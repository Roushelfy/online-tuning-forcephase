#!/usr/bin/env python3
"""List v10 records whose stored status predates the SIGXCPU classifier fix (protocol section 12): status 'error'
with exit -24 under the per-run policy cap. Record files are not modified; the analysis applies
scripts/run_timeout_policy.is_timeout(cpu, key, exit_code) itself. Writes results/cross_scale_v10/status_corrections.json.
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import run_timeout_policy  # noqa: E402

DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
RUNS = os.path.join(DATA, "runs", "cross_scale_v10")


def main():
    out = []
    for p in sorted(glob.glob(os.path.join(RUNS, "*", "*.json"))):
        if p.endswith(("progress.json", "effective_plan.json")):
            continue
        r = json.load(open(p))
        if r["status"] == "error" and run_timeout_policy.is_timeout(r["cpu"], r["key"], r.get("exit_code")):
            out.append({"stage": os.path.basename(os.path.dirname(p)), "id": r["id"], "instance": r["instance"],
                        "method": r["method"] + (f" ({r['strategy']})" if r.get("strategy") else ""),
                        "stored_status": "error", "status": "policy_timeout", "exit_code": r["exit_code"], "cpu": r["cpu"],
                        "wall": r["wall"]})
    doc = {"note": "Records stopped by the kernel CPU limit (SIGXCPU, exit -24) at the per-run cap whose reported rusage "
                   "was slightly below cap - 0.5 s (kernel runtime runs up to ~1.5 s ahead of rusage on large formulas; "
                   "wrappers round the remaining budget up to whole seconds), so the controller stored 'error'. They are "
                   "policy timeouts; record files are unchanged and the analysis applies the corrected rule.",
           "corrections": out}
    json.dump(doc, open(os.path.join(ROOT, "results", "cross_scale_v10", "status_corrections.json"), "w"), indent=1)
    print(len(out), [(c["stage"], c["instance"], c["method"], round(c["cpu"], 2)) for c in out])


if __name__ == "__main__":
    main()
