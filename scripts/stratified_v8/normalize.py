#!/usr/bin/env python3
"""Normalize v8 run records to one measurement per instance x method for
scripts/completion_v7/evaluate.py (statuses solved / censored / missing / error).

  normalize.py --stage s1_dev --part dev
  normalize.py --stage s3_holdout --part holdout --sbs Fm

Writes results/stratified_v8/normalized_<part>.json and, for dev, dev_times.json
({instance: {D, Fp, Fm: CPU or actual lower bound, bound: {...}}}).
"""

import argparse
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
RES = os.path.join(ROOT, "results", "stratified_v8")


def norm(r, method):
    st = r["status"]
    if st == "solved" and (r.get("verification") or {}).get("ok") is True:
        out = {"status": "solved", "verified": True, "measurement_valid": True, "cpu_seconds": r["cpu"]}
    elif st == "censored":
        out = {"status": "censored", "verified": False, "measurement_valid": True, "cpu_seconds": r["cpu"]}
    elif st == "not_started":
        out = {"status": "missing", "verified": False, "measurement_valid": False, "cpu_seconds": None}
    else:
        out = {"status": "error", "verified": False, "measurement_valid": False, "cpu_seconds": r.get("cpu")}
    out.update(instance=r["instance"], method=method, time_kind="measured_process_tree_cpu",
               source_run_id=f"v8:{r['id']}", stop_reason=r.get("stop_reason"),
               answer={10: "SAT", 20: "UNSAT"}.get(r.get("exit_code")))
    if r["method"] == "W":
        out.update(action=r.get("action"), observation_cpu=r.get("observation_cpu"), formal_cpu=r.get("formal_cpu"),
                   decision_path=(r.get("decision") or {}).get("path"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--part", choices=["dev", "holdout"], required=True)
    ap.add_argument("--sbs")
    a = ap.parse_args()
    panel = [l.split()[0] for l in open(os.path.join(ROOT, "configs", "stratified_v8", f"panel_{a.part}.txt"))
             if l.strip() and not l.startswith("#")]
    recs = {}
    for p in glob.glob(os.path.join(DATA, "runs", "stratified_v8", a.stage, "*.json")):
        if p.endswith("progress.json"):
            continue
        r = json.load(open(p))
        if r.get("rep", 0):
            continue
        k = (r["instance"], r["method"])
        if k in recs:
            raise SystemExit(f"duplicate record {k}")
        recs[k] = r
    out = []
    methods = ["D", "Fp", "Fm"] + (["W"] if a.part == "holdout" and any(m == "W" for _, m in recs) else [])
    for h in panel:
        for m in methods:
            r = recs.get((h, m))
            out.append(norm(r, m) if r else {"instance": h, "method": m, "status": "missing", "cpu_seconds": None,
                                             "verified": False, "measurement_valid": False})
        if a.sbs:
            r = recs.get((h, a.sbs))
            if r:
                x = norm(r, "SBS")
                x["sbs_action"] = a.sbs
                out.append(x)
    json.dump(out, open(os.path.join(RES, f"normalized_{a.part}.json"), "w"), indent=1)
    if a.part == "dev":
        times = {}
        for h in panel:
            t, b = {}, {}
            for m in ("D", "Fp", "Fm"):
                x = next(o for o in out if o["instance"] == h and o["method"] == m)
                if x["status"] not in ("solved", "censored"):
                    raise SystemExit(f"{h} {m}: {x['status']} -- no time or bound")
                t[m], b[m] = x["cpu_seconds"], x["status"] == "censored"
            times[h] = dict(t, bound=b)
        json.dump(times, open(os.path.join(RES, "dev_times.json"), "w"), indent=1, sort_keys=True)
    import collections
    print(collections.Counter((o["method"], o["status"]) for o in out))


if __name__ == "__main__":
    main()
