#!/usr/bin/env python3
"""Plan v7 stage 2 (oracle certificates; docs/COMPLETION_RUN_PLAN_V7.md section 4).

  python3 scripts/completion_v7/stage2_plan.py [--budget-cpu-hours 10]

After stage 1 and normalize.py: for every instance whose three v6 arms were
all censored and whose D completed (stage 1) at b > 300 s, F+ and F- are run
from scratch until they complete or reach b CPU seconds (cap = b + 1; status
noncompetitive_bound). All eligible instances are scheduled in increasing b, without a CPU-hour
budget. Finite per-arm bounds certify the oracle; they are not resource caps.
Writes configs/completion_v7/stage2_unlimited.json by default.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import resource_policy

RES = os.path.join(ROOT, "results", "completion_v7")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-cpu-hours", type=float, default=None,
                    help="deprecated and ignored; all eligible arms are scheduled")
    ap.add_argument("--out", default=os.path.join(ROOT, "configs", "completion_v7", "stage2_unlimited.json"))
    a = ap.parse_args()
    policy = resource_policy.load_policy(ROOT)
    with open(os.path.join(RES, "normalized.json")) as records_file:
        norm = {(r["instance"], r["method"]): r for r in json.load(records_file)}
    with open(os.path.join(RES, "reuse_records.json")) as records_file:
        reuse = {(r["instance"], r["method"]): r for r in json.load(records_file)}
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
    skipped = []
    for b, h, arms in cands:
        cost = (b + 1) * len(arms)
        used += cost
        jobs += [{"instance": h, "method": x, "kind": "fixed", "cap_cpu": round(b + 1.0, 3), "cap_kind": "oracle_noncompetitive_bound"} for x in arms]
    plan = {"stage": "stage2", "description": "v7 stage 2: F+/F- from scratch capped at the completed D time b (oracle certificates), smallest b first",
            "budget_cpu_hours": None, "resource_policy_id": policy["policy_id"], "planned_cpu_hours_upper_bound": used / 3600, "jobs": jobs,
            "not_scheduled": skipped}
    plan = resource_policy.prepare_plan(plan, policy)
    with open(a.out, "w") as plan_file:
        json.dump(plan, plan_file, indent=1)
    print(json.dumps({"jobs": len(jobs), "instances": len({j['instance'] for j in jobs}),
                      "planned_cpu_hours": round(used / 3600, 2), "not_scheduled": len(skipped)}))


if __name__ == "__main__":
    main()
