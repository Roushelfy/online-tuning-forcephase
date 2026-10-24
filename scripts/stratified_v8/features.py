#!/usr/bin/env python3
"""v8 observation: the 11 pre-registered indicators from build/tools/obsprofile6
(docs/STRATIFIED_PROTOCOL_V8.md section 7). Standard library only (also imported by wrapper.py).

  features.py --panel configs/stratified_v8/panel_dev.txt --out results/stratified_v8/features_dev.json

Each instance is observed once in a fresh process tree; the recorded CPU is
obsprofile6's own CPU (wait4). An observation is usable only if obsprofile6
exited normally within the 2 s cap, every section finished, and none of the
11 indicators is missing; otherwise the deployment falls back to D.
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts", "stable_selection_v6"))
import v6lib  # noqa: E402

PROTO = json.load(open(os.path.join(ROOT, "configs", "stratified_v8", "protocol.json")))
FEAT = PROTO["features"]
NAMES = FEAT["scale_only"] + FEAT["structure"]
SECTIONS = ["polar", "resid", "bilat"]
CAP = FEAT["total_cap_cpu_seconds"]


def extract(cnf, workdir, mem_mb=16000):
    obs = v6lib.run_obs6(cnf, SECTIONS, CAP, workdir, mem_mb)
    raw = obs.get("features") or {}
    s28 = v6lib.twlib.static_features(raw) if raw else {}
    feats = {}
    for k in NAMES:
        v = s28.get(k) if k in s28 else raw.get(k)
        feats[k] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    secs = obs.get("sections") or {}
    sec_ok = all((secs.get(s) or {}).get("status") == "ok" for s in ["s28"] + SECTIONS)
    ok = obs["exit_code"] == 0 and obs["terminated_by"] is None and obs["cpu"] <= CAP and sec_ok \
        and all(v is not None for v in feats.values())
    return {"ok": ok, "cpu": obs["cpu"], "exit_code": obs["exit_code"], "terminated_by": obs["terminated_by"],
            "sections": {k: (v or {}).get("status") for k, v in secs.items()}, "features": feats}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    data = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
    ids = [l.split()[0] for l in open(os.path.join(ROOT, a.panel)) if l.strip() and not l.startswith("#")]
    work = os.path.join(os.environ.get("V8_WORK", f"/var/tmp/fp_v8_{os.environ.get('USER', 'user')}"), "features")
    out = {"names": NAMES, "tool": FEAT["tool"], "cap": CAP, "host": os.uname().nodename,
           "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "instances": {}}
    for i in ids:
        out["instances"][i] = extract(os.path.join(data, "stratified_v8", "cnf", i + ".cnf"), os.path.join(work, i))
    out["cpu_total"] = sum(v["cpu"] for v in out["instances"].values())
    json.dump(out, open(os.path.join(ROOT, a.out), "w"), indent=1, sort_keys=True)
    print(json.dumps({"instances": len(ids), "ok": sum(v["ok"] for v in out["instances"].values()),
                      "cpu_total": round(out["cpu_total"], 3)}))


if __name__ == "__main__":
    main()
