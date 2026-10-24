#!/usr/bin/env python3
"""Consistency check before S3 (no solving): run wrapper.py --decide-only on every development
instance in a fresh process and compare its observed features and action with the offline
features (features_dev.json) and the frozen strategy's offline prediction; record the wrapper's
process-tree CPU up to the exec point (observation + Python overhead).

  check_wrapper.py --strategy configs/stratified_v8/frozen/strategy.json
"""
import argparse
import json
import os
import resource
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import models  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--strategy", required=True)
a = ap.parse_args()
data = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
strat = json.load(open(os.path.join(ROOT, a.strategy)))
fe = json.load(open(os.path.join(ROOT, "results", "stratified_v8", "features_dev.json")))["instances"]
work = f"/var/tmp/fp_v8_{os.environ.get('USER', 'user')}/check"
rows = []
for i in sorted(fe):
    wd = os.path.join(work, i)
    c0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    r = subprocess.run([sys.executable, os.path.join(HERE, "wrapper.py"), "--strategy", os.path.join(ROOT, a.strategy),
                        "--cnf", os.path.join(data, "stratified_v8", "cnf", i + ".cnf"), "--workdir", wd, "--decide-only"],
                       capture_output=True, text=True, check=True)
    c1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    dec = json.load(open(os.path.join(wd, "decision.json")))
    off = models.predict(strat, fe[i]["features"])
    rows.append({"instance": i, "live": dec["action"], "offline": off, "match": dec["action"] == off,
                 "features_equal": dec["features"] == fe[i]["features"],
                 "wrapper_cpu": (c1.ru_utime + c1.ru_stime) - (c0.ru_utime + c0.ru_stime),
                 "obs_cpu": dec["observation"]["cpu"]})
out = {"strategy": a.strategy, "n": len(rows), "actions_match": sum(r["match"] for r in rows),
       "features_equal": sum(r["features_equal"] for r in rows),
       "wrapper_cpu_total": sum(r["wrapper_cpu"] for r in rows), "rows": rows}
json.dump(out, open(os.path.join(ROOT, "results", "stratified_v8", "wrapper_check_dev.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "rows"}))
