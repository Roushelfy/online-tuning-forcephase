#!/usr/bin/env python3
"""v8 formal panel: generation plan, freeze (split, panels, evaluation configs) and run plans
(docs/STRATIFIED_PROTOCOL_V8.md sections 3-5). Standard library only.

  panel.py gen-plan                         -> configs/stratified_v8/formal_gen.json   (from scales.json)
  panel.py freeze --manifest M              -> panel_dev.txt, panel_holdout.txt, split.json, eval_*.json
  panel.py run-plan --split dev|holdout [--strategy S]  -> configs/stratified_v8/s1_dev.json / s3_holdout.json
"""

import argparse
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CFG = os.path.join(ROOT, "configs", "stratified_v8")
P = json.load(open(os.path.join(CFG, "protocol.json")))
TYPES, SCALES = P["types"], P["scales"]


def split_hash(bid):
    return hashlib.sha256((bid + ":v8split").encode()).hexdigest()


def gen_plan():
    sc = json.load(open(os.path.join(CFG, "scales.json")))
    if not sc.get("N"):
        raise SystemExit("no feasible formal size in scales.json")
    nd, nh = sc["per_cell"]
    inst = []
    for t in TYPES:
        for s in SCALES:
            for j in range(nd + nh):
                inst.append({"id": f"v8-{t}-{s}-{j:02d}", "type": t, "scale": s, "param": sc["params"][t][s],
                             "seed": 8100000 + 10000 * TYPES.index(t) + 1000 * SCALES.index(s) + j, "role": "formal"})
    json.dump({"stage": "formal", "N": sc["N"], "instances": inst}, open(os.path.join(CFG, "formal_gen.json"), "w"), indent=1)
    print(len(inst))


def freeze(manifest):
    sc = json.load(open(os.path.join(CFG, "scales.json")))
    nd, nh = sc["per_cell"]
    man = json.load(open(manifest))
    rows = man["instances"]
    # duplicates against the pilot instances as well
    seen = {}
    for mp in ("pilot_r1_manifest.json", "pilot_r2_manifest.json"):
        p = os.path.join(ROOT, "results", "stratified_v8", mp)
        if os.path.exists(p):
            for r in json.load(open(p))["instances"]:
                seen[r["canonical_sha256"]] = r["id"]
    for r in rows:
        if r["canonical_sha256"] in seen:
            raise SystemExit(f"duplicate of {seen[r['canonical_sha256']]}: {r['id']}")
        seen[r["canonical_sha256"]] = r["id"]
    split = {}
    for t in TYPES:
        for s in SCALES:
            cell = sorted([r for r in rows if r["type"] == t and r["scale"] == s], key=lambda r: split_hash(r["id"]))
            if len(cell) != nd + nh:
                raise SystemExit(f"cell {t}-{s} has {len(cell)} instances")
            for k, r in enumerate(cell):
                split[r["id"]] = {"split": "dev" if k < nd else "holdout", "type": t, "scale": s, "rank": k,
                                  "split_hash": split_hash(r["id"]), "sha256": r["sha256"]}
    json.dump(split, open(os.path.join(CFG, "split.json"), "w"), indent=1, sort_keys=True)
    for part in ("dev", "holdout"):
        ids = sorted(i for i, v in split.items() if v["split"] == part)
        with open(os.path.join(CFG, f"panel_{part}.txt"), "w") as f:
            f.write(f"# v8 {part} panel ({len(ids)} base instances), frozen by scripts/stratified_v8/panel.py\n")
            f.writelines(i + "\n" for i in ids)
        methods = ["D", "Fp", "Fm"] + (["SBS", "W"] if part == "holdout" else [])
        cfg = {"schema_version": 1, "phase": f"stratified_v8_{part}", "metric": "mean_completed_cpu_seconds",
               "unit": "process_tree_cpu_seconds", "aggregation": "arithmetic_mean_over_fixed_panel",
               "panel_file": f"configs/stratified_v8/panel_{part}.txt", "panel_size": len(ids), "methods": methods,
               "baseline": "D", "required_methods": methods, "oracle_actions": ["D", "Fp", "Fm"],
               "require_oracle_complete": True, "scoring_cutoff_cpu_seconds": None, "timeout_penalty": None,
               "incomplete_mean": None, "drop_incomplete_instances": False,
               "include_observation_and_algorithmic_restart_cpu": True, "independent_verification_required": True,
               "checker_cpu_in_primary_metric": False, "formal_seed": 0}
        json.dump(cfg, open(os.path.join(CFG, f"eval_{part}.json"), "w"), indent=1)
    print({p: sum(1 for v in split.values() if v["split"] == p) for p in ("dev", "holdout")})


def run_plan(part, strategy):
    split = json.load(open(os.path.join(CFG, "split.json")))
    cap = P["formal"]["cap_cpu_per_run"]
    methods = ["D", "Fp", "Fm"] + (["W"] if strategy else [])
    jobs = []
    for s in ("L", "M", "S"):
        for t in TYPES:
            cell = sorted([i for i, v in split.items() if v["split"] == part and v["type"] == t and v["scale"] == s],
                          key=lambda i: split[i]["split_hash"])
            for i in cell:
                for m in methods:
                    j = {"instance": i, "sha256": split[i]["sha256"], "method": m, "rep": 0, "cap_cpu": cap}
                    if m == "W":
                        j["strategy"] = strategy
                    jobs.append(j)
    name = "s1_dev" if part == "dev" else "s3_holdout"
    json.dump({"stage": name, "jobs": jobs}, open(os.path.join(CFG, f"{name}.json"), "w"), indent=1)
    print(name, len(jobs))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen-plan")
    f = sub.add_parser("freeze")
    f.add_argument("--manifest", required=True)
    r = sub.add_parser("run-plan")
    r.add_argument("--split", choices=["dev", "holdout"], required=True)
    r.add_argument("--strategy")
    a = ap.parse_args()
    if a.cmd == "gen-plan":
        gen_plan()
    elif a.cmd == "freeze":
        freeze(a.manifest)
    else:
        run_plan(a.split, a.strategy)


if __name__ == "__main__":
    main()
