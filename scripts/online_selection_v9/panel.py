#!/usr/bin/env python3
"""v9 formal panels and run plans (docs/ONLINE_SELECTION_PROTOCOL_V9.md sections 2.3, 3, 5-8).
Standard library only.

  panel.py gen-plan                      -> configs/online_selection_v9/formal_gen.json (main 540, controls 30, extrapolation 90)
  panel.py freeze --manifest M           -> split.json, panel_*.txt, eval_*.json
  panel.py plan <name> [--strategy S ...] -> configs/online_selection_v9/<name>.json
       names: s1_dev, p_dev, ref_dev, mech_dev, holdout, extrap, robust (see protocol)
"""

import argparse
import glob
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CFG = os.path.join(ROOT, "configs", "online_selection_v9")
RES = os.path.join(ROOT, "results", "online_selection_v9")
P = json.load(open(os.path.join(CFG, "protocol.json")))
TI, SI = P["type_index"], P["scale_index"]
MAIN_TYPES, SCALES = ("rand3", "col3", "assign2"), ("S", "M", "L")
TYPE_ORDER = ("rand3", "col3", "assign2", "assign0")
REF = "configs/online_selection_v9/strategies/ref_D2_Fp.json"


def split_hash(i):
    return hashlib.sha256((i + ":v9split").encode()).hexdigest()


def gen_plan():
    sc = json.load(open(os.path.join(CFG, "scales.json")))
    st = sc["assign2_structure"]
    inst = []
    for t in MAIN_TYPES:
        for s in SCALES:
            for j in range(60):
                r = {"id": f"v9-{t}-{s}-{j:02d}", "type": t, "scale": s, "param": sc["params"][t][s],
                     "seed": 9100000 + 10000 * TI[t] + 1000 * SI[s] + j, "role": "main"}
                if t == "assign2":
                    r["structure"] = st
                inst.append(r)
    for s in SCALES:
        for j in range(P["formal"]["controls"]["per_scale"]):
            inst.append({"id": f"v9-assign0-{s}-{j:02d}", "type": "assign0", "scale": s, "param": sc["params"]["assign0"][s],
                         "seed": 9200000 + 1000 * SI[s] + j, "role": "control"})
    for t in MAIN_TYPES:
        for lv, p in enumerate(sc["extrapolation"][t]):
            for j in range(P["formal"]["extrapolation"]["per_level"]):
                r = {"id": f"v9x-{t}-X{lv + 1}-{j:02d}", "type": t, "scale": f"X{lv + 1}", "param": p,
                     "seed": 9300000 + 10000 * TI[t] + 1000 * lv + j, "role": "extrapolation"}
                if t == "assign2":
                    r["structure"] = st
                inst.append(r)
    json.dump({"stage": "formal", "instances": inst}, open(os.path.join(CFG, "formal_gen.json"), "w"), indent=1)
    print(len(inst))


def freeze(manifest):
    rows = json.load(open(manifest))["instances"]
    seen = {}
    others = glob.glob(os.path.join(RES, "pilot_r*_manifest.json")) + \
        glob.glob(os.path.join(ROOT, "results", "stratified_v8", "*manifest.json"))
    for mp in others:
        for r in json.load(open(mp))["instances"]:
            for k in ("canonical_sha256", "invariant_sha256"):
                if r.get(k):
                    seen[(k, r[k])] = r["id"]
    for r in rows:
        for k in ("canonical_sha256", "invariant_sha256"):
            if (k, r[k]) in seen:
                raise SystemExit(f"duplicate {k} of {seen[(k, r[k])]}: {r['id']}")
            seen[(k, r[k])] = r["id"]
    split = {}
    for t in TYPE_ORDER:
        for s in SCALES:
            cell = sorted([r for r in rows if r["type"] == t and r["scale"] == s and r["role"] != "extrapolation"],
                          key=lambda r: split_hash(r["id"]))
            for k, r in enumerate(cell):
                if r["role"] == "main":
                    part = "dev" if k < 30 else ("H1", "H2", "H3")[(k - 30) // 10]
                else:
                    part = "dev" if k < 5 else "Hc"
                split[r["id"]] = {"split": part, "type": t, "scale": s, "rank": k, "role": r["role"],
                                  "split_hash": split_hash(r["id"]), "sha256": r["sha256"], "param": r["param"]}
    for r in rows:
        if r["role"] == "extrapolation":
            split[r["id"]] = {"split": "X", "type": r["type"], "scale": r["scale"], "rank": None, "role": r["role"],
                              "split_hash": split_hash(r["id"]), "sha256": r["sha256"], "param": r["param"]}
    json.dump(split, open(os.path.join(CFG, "split.json"), "w"), indent=1, sort_keys=True)
    panels = {"dev": lambda v: v["role"] == "main" and v["split"] == "dev",
              "holdout": lambda v: v["role"] == "main" and v["split"] in ("H1", "H2", "H3"),
              "H1": lambda v: v["split"] == "H1", "H2": lambda v: v["split"] == "H2", "H3": lambda v: v["split"] == "H3",
              "controls_dev": lambda v: v["role"] == "control" and v["split"] == "dev",
              "controls_holdout": lambda v: v["role"] == "control" and v["split"] == "Hc",
              "extrapolation": lambda v: v["role"] == "extrapolation"}
    for name, f in panels.items():
        ids = sorted(i for i, v in split.items() if f(v))
        with open(os.path.join(CFG, f"panel_{name}.txt"), "w") as fh:
            fh.write(f"# v9 panel {name} ({len(ids)} base instances), frozen by scripts/online_selection_v9/panel.py\n")
            fh.writelines(i + "\n" for i in ids)
        print(name, len(ids))


def ordered(pred):
    split = json.load(open(os.path.join(CFG, "split.json")))
    out = []
    for s in ("L", "M", "S", "X1", "X2"):
        for t in TYPE_ORDER:
            out += sorted([i for i, v in split.items() if v["type"] == t and v["scale"] == s and pred(i, v)],
                          key=lambda i: split[i]["split_hash"])
    return out, split


def plan(name, strategies):
    jobs = []
    if name in ("s1_dev", "p_dev", "ref_dev"):
        ids, split = ordered(lambda i, v: v["split"] == "dev")
        for i in ids:
            b = {"instance": i, "sha256": split[i]["sha256"], "rep": 0}
            if name == "s1_dev":
                jobs += [dict(b, method=m) for m in ("D", "Fp", "Fm")]
            elif name == "p_dev":
                jobs += [dict(b, method="PROBE", tau=t) for t in P["selection"]["tau_grid"]]
            else:
                jobs.append(dict(b, method="W", strategy=REF))
    elif name == "mech_dev":
        sel = json.load(open(os.path.join(RES, "mechanism_instances.json")))["instances"]
        ids, split = ordered(lambda i, v: i in sel)
        for i in ids:
            jobs += [{"instance": i, "sha256": split[i]["sha256"], "rep": 0, "method": m}
                     for m in P["mechanism"]["configs"]]
    elif name in ("holdout", "extrap"):
        want = (lambda i, v: v["split"] in ("H1", "H2", "H3", "Hc")) if name == "holdout" else (lambda i, v: v["split"] == "X")
        ids, split = ordered(want)
        for i in ids:
            b = {"instance": i, "sha256": split[i]["sha256"], "rep": 0}
            jobs += [dict(b, method=m) for m in ("D", "Fp", "Fm")]
            jobs += [dict(b, method="W", strategy=s) for s in strategies]
    else:
        raise SystemExit(f"unknown plan {name}")
    json.dump({"stage": name, "jobs": jobs}, open(os.path.join(CFG, f"{name}.json"), "w"), indent=1)
    print(name, len(jobs))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen-plan")
    f = sub.add_parser("freeze")
    f.add_argument("--manifest", required=True)
    p = sub.add_parser("plan")
    p.add_argument("name")
    p.add_argument("--strategy", action="append", default=[])
    a = ap.parse_args()
    if a.cmd == "gen-plan":
        gen_plan()
    elif a.cmd == "freeze":
        freeze(a.manifest)
    else:
        plan(a.name, a.strategy)


if __name__ == "__main__":
    main()
