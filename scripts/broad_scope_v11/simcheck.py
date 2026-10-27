#!/usr/bin/env python3
"""Goal v11 protocol 7.4: offline simulation vs the real frozen structural wrapper on the development 240
(stage deploy_dev). Same decision code; compares action, path, solved status and CPU.

  $FP_PY scripts/broad_scope_v11/simcheck.py   -> results/broad_scope_v11/simcheck.json
"""
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import devlib as L  # noqa: E402


def main():
    fr = json.load(open(os.path.join(L.CFG, "frozen", "FREEZE.json")))
    path = fr["files"]["structural"]["path"]
    strat = json.load(open(os.path.join(L.ROOT, path)))
    rows = L.pool_table()
    dev = sorted(i for i, r in rows.items() if r["role"] == "development")
    sim = L.Sim(rows)
    cfg = {"static": True, "probes": []}
    simulated = sim.apply(cfg, strat, dev)
    real = {}
    for r in L.records("deploy_dev"):
        if r.get("strategy") == path:
            real[r["instance"]] = r
    out, agree_a, agree_s, diffs = {}, 0, 0, []
    for i in dev:
        s, r = simulated[i], real.get(i)
        if r is None:
            continue
        rs = L.ok(r)
        out[i] = {"sim_action": s[3], "real_action": r.get("action"), "sim_path": s[4], "real_path": r.get("path"),
                  "sim_solved": s[0], "real_solved": rs, "sim_cpu": s[1], "real_cpu": r["cpu"]}
        agree_a += s[3] == r.get("action")
        agree_s += s[0] == rs
        if s[0] and rs:
            diffs.append(r["cpu"] / max(s[1], 1e-3))
    res = {"n": len(out), "action_agree": agree_a, "solved_agree": agree_s,
           "cpu_ratio_real_over_sim": {"median": statistics.median(diffs) if diffs else None,
                                       "q10": sorted(diffs)[len(diffs) // 10] if diffs else None,
                                       "q90": sorted(diffs)[9 * len(diffs) // 10] if diffs else None},
           "total_sim": sum(v["sim_cpu"] for v in out.values()), "total_real": sum(min(v["real_cpu"], L.CAP) for v in out.values()),
           "per_instance": out}
    json.dump(res, open(os.path.join(L.RES, "simcheck.json"), "w"), indent=1)
    print({k: v for k, v in res.items() if k != "per_instance"})


if __name__ == "__main__":
    main()
