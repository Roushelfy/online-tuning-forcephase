#!/usr/bin/env python3
"""Run a command restricted to the logical CPUs of one CPU socket.

  on_socket.py <socket-index> <command...>

Used by slurm_validate.sh so that the fixed-action runner and the wrapper
runner share a node without sharing cores (fprun.physical_cores() picks
cores from the inherited affinity)."""
import glob
import os
import sys

sock = int(sys.argv[1])
cpus = set()
for p in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/topology/physical_package_id"):
    if int(open(p).read()) == sock:
        cpus.add(int(p.split("/")[5][3:]))
cpus &= os.sched_getaffinity(0)
if not cpus:
    sys.exit(f"no CPUs on socket {sock}")
os.sched_setaffinity(0, cpus)
os.execvp(sys.argv[2], sys.argv[2:])
