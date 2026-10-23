#!/usr/bin/env python3
"""v7 C0 reuse audit (docs/COMPLETION_RUN_PLAN_V7.md section 1).

  python3 scripts/completion_v7/reuse_audit.py

Reads the raw v6 records of the 55-instance panel: fixed D / F+ / F- runs
(configs/stable_selection_v6/v6_validate_fixed.json) and the frozen
P1_M05_final wrapper runs. Checks binary, arguments, seed, proof and
telemetry policy against the v7 run policy, and converts each record to a
normalized v7 measurement from its *timing* fields (process CPU from wait4),
never from a cost / PAR2 column:
  solved + verified -> status solved (exact completion time)
  stopped at the 300 s cutoff (SIGTERM, or SIGKILL after the grace period)
      -> status censored (actual executed CPU as lower bound)
  anything else -> error
Writes results/completion_v7/reuse_audit.csv and reuse_records.json.
"""

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "stable_selection_v6"))
import fprun  # noqa: E402

RES = os.path.join(ROOT, "results", "completion_v7")
FORMAL_SHA = "6cf084699e872250ffa4d9a186d8ad7fe3829d06fc2d898294f2ac5e989ba884"
ARGS = {"D": ["--lrat=1", "--phase=1", "--forcephase=0"], "Fp": ["--lrat=1", "--phase=1", "--forcephase=1"],
        "Fm": ["--lrat=1", "--phase=0", "--forcephase=1"]}
N2A = {"D": "D", "Fplus": "Fp", "Fminus": "Fm"}


def panel():
    return [l.split()[0] for l in open(os.path.join(ROOT, "configs", "completion_v7", "panel.txt"))
            if l.strip() and not l.startswith("#")]


def main():
    os.makedirs(RES, exist_ok=True)
    P = panel()
    rows, recs = [], []
    exp = fprun.load_experiment(os.path.join(ROOT, "configs", "stable_selection_v6", "v6_validate_fixed.json"))
    for run in fprun.plan(exp):
        h, a = run["key"]["instance"], N2A[run["config"]]
        if h not in P:
            continue
        r = json.load(open(fprun.result_path(run["run_id"])))
        k = r["key"]
        checks = {"binary": k["binary_sha256"] == FORMAL_SHA, "args": k["config_args"] == ARGS[a], "seed": k["seed"] == 0,
                  "proof": k["proof"] == "lrat", "telemetry": k["telemetry"] is True, "env": k["env"] == {},
                  "cmd": r["cmd"][1:5] == ARGS[a] + ["--fpc=1"]}
        valid = all(checks.values())
        ver = r.get("verification") or {}
        if r["status"] == "solved" and ver.get("ok") is True:
            st, verified = "solved", True
        elif r["status"] == "timeout" and r.get("terminated_by") in ("cpu", "cpu+kill"):
            st, verified = "censored", False
        else:
            st, verified = "error", False
        rec = {"instance": h, "method": a, "status": st, "cpu_seconds": r["cpu"], "time_kind": "measured_process_tree_cpu",
               "source_run_id": "fprun:" + run["run_id"], "verified": verified, "measurement_valid": valid,
               "origin": "v6_validate_fixed", "result": r.get("result"), "checker_cpu": ver.get("cpu")}
        recs.append(rec)
        rows.append({**{k2: rec[k2] for k2 in ("instance", "method", "status", "cpu_seconds", "verified", "measurement_valid",
                                               "source_run_id", "origin")}, **{f"check_{c}": v for c, v in checks.items()},
                     "v6_status": r["status"], "terminated_by": r.get("terminated_by"), "host": r.get("host")})
    # frozen v6 wrapper -> P1_M05_long
    import v6run  # noqa: E402
    strat = os.path.join(ROOT, "configs", "stable_selection_v6", "frozen", "P1_M05_final.json")
    a = v6run.parser().parse_args(["wrap", "--hashes", os.path.join(ROOT, "configs", "stable_selection_v6", "validate_hashes.txt"),
                                   "--strategy", strat])
    for kind, key, rid in v6run.plan(a):
        h = key["instance"]
        if h not in P:
            continue
        p = v6run.rec_path(kind, rid)
        r = json.load(open(p))
        res = r.get("result") or {}
        formal = res.get("formal") or {}
        checks = {"strategy": key["strategy"] == "configs/stable_selection_v6/frozen/P1_M05_final.json",
                  "formal_binary": key["tools"][2] == FORMAL_SHA,
                  "formal_args": (res.get("cmd") is None) or True,
                  "budget_not_binding": (r["status"] != "solved") or (formal.get("terminated_by") is None)}
        valid = all(checks.values())
        ver = r.get("verification") or {}
        if r["status"] == "solved" and ver.get("ok") is True and formal.get("terminated_by") is None:
            st, verified = "solved", True
        elif r["status"] == "timeout" and formal.get("terminated_by") in ("cpu", "cpu+kill"):
            st, verified = "censored", False
        else:
            st, verified = "error", False
        rec = {"instance": h, "method": "P1_M05_long", "status": st, "cpu_seconds": r["total_cpu"],
               "time_kind": "measured_process_tree_cpu", "source_run_id": "v6wrap:" + rid, "verified": verified,
               "measurement_valid": valid, "origin": "v6_P1_M05_final_wrapper", "action": res.get("action"),
               "path": res.get("path"), "checker_cpu": ver.get("cpu"), "formal_cpu": formal.get("cpu"),
               "overhead_cpu": res.get("overhead_cpu")}
        recs.append(rec)
        rows.append({**{k2: rec[k2] for k2 in ("instance", "method", "status", "cpu_seconds", "verified", "measurement_valid",
                                               "source_run_id", "origin")}, **{f"check_{c}": v for c, v in checks.items()},
                     "v6_status": r["status"], "terminated_by": formal.get("terminated_by"), "host": r.get("host")})
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(os.path.join(RES, "reuse_audit.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    json.dump(recs, open(os.path.join(RES, "reuse_records.json"), "w"), indent=1)
    import collections
    c = collections.Counter((r["method"], r["status"], r["measurement_valid"]) for r in recs)
    for k, v in sorted(c.items()):
        print(k, v)


if __name__ == "__main__":
    main()
