#!/usr/bin/env python3
"""Goal v11 S4 (docs/BROAD_SCOPE_PROTOCOL_V11.md section 7.2-7.3): nested grouped CV of the method families on the
training pool (discovery + development), leave-one-family-out and leave-one-level-out diagnostics, posthoc
family-label routing bound, the main-strategy rule and the freeze. Training pool only.

  $FP_PY scripts/broad_scope_v11/selection.py cv       -> results/broad_scope_v11/selection.json
  $FP_PY scripts/broad_scope_v11/selection.py freeze   -> configs/broad_scope_v11/frozen/*.json, FREEZE.json
"""
import argparse
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import devlib as L  # noqa: E402

FAMS = ["SBS", "ST", "TR", "PR"]
MARGIN = L.P["replace_margin"]
OUT = os.path.join(L.RES, "selection.json")
FROZEN = os.path.join(L.CFG, "frozen")


def compare(rows, a, b, ids=None):
    ids = sorted(ids or a)
    cells = [L.cell(rows[i]) for i in ids]
    x, y = [a[i][1] for i in ids], [b[i][1] for i in ids]
    pt, lo, hi = L.strat_boot(cells, x, y)
    return {"gain": pt, "ci": [lo, hi], "solved": [sum(1 for i in ids if a[i][0]), sum(1 for i in ids if b[i][0])],
            "gained": [i for i in ids if a[i][0] and not b[i][0]], "lost": [i for i in ids if b[i][0] and not a[i][0]]}


def main_rule(summ):
    trace, inc = [], "SBS"
    for f in L.P["complexity_order"][1:]:
        kf, ki = (summ[f]["solved"], summ[f]["total"]), (summ[inc]["solved"], summ[inc]["total"])
        beats = L.better(kf, ki, MARGIN)
        note = {"family": f, "vs": inc, "beats_incumbent": beats}
        if f == "PR":
            kc = (summ["NC"]["solved"], summ["NC"]["total"])
            note["beats_NC"] = L.better(kf, kc, MARGIN)
            beats = beats and note["beats_NC"]
        note["replaces"] = beats
        trace.append(note)
        if beats:
            inc = f
    st = min(("ST", "TR"), key=lambda f: (L.crit_key((summ[f]["solved"], summ[f]["total"])), f != "ST"))
    return inc, st, trace


def by_group(rows, oof, key):
    out = {}
    for i, v in oof.items():
        g = key(rows[i])
        o = out.setdefault(g, {"n": 0, "solved": 0, "total": 0.0})
        o["n"] += 1
        o["solved"] += int(v[0])
        o["total"] += v[1]
    return out


def posthoc_family_routing(sim, folds):
    """Not deployable: the true family label -> the family's best fixed action on the training fold."""
    rows, oof = sim.rows, {}
    for k in sorted(set(folds.values())):
        train = [i for i in rows if folds[i] != k]
        for i in (i for i in rows if folds[i] == k):
            f = rows[i]["family"]
            tr_f = [j for j in train if rows[j]["family"] == f] or train
            a = L.best_fixed(rows, None, tr_f)
            s, c = L.outcome(rows[i], None, a)
            oof[i] = (s, c, 0.0, a, "label_route")
    return oof


def oracle(rows):
    out = {}
    for i, r in rows.items():
        sol = [(r["t"][a], a) for a in L.ACTS if r["ok"].get(a)]
        if sol:
            t, a = min(sol)
            out[i] = (True, t, 0.0, a, "oracle")
        else:
            out[i] = (False, L.CAP, 0.0, None, "oracle")
    return out


def run_cv(sim, folds, label):
    res, chosen = {}, {}
    for f in FAMS + ["V10"]:
        t0 = time.time()
        res[f], chosen[f] = L.cv(sim, f, folds)
        print(f"[{label}] {f}: {L.summarize(res[f])['solved']} solved, total {L.summarize(res[f])['total']:.1f} "
              f"({time.time() - t0:.0f} s)", flush=True)
    res["NC"], chosen["NC"] = L.cv(sim, "NC", folds, {k: v["cfg"] for k, v in chosen["PR"].items()})
    return res, chosen


def cmd_cv():
    rows = L.pool_table()
    missing = [i for i, r in rows.items() if set(r["t"]) != set(L.ACTS) or "m" not in r]
    if missing:
        raise SystemExit(f"{len(missing)} pool instances lack fixed or MEASURE records, e.g. {missing[:3]}")
    sim = L.Sim(rows)
    folds = {i: r["fold"] for i, r in rows.items()}
    res, chosen = run_cv(sim, folds, "outer")
    res["label_route"] = posthoc_family_routing(sim, folds)
    res["oracle"] = oracle(rows)
    for a in L.ACTS:
        res["fixed_" + a] = {i: (*L.outcome(rows[i], None, a), 0.0, a, "fixed") for i in rows}
    summ = {f: L.summarize(o) for f, o in res.items()}
    main, sstar, trace = main_rule(summ)
    comps = {}
    for a, b in (("PR", "NC"), ("ST", "SBS"), ("TR", "SBS"), ("PR", "SBS"), ("TR", "ST"), ("PR", "TR"), ("PR", "ST"),
                 ("V10", "SBS"), ("label_route", "SBS"), ("oracle", "SBS")):
        comps[f"{a}_vs_{b}"] = compare(rows, res[a], res[b])
    diag = {}
    for name, key in (("leave_one_family_out", lambda r: r["family"]), ("leave_one_level_out", lambda r: r["level"])):
        f2 = {i: key(r) for i, r in rows.items()}
        dres, dch = run_cv(sim, f2, name)
        dres["label_route"] = posthoc_family_routing(sim, f2)
        diag[name] = {"summary": {f: L.summarize(o) for f, o in dres.items()},
                      "by_heldout": {f: by_group(rows, o, key) for f, o in dres.items()},
                      "chosen": {f: {str(k): L.jsonable(v["cfg"]) for k, v in ch.items()} for f, ch in dch.items()}}
    out = {"n": len(rows), "summary": summ, "main_family": main, "structural_control": sstar, "rule_trace": trace,
           "comparisons": comps,
           "by_family": {f: by_group(rows, o, lambda r: r["family"]) for f, o in res.items()},
           "by_cell": {f: {"|".join(k): v for k, v in by_group(rows, o, L.cell).items()} for f, o in res.items()},
           "chosen": {f: {str(k): L.jsonable(v["cfg"]) for k, v in ch.items()} for f, ch in chosen.items()},
           "oof": {f: {i: list(v) for i, v in o.items()} for f, o in res.items()},
           "diagnostics": diag}
    json.dump(out, open(OUT, "w"), indent=1, default=str)
    print("main family:", main, "structural control:", sstar)
    for t in trace:
        print(t)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def cmd_freeze():
    sel = json.load(open(OUT))
    rows = L.pool_table()
    sim = L.Sim(rows)
    ids = sorted(rows)
    os.makedirs(FROZEN, exist_ok=True)
    main, sstar = sel["main_family"], sel["structural_control"]
    out = {"main_family": main, "structural_control": sstar, "files": {}}

    def freeze(fam, name, pr_cfg=None):
        if fam == "SBS":
            strat = {"kind": "fixed", "action": L.best_fixed(rows, None, ids)}
            cfg = {"fixed": strat["action"]}
        else:
            cfg, strat, _ = L.run_family(sim, fam, ids, [], pr_cfg)
        strat = dict(strat, name=name, family=fam, config=L.jsonable(cfg))
        if "probes" in strat:
            strat["probes"] = [{"arm": a, "tau": float(t)} for a, t in strat["probes"]]
        p = os.path.join(FROZEN, name + ".json")
        json.dump(strat, open(p, "w"), indent=1, sort_keys=True)
        out["files"][name] = {"path": os.path.relpath(p, L.ROOT), "sha256": sha(p), "family": fam}
        return cfg, strat

    mcfg, _ = freeze(main, "main")
    if sstar != main:
        freeze(sstar, "structural")
    if main == "PR":
        freeze("NC", "nc", mcfg)
    sbs = L.best_fixed(rows, None, ids)
    out.update(dev_sbs=sbs, deploy={"fixed": list(L.ACTS), "wrappers": sorted(out["files"]),
                                    "v10": {"wrapper": "scripts/cross_scale_v10/wrapper.py",
                                            "strategy": "configs/cross_scale_v10/frozen/main.json"}},
               selection_sha256=sha(OUT), protocol_sha256=sha(os.path.join(L.CFG, "protocol.json")),
               utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    json.dump(out, open(os.path.join(FROZEN, "FREEZE.json"), "w"), indent=1, sort_keys=True)
    print(json.dumps(out, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cv", "freeze"])
    a = ap.parse_args()
    cmd_cv() if a.cmd == "cv" else cmd_freeze()


if __name__ == "__main__":
    main()
