"""Cluster feature extraction with measured CPU (one JSON line per instance).

For each instance of the mirror:
  1. native_linear42 on the GBD .xz file (Mu's acquisition path: 8 s CPU attempt, 16 s retry only after SIGXCPU),
     child CPU from wait4, raw GBD base statistics;
  2. cnf_unit_unique on the decompressed plain CNF (decompression CPU recorded separately), child CPU from wait4.
Each worker is pinned to one CPU token (first N CPUs of the allocation, one hardware thread per physical core).

  python3 tools/anni2022_extract_features.py --tools TOOLS_DIR --cnf-dir CNF_XZ --out OUT.jsonl --shard I/N [--workers 8]
"""
import argparse
import json
import lzma
import os
import queue
import shutil
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def timed(cmd, cpu):
    """Run cmd pinned to cpu; returns (stdout, stderr, exit, child CPU s, wall s)."""
    t0 = time.monotonic()
    p = subprocess.Popen(["taskset", "-c", str(cpu), *cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = p.stdout.read(); err = p.stderr.read()
    _, status, ru = os.wait4(p.pid, 0)
    return out.decode(), err.decode(), os.waitstatus_to_exitcode(status), ru.ru_utime + ru.ru_stime, time.monotonic() - t0


def one(k, a, cpu, local):
    rec = {"instance_key": k, "host": socket.gethostname(), "cpu_token": cpu}
    xz = Path(a.cnf_dir) / f"{k}.cnf.xz"
    attempts = []
    for name in ("native_linear42", "native_linear42_cpu16"):
        out, err, code, c, w = timed([str(Path(a.tools) / name), str(xz)], cpu)
        attempts.append({"binary": name, "exit": code, "cpu_s": c, "wall_s": w, "stderr": err.strip()[:200]})
        if code == 0:
            rec["raw42"] = json.loads(out)["features"]; break
        # Retry only after the 8 s CPU limit ended the attempt, as in Mu's policy. With soft = hard = 8 s, macOS
        # delivers SIGXCPU (-24) but Linux delivers SIGKILL (-9) at the hard limit, so both count when CPU >= 7.9 s.
        if not (code in (-24, -9) and c >= 7.9): break
    rec["native_attempts"] = attempts
    rec["native_ok"] = "raw42" in rec
    rec["native_cpu_s"] = sum(x["cpu_s"] for x in attempts)
    plain = local / f"{k}.cnf"
    t0 = time.thread_time()
    with lzma.open(xz) as src, plain.open("wb") as dst: shutil.copyfileobj(src, dst, 1 << 20)
    rec["decompress_thread_cpu_s"] = time.thread_time() - t0
    out, err, code, c, w = timed(["prlimit", "--cpu=300", "--as=34359738368", "--", str(Path(a.tools) / "cnf_unit_unique"), str(plain)], cpu)
    plain.unlink(missing_ok=True)
    rec["uu_exit"], rec["uu_cpu_s"], rec["uu_wall_s"] = code, c, w
    if code == 0: rec["unit_unique"] = json.loads(out)
    else: rec["uu_stderr"] = err.strip()[:200]
    return rec


def main():
    p = argparse.ArgumentParser()
    for x in ("--tools", "--cnf-dir", "--out", "--shard"): p.add_argument(x, required=True)
    p.add_argument("--workers", type=int, default=8); p.add_argument("--local", default="/var/tmp/anni-features")
    a = p.parse_args(); i, n = map(int, a.shard.split("/"))
    keys = sorted(f[:32] for f in os.listdir(a.cnf_dir) if f.endswith(".cnf.xz"))[i::n]
    out = Path(a.out); done = set()
    if out.exists(): done = {json.loads(l)["instance_key"] for l in out.open()}
    todo = [k for k in keys if k not in done]
    local = Path(a.local) / f"shard-{i:03d}"; local.mkdir(parents=True, exist_ok=True)
    cpus = sorted(os.sched_getaffinity(0))[:a.workers]; tokens = queue.Queue(); [tokens.put(c) for c in cpus]
    lock = threading.Lock(); print(f"shard {i}/{n} {socket.gethostname()} cpus {cpus} todo {len(todo)}", flush=True)

    def job(k):
        cpu = tokens.get()
        try:
            rec = one(k, a, cpu, local)
        except Exception as e:
            rec = {"instance_key": k, "error": repr(e)}
        finally:
            tokens.put(cpu)
        with lock, out.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    with ThreadPoolExecutor(len(cpus)) as ex: list(ex.map(job, todo))
    print("done", flush=True)


if __name__ == "__main__":
    main()
