#!/usr/bin/env python3
"""Plan v7 stage 2 (oracle certificates; docs/COMPLETION_RUN_PLAN_V7.md section 4).

  python3 scripts/completion_v7/stage2_plan.py [--budget-cpu-hours 10]

After stage 1 and normalize.py: for every instance whose three v6 arms were
all censored and whose D completed (stage 1) at b > 300 s, F+ and F- are run
from scratch until they complete or reach b CPU seconds (cap = b + 1; status
noncompetitive_bound). Instances are taken in increasing b while the summed
caps stay within the budget (the runner's budget stop is a second guard).
Writes configs/completion_v7/stage2.json.
"""

import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RES = os.path.join(ROOT, "results", "completion_v7")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-cpu-hours", type=float, default=10.0)
    a = ap.parse_args()
    norm = {(r["instance"], r["method"]): r for r in json.load(open(os.path.join(RES, "normalized.json")))}
    reuse = {(r["instance"], r["method"]): r for r in json.load(open(os.path.join(RES, "reuse_records.json")))}
    cands = []
    for (h, m), r in norm.items():
        if m != "D" or r["status"] != "solved" or r["cpu_seconds"] <= 300:
            continue
        if not all(reuse[(h, x)]["status"] == "censored" for x in ("D", "Fp", "Fm")):
            continue
        b = r["cpu_seconds"]
        arms = [x for x in ("Fp", "Fm") if norm[(h, x)]["status"] != "solved" and norm[(h, x)]["cpu_seconds"] < b]
        if arms:
            cands.append((b, h, arms))
    cands.sort()
    jobs, used = [], 0.0
    budget = a.budget_cpu_hours * 3600
    skipped = []
    for b, h, arms in cands:
        cost = (b + 1) * len(arms)
        if used + cost > budget:
            skipped.append({"instance": h, "b": b, "arms": arms})
            continue
        used += cost
        jobs += [{"instance": h, "method": x, "kind": "fixed", "cap_cpu": round(b + 1.0, 3)} for x in arms]
    plan = {"stage": "stage2", "description": "v7 stage 2: F+/F- from scratch capped at the completed D time b (oracle certificates), smallest b first",
            "budget_cpu_hours": a.budget_cpu_hours, "planned_cpu_hours_upper_bound": used / 3600, "jobs": jobs,
            "not_scheduled": skipped}
    json.dump(plan, open(os.path.join(ROOT, "configs", "completion_v7", "stage2.json"), "w"), indent=1)
    print(json.dumps({"jobs": len(jobs), "instances": len({j['instance'] for j in jobs}),
                      "planned_cpu_hours": round(used / 3600, 2), "not_scheduled": len(skipped)}))


if __name__ == "__main__":
    main()
