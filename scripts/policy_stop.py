#!/usr/bin/env python3
"""Apply the per-run CPU timeout (configs/run_timeout_policy.json) to solver processes that are ALREADY running
under an older controller (one that cannot enforce it). Run on the job's node:

  srun --jobid J --overlap -n1 python3 scripts/policy_stop.py [--dry-run]

Every `cadical` process of this user whose process-tree CPU (utime + stime + cutime + cstime; the probe of a
wrapper is a waited child, so it is included) has reached the policy limit gets SIGTERM, exactly as a
controller stop would. Answer checkers (lrat-trim / checkmodel) are never touched. Each stop is logged to
$FP_DATA/logs/policy_stops/<utc>-<host>.json (pid, command, CPU, time). The controller then writes its usual
record (exit -15, logs saved); results/policy_stops.json maps those record ids to status 'policy_timeout'.
"""
import argparse
import json
import os
import signal
import socket
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POL = json.load(open(os.path.join(ROOT, "configs", "run_timeout_policy.json")))
LIMIT = POL["per_instance_method_cpu_seconds"]
TICK = os.sysconf("SC_CLK_TCK")
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")


def procs():
    uid = os.getuid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            if os.stat(f"/proc/{pid}").st_uid != uid:
                continue
            cmd = [c.decode() for c in open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0") if c]
            if not cmd or os.path.basename(cmd[0]) != "cadical":
                continue
            parts = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
            cpu = sum(int(parts[i]) for i in (11, 12, 13, 14)) / TICK
            yield int(pid), cmd, cpu
        except (OSError, ValueError, IndexError):
            continue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out = {"utc": utc, "host": socket.gethostname(), "policy_id": POL["policy_id"], "limit_cpu_seconds": LIMIT,
           "dry_run": a.dry_run, "stopped": [], "kept": []}
    for pid, cmd, cpu in procs():
        row = {"pid": pid, "cpu": cpu, "cnf": next((c for c in cmd if c.endswith(".cnf")), None),
               "args": [c for c in cmd[1:] if c.startswith("--")]}
        if cpu >= LIMIT:
            if not a.dry_run:
                os.kill(pid, signal.SIGTERM)
            out["stopped"].append(row)
        else:
            out["kept"].append(row)
    d = os.path.join(DATA, "logs", "policy_stops")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{utc}-{out['host']}{'-dry' if a.dry_run else ''}.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({"host": out["host"], "stopped": len(out["stopped"]), "kept": len(out["kept"]),
                      "dry_run": a.dry_run, "min_cpu_stopped": min([r["cpu"] for r in out["stopped"]] or [0])}))


if __name__ == "__main__":
    main()
