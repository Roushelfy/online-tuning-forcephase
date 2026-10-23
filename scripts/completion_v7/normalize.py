#!/usr/bin/env python3
"""Normalize all v7 measurements to one record per instance x method by the
pre-registered adoption order (docs/COMPLETION_RUN_PLAN_V7.md section 3), for
scripts/completion_v7/evaluate.py.

  python3 scripts/completion_v7/normalize.py [--stages stage1,stage2]

Order (first available *valid* measurement; never the fastest):
  D / Fp / Fm : v6 verified solve > v7 standalone long run > (D only) the formal
                D solve inside the v7 P1_M05_long run > v6 300-s censored bound
  P1_M05_long : v6 verified solve > v7 long wrapper > v6 censored bound
v7 attempts that ended in error / wrong / unverified are kept in the attempt
log and never displace a valid measurement or bound.
Writes $FP_DATA/runs/completion_v7/normalized.json and
results/completion_v7/{normalized.json, attempts.csv}.
"""

import argparse
import csv
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import fprun  # noqa: E402

RES = os.path.join(ROOT, "results", "completion_v7")
OUT = os.path.join(fprun.DATA, "runs", "completion_v7")
VALID = {"solved", "censored", "noncompetitive_bound"}


def panel():
    return [l.split()[0] for l in open(os.path.join(ROOT, "configs", "completion_v7", "panel.txt"))
            if l.strip() and not l.startswith("#")]


def v7_records(stages):
    out = []
    for st in stages:
        for p in sorted(glob.glob(os.path.join(OUT, st, "*.json"))):
            if p.endswith("progress.json"):
                continue
            r = json.load(open(p))
            r["_stage"] = st
            out.append(r)
    return out


def norm_v7(r, method, cpu, derived=None):
    ok = r["status"] in VALID
    return {"instance": r["instance"], "method": method,
            "status": r["status"] if ok else "error", "cpu_seconds": cpu,
            "time_kind": "measured_process_tree_cpu",
            "source_run_id": f"v7:{r['_stage']}:{r['id']}" + (f":{derived}" if derived else ""),
            "verified": r["status"] == "solved", "measurement_valid": ok and cpu is not None and cpu >= 0,
            "origin": f"v7_{r['_stage']}" + (f"_{derived}" if derived else ""),
            "host": r.get("host"), "stop_reason": r.get("stop_reason")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", default="stage1,stage2")
    a = ap.parse_args()
    P = panel()
    reuse = json.load(open(os.path.join(RES, "reuse_records.json")))
    v6 = {(r["instance"], r["method"]): r for r in reuse}
    v7 = v7_records([s for s in a.stages.split(",") if os.path.isdir(os.path.join(OUT, s))])
    attempts = []
    fixed7, wrap7 = {}, {}
    for r in v7:
        attempts.append({"instance": r["instance"], "method": r["method"], "kind": r["kind"], "stage": r["_stage"],
                         "status": r["status"], "cpu": r["cpu"], "formal_cpu": r.get("formal_cpu"), "action": r.get("action"),
                         "stop_reason": r.get("stop_reason"), "exit_code": r["exit_code"], "host": r["host"], "id": r["id"]})
        if r["status"] not in VALID:
            continue
        if r["kind"] == "fixed":
            prev = fixed7.get((r["instance"], r["method"]))
            # several valid stages for one arm (stage-2 arms restart from scratch): the longest actual run
            # is the one whose bound / completion is the measurement of record; it is fixed by stage order
            if prev is None or r["_stage"] > prev["_stage"]:
                fixed7[(r["instance"], r["method"])] = r
        else:
            wrap7[r["instance"]] = r
    out = []
    for h in P:
        for m in ("D", "Fp", "Fm"):
            old = v6.get((h, m))
            if old and old["status"] == "solved" and old["verified"] and old["measurement_valid"]:
                out.append(old)
            elif (h, m) in fixed7:
                r = fixed7[(h, m)]
                out.append(norm_v7(r, m, r["cpu"]))
            elif m == "D" and h in wrap7 and wrap7[h].get("action") == "D" and wrap7[h].get("formal_cpu") is not None:
                r = wrap7[h]
                out.append(norm_v7(r, "D", r["formal_cpu"], derived="formal_subprocess"))
            elif old:
                out.append(old)
            else:
                out.append({"instance": h, "method": m, "status": "missing", "cpu_seconds": None, "verified": False,
                            "measurement_valid": False})
        old = v6.get((h, "P1_M05_long"))
        if old and old["status"] == "solved" and old["verified"] and old["measurement_valid"]:
            out.append(old)
        elif h in wrap7:
            out.append(norm_v7(wrap7[h], "P1_M05_long", wrap7[h]["cpu"]))
        elif old:
            out.append(old)
        else:
            out.append({"instance": h, "method": "P1_M05_long", "status": "missing", "cpu_seconds": None,
                        "verified": False, "measurement_valid": False})
    for dst in (os.path.join(OUT, "normalized.json"), os.path.join(RES, "normalized.json")):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        json.dump(out, open(dst, "w"), indent=1)
    with open(os.path.join(RES, "attempts.csv"), "w", newline="") as f:
        fields = ["instance", "method", "kind", "stage", "status", "cpu", "formal_cpu", "action", "stop_reason", "exit_code",
                  "host", "id"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(attempts)
    import collections
    print(collections.Counter((r["method"], r["status"]) for r in out))


if __name__ == "__main__":
    main()
