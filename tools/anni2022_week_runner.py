"""Runner for the week-2026-11-16 experiments (probes, F-largest, identity checks).

Measurement is the baseline's: each solver run goes through run_one.limited_process (CPU read from /proc, SIGTERM
at the cutoff, prlimit backstop, taskset to one CPU token, wait4 rusage), answers are verified like the baseline
(SAT: check_model against the CNF; UNSAT: lrat-trim --no-trim on the binary LRAT proof), and 'solved' means verified
and CPU <= cutoff. Inputs come from the local GBD .xz mirror and are checked against the baseline input SHA.

  python3 tools/anni2022_week_runner.py --tasks TASKS.jsonl --out RUN_ROOT --cnf-dir CNF_XZ --receipts RUN_ROOT_V3 \
      --shard I/N [--workers 8]
TASKS.jsonl rows: {"task": id, "instance_key": k, "config": name, "binary": path, "binary_sha256": sha,
                   "args": [...], "cutoff_s": T, "checker": path, "checker_sha256": sha}
Results: RUN_ROOT/results/<task>.json (+ <task>.log.gz). Re-running skips finished tasks; an interrupted attempt
directory is moved to RUN_ROOT/aborted/<task>.<stamp> and the task runs again (recorded in the result).
"""
import argparse
import glob
import gzip
import json
import lzma
import os
import queue
import re
import shutil
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.anniversary2022_baseline.common import check_model, parse_stats, sha  # noqa: E402
from src.anniversary2022_baseline.run_one import limited_process  # noqa: E402

MEMORY = 32 * 1024 ** 3; FSIZE = 32 * 1024 ** 3; CHECK_CPU = 1800; CHECK_WALL = 2400
ANNI = re.compile(r"^c anni (tick|final) (.*)$", re.M)
FLARGEST = re.compile(r"^c anni flargest (.*)$", re.M)


def kv(text):
    out = {}
    for item in text.split():
        k, v = item.split("=", 1)
        out[k] = float(v) if any(c in v for c in ".e") else int(v)
    return out


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Inputs:
    """Node-local plain CNFs, decompressed once per shard and removed after the instance's last task."""
    def __init__(self, cnf_dir, receipts, local):
        self.cnf_dir, self.receipts, self.local = Path(cnf_dir), receipts, Path(local)
        self.local.mkdir(parents=True, exist_ok=True); self.lock = threading.Lock(); self.events = {}; self.left = {}

    def get(self, k):
        with self.lock:
            ev = self.events.get(k)
            if ev is None:
                ev = self.events[k] = threading.Event(); mine = True
            else:
                mine = False
        dst = self.local / f"{k}.cnf"
        if mine:
            try:
                tmp = dst.with_suffix(".part")
                with lzma.open(self.cnf_dir / f"{k}.cnf.xz") as src, tmp.open("wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                if sha(tmp) != self.receipts[k]:
                    raise ValueError("decompressed CNF differs from the baseline input SHA")
                tmp.replace(dst)
            finally:
                ev.set()
        ev.wait()
        if not dst.exists(): raise RuntimeError("input preparation failed for " + k)
        return dst

    def done(self, k):
        with self.lock:
            self.left[k] -= 1
            if self.left[k] == 0:
                (self.local / f"{k}.cnf").unlink(missing_ok=True); self.events.pop(k, None)


def run_task(t, cnf, root, cpu, proofs):
    res_path = root / "results" / f"{t['task']}.json"
    if res_path.exists(): return json.loads(res_path.read_text())
    work = root / "attempts" / t["task"]; recovered = None
    if work.exists():
        recovered = str(root / "aborted" / f"{t['task']}.{time.strftime('%Y%m%dT%H%M%S')}")
        (root / "aborted").mkdir(exist_ok=True); work.rename(recovered)
    work.mkdir(parents=True)
    assert sha(t["binary"]) == t["binary_sha256"], "solver binary changed"
    proof = proofs / f"{t['task']}.lrat"; proof.unlink(missing_ok=True)
    T = t["cutoff_s"]; log = work / "solver.log"
    cmd = [t["binary"], *t["args"], "--seed=0", "--stats", "--lrat", "--binary=true", "-t", "1800", str(cnf), str(proof)]
    started = utc()
    m = limited_process(cmd, log, T, max(1800, 3 * T), MEMORY, FSIZE, cpu, work / "active.json", 5)
    text = log.read_text(errors="replace")
    stats = parse_stats(text[-200000:])
    answer = {10: "SAT", 20: "UNSAT"}.get(m["exit_code"])
    status = ("CPU_TIMEOUT" if m["stop_reason"] == "CPU_LIMIT" else "WALL_WATCHDOG" if m["stop_reason"] == "WALL_WATCHDOG"
              else answer or ("UNKNOWN" if m["exit_code"] == 0 else "ERROR"))
    if answer and m["cpu_s"] > T: status = "CPU_TIMEOUT"
    verification, checker = "NOT_ANSWERED", None
    if status == "SAT":
        verification = "VERIFIED_MODEL" if check_model(cnf, log) else "INVALID_MODEL"
    elif status == "UNSAT":
        assert sha(t["checker"]) == t["checker_sha256"], "checker binary changed"
        clog = work / "checker.log"
        checker = limited_process([t["checker"], "--no-trim", str(cnf), str(proof)], clog, CHECK_CPU, CHECK_WALL,
                                  MEMORY, FSIZE, cpu, work / "checker_active.json", 5)
        ok = checker["exit_code"] == 20 and any(l.strip() == "s VERIFIED" for l in clog.read_text(errors="replace").splitlines())
        verification = "VERIFIED_LRAT" if ok else "PENDING_VERIFICATION"
    solved = status in ("SAT", "UNSAT") and verification.startswith("VERIFIED") and m["cpu_s"] <= T
    proof_bytes = proof.stat().st_size if proof.exists() else 0
    proof.unlink(missing_ok=True)
    telemetry = [{"tag": tag, **kv(body)} for tag, body in ANNI.findall(text)]
    fl = FLARGEST.search(text)
    with log.open("rb") as src, gzip.open(root / "results" / f"{t['task']}.log.gz", "wb") as out:
        shutil.copyfileobj(src, out)
    result = {**{k: t[k] for k in ("task", "instance_key", "config", "args", "cutoff_s", "binary_sha256")},
              "status": status, "answer": answer, "verification": verification, "solved": solved,
              "exit_code": m["exit_code"], "stop_reason": m["stop_reason"], "hard_kill": m["hard_kill"],
              "cpu_s": m["cpu_s"], "cpu_user_s": m["cpu_user_s"], "cpu_system_s": m["cpu_system_s"], "wall_s": m["wall_s"],
              "maxrss_kib": m["maxrss_kib"], "checker_cpu_s": checker["cpu_s"] if checker else 0.0, **stats,
              "flargest": kv(fl.group(1)) if fl else None, "telemetry": telemetry, "proof_bytes": proof_bytes,
              "host": socket.gethostname(), "cpu_token": cpu, "started_utc": started, "finished_utc": utc(),
              "recovered_from": recovered, "command": cmd}
    tmp = res_path.with_suffix(".tmp"); tmp.write_text(json.dumps(result)); tmp.replace(res_path)
    shutil.rmtree(work)
    return result


def main():
    p = argparse.ArgumentParser()
    for a in ("--tasks", "--out", "--cnf-dir", "--receipts", "--shard"): p.add_argument(a, required=True)
    p.add_argument("--workers", type=int, default=8); p.add_argument("--local", default="/var/tmp/anni-week")
    a = p.parse_args()
    idx, cnt = map(int, a.shard.split("/"))
    tasks = [json.loads(l) for l in open(a.tasks)]
    keys = sorted({t["instance_key"] for t in tasks})
    mine_keys = set(keys[idx::cnt])                      # whole instances per shard, so each CNF is staged once
    mine = [t for t in tasks if t["instance_key"] in mine_keys]
    root = Path(a.out); (root / "results").mkdir(parents=True, exist_ok=True)
    receipts = {}
    for f in glob.glob(os.path.join(a.receipts, "shard-*/input_receipts/*.json")):
        r = json.load(open(f)); receipts[r["instance_key"]] = r["input_sha256"]
    local = Path(a.local) / f"shard-{idx:03d}-of-{cnt:03d}"
    inputs = Inputs(a.cnf_dir, receipts, local / "cnf"); proofs = local / "proofs"; proofs.mkdir(parents=True, exist_ok=True)
    todo = [t for t in mine if not (root / "results" / f"{t['task']}.json").exists()]
    todo.sort(key=lambda t: (t["instance_key"], t["config"]))  # consecutive tasks share one staged CNF
    for t in todo: inputs.left[t["instance_key"]] = inputs.left.get(t["instance_key"], 0) + 1
    cpus = sorted(os.sched_getaffinity(0))[:a.workers]; tokens = queue.Queue()
    for c in cpus: tokens.put(c)
    print(f"shard {idx}/{cnt} host {socket.gethostname()} cpus {cpus} tasks {len(mine)} todo {len(todo)}", flush=True)
    counts = {}; lock = threading.Lock()

    def job(t):
        cpu = tokens.get(); prev = os.sched_getaffinity(0)
        try:
            os.sched_setaffinity(0, {cpu})
            cnf = inputs.get(t["instance_key"])
            r = run_task(t, cnf, root, cpu, proofs); key = r["status"]
        except Exception as e:
            key = "EXCEPTION"; (root / "errors").mkdir(exist_ok=True)
            (root / "errors" / f"{t['task']}.txt").write_text(f"{utc()} {e!r}\n")
        finally:
            os.sched_setaffinity(0, prev); tokens.put(cpu); inputs.done(t["instance_key"])
        with lock:
            counts[key] = counts.get(key, 0) + 1
            if sum(counts.values()) % 100 == 0: print(utc(), counts, flush=True)

    with ThreadPoolExecutor(len(cpus)) as ex:
        list(ex.map(job, todo))
    print("done", counts, flush=True)
    raise SystemExit(0 if "EXCEPTION" not in counts else 2)


if __name__ == "__main__":
    main()
