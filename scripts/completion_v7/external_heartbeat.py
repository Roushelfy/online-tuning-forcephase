#!/usr/bin/env python3
"""External CPU sampler for a running longrun.py stage (used for stage 1, whose
in-process heartbeat was written only once; docs/COMPLETION_RUN_PLAN_V7.md
deviation 3). Run on the job's node (srun --jobid J --overlap): reads /proc for
every process whose command line contains a panel CNF path and writes
<stage dir>/heartbeat_external/<utc>.json with each process's actual CPU
(utime + stime + cutime + cstime). Never overwrites.

  external_heartbeat.py <stage_dir>
"""
import json
import os
import sys
import time

TICK = os.sysconf("SC_CLK_TCK")
stage_dir = sys.argv[1]
out = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "host": os.uname().nodename, "procs": []}
for pid in os.listdir("/proc"):
    if not pid.isdigit():
        continue
    try:
        cmd = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
        cmd = [c.decode("utf-8", "replace") for c in cmd if c]
        if not any("/fp_local_" in c and c.endswith(".cnf") for c in cmd):
            continue
        parts = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
        cpu = sum(int(parts[i]) for i in (11, 12, 13, 14)) / TICK
        cnf = [c for c in cmd if c.endswith(".cnf")][0]
        out["procs"].append({"pid": int(pid), "exe": os.path.basename(cmd[0]), "instance": os.path.basename(cnf)[:-4],
                             "cpu": cpu, "is_solver": cmd[0].endswith("cadical")})
    except (OSError, IndexError, ValueError):
        continue
d = os.path.join(stage_dir, "heartbeat_external")
os.makedirs(d, exist_ok=True)
json.dump(out, open(os.path.join(d, out["utc"] + ".json"), "w"))
print(out["utc"], len(out["procs"]), round(sum(p["cpu"] for p in out["procs"] if p["is_solver"]) / 3600, 2))
