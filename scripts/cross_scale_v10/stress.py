#!/usr/bin/env python3
"""Goal v10 optional stress test on the old 55 competition problems (docs/CROSS_SCALE_PROTOCOL_V10.md section 9).

  python3 scripts/cross_scale_v10/stress.py   -> results/cross_scale_v10/stress_old55.json

3600 s view per instance x method: D from the historical records (scripts/online_selection_v9/timeout_view.py,
fully determined); F+ / F- from the historical records plus the new 3600 s runs (stress_old55_fixed) for the
records that only had v6's 300 s bound; W_main / W_ref from stress_old55. Never 3600 as a completion time.
"""
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts", "online_selection_v9"))
import timeout_view as TV  # noqa: E402

DATA = TV.DATA
RUNS = os.path.join(DATA, "runs", "cross_scale_v10")
TP = [1, 10, 60, 600, 3600]


def recs(stage):
    for p in glob.glob(os.path.join(RUNS, stage, "*.json")):
        if not p.endswith(("progress.json", "effective_plan.json")):
            yield json.load(open(p))


def main():
    P, ev = TV.old55()
    fr = json.load(open(os.path.join(ROOT, "configs", "cross_scale_v10", "frozen", "FREEZE.json")))
    wmap = {fr["main_wrapper"]: "W_main", fr["reference_wrapper"]: "W_ref"}
    new = collections.defaultdict(list)
    for r in recs("stress_old55_fixed"):
        good = TV.ok(r)
        new[(r["instance"], r["method"])].append((r["cpu"], good, {10: "SAT", 20: "UNSAT"}.get(r.get("exit_code"))))
    w = {}
    for r in recs("stress_old55"):
        w[(r["instance"], wmap.get(r["strategy"]))] = r
    per, methods = {}, ["D", "Fp", "Fm", "W_main", "W_ref"]
    for h in P:
        per[h] = {}
        for m in ("D", "Fp", "Fm"):
            st, t, ans = TV.classify(ev[(h, m)] + new.get((h, m), []))
            per[h][m] = {"status": st, "solved": st == "solved", "cpu": t, "answer": ans,
                         "new_3600_run": bool(new.get((h, m)))}
        for m in ("W_main", "W_ref"):
            r = w.get((h, m))
            if r is None:
                per[h][m] = {"status": "missing", "solved": False, "cpu": None}
                continue
            good = TV.ok(r) and r["cpu"] <= TV.LIMIT
            per[h][m] = {"status": "solved" if good else r["status"], "solved": good, "cpu": r["cpu"] if good else None,
                         "path": r.get("path"), "action": r.get("action"), "pre_exec_cpu": r.get("pre_exec_cpu"),
                         "actual_cpu": r["cpu"]}
    out = {"panel": "old 55 (v7)", "n": len(P), "limit": TV.LIMIT, "methods": methods, "per_instance": per, "summary": {}}
    for m in methods:
        rows = [per[h][m] for h in P]
        out["summary"][m] = {"solved": sum(r["solved"] for r in rows),
                             "statuses": dict(collections.Counter(r["status"] for r in rows)),
                             "time_points": {str(t): sum(1 for r in rows if r["solved"] and r["cpu"] <= t) for t in TP},
                             "complete_mean": None if any(not r["solved"] for r in rows) else sum(r["cpu"] for r in rows) / len(P)}
        if m.startswith("W"):
            out["summary"][m]["paths"] = dict(collections.Counter(r.get("path") for r in rows))
            out["summary"][m]["actions"] = dict(collections.Counter(r.get("action") for r in rows))
    for a, b in (("W_main", "D"), ("W_main", "Fm"), ("W_main", "W_ref"), ("W_ref", "D"), ("Fm", "D"), ("Fp", "D")):
        out.setdefault("paired", {})[f"{a}_vs_{b}"] = {
            "gained": [h for h in P if per[h][a]["solved"] and not per[h][b]["solved"]],
            "lost": [h for h in P if per[h][b]["solved"] and not per[h][a]["solved"]]}
    out["any_fixed_solved"] = sum(1 for h in P if any(per[h][m]["solved"] for m in ("D", "Fp", "Fm")))
    out["not_reconstructable_left"] = {m: [h for h in P if per[h][m]["status"] == "not_reconstructable"] for m in ("Fp", "Fm")}
    json.dump(out, open(os.path.join(ROOT, "results", "cross_scale_v10", "stress_old55.json"), "w"), indent=1, sort_keys=True)
    print({m: out["summary"][m]["solved"] for m in methods}, "any fixed", out["any_fixed_solved"],
          {k: (len(v["gained"]), len(v["lost"])) for k, v in out["paired"].items()})


if __name__ == "__main__":
    main()
