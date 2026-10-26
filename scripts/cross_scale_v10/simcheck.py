#!/usr/bin/env python3
"""Goal v10: offline simulation vs the real frozen wrappers on the development set (deploy_dev; protocol 6.4).
Decisions agree when the real wrapper took the same path / action as common.decide on the MEASURE record.

  $FP_PY scripts/cross_scale_v10/simcheck.py   -> results/cross_scale_v10/simcheck.json
"""
import collections
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import devlib as L  # noqa: E402


def main():
    rows = L.dev_table()
    fr = json.load(open(os.path.join(L.CFG, "frozen", "FREEZE.json")))
    real = {}
    for r in L.records("deploy_dev"):
        real[(r["instance"], r["strategy"])] = r
    out = {}
    for key in ("main_wrapper", "reference_wrapper"):
        path = fr.get(key)
        if not path:
            continue
        s = json.load(open(os.path.join(L.ROOT, path)))
        probes = [(p["arm"], p["tau"]) for p in s["probes"]]
        agree, diffs, rel, n, mism = 0, [], [], 0, []
        for i, row in rows.items():
            pr = L.pre(row, s.get("static", False), probes)
            if pr.answered:
                sim_path, sim_act = "probe_solved", pr.answer_arm + "_probe"
                sim_cost = pr.cost
            else:
                sim_act, sim_path = L.common.decide(s, pr.x, pr.started)
                sim_cost = pr.cost + row["t"][sim_act]
            r = real.get((i, path))
            if r is None:
                continue
            n += 1
            same = (r.get("action") == sim_act)
            agree += same
            if not same:
                mism.append({"instance": i, "sim": [sim_path, sim_act], "real": [r.get("path"), r.get("action")]})
            diffs.append(r["cpu"] - sim_cost)
            rel.append(r["cpu"] / sim_cost if sim_cost > 0 else None)
        out[key] = {"n": n, "decision_agreement": agree, "mismatches": mism,
                    "real_minus_sim_median": statistics.median(diffs), "real_minus_sim_mean": statistics.mean(diffs),
                    "real_minus_sim_total": sum(diffs),
                    "real_over_sim_q": {q: sorted(x for x in rel if x)[int(q * (len(rel) - 1))] for q in (0.05, 0.5, 0.95)},
                    "real_total": sum(real[(i, path)]["cpu"] for i in rows if (i, path) in real),
                    "real_paths": dict(collections.Counter(real[(i, path)].get("path") for i in rows if (i, path) in real))}
    json.dump(out, open(os.path.join(L.RES, "simcheck.json"), "w"), indent=1, sort_keys=True)
    for k, v in out.items():
        print(k, {x: v[x] for x in v if x != "mismatches"}, "mismatches", len(v["mismatches"]))


if __name__ == "__main__":
    main()
