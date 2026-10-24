#!/usr/bin/env python3
"""v8 run controller (docs/STRATIFIED_PROTOCOL_V8.md section 5).

  runner.py --plan configs/stratified_v8/<stage>.json --stage <stage> --budget-cpu-hours B

Queue in the plan's (pre-registered) order on K = (physical cores - 4) slots,
one physical core per run; the controller and the answer checkers stay on the
other cores. No scoring cutoff. Administrative stops only:
  * per-run cap (`cap_cpu`, pilot 180 s / formal 900 s): SIGTERM when the run's
    own CPU reaches it -> status 'censored', stop_reason 'cap';
  * stage budget: when the summed CPU of this stage's runs (finished + running)
    reaches the budget, running runs get SIGTERM (SIGKILL after 60 s) -> 'censored',
    stop_reason 'budget'; runs not yet started get a 'not_started' record.
Methods: D / Fp / Fm run build/fpc with the action's flags exactly as in v4-v7
(--lrat=1 <action> --fpc=1, seed 0, RLIMIT_AS 16000 MB); `rep` > 0 repeats the
same command (timing-noise check). Method W runs scripts/stratified_v8/wrapper.py
with the frozen strategy given in the plan. Answers are verified at once
(checkmodel / lrat-trim); proofs live under /var/tmp and are deleted afterwards.
Records: $FP_DATA/runs/stratified_v8/<stage>/<id>.json (existing records are
skipped); heartbeat <stage>/progress.json every 60 s.
"""

import argparse
import concurrent.futures as cf
import gzip
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "three_way"))
import fprun  # noqa: E402
import twlib  # noqa: E402

FORMAL = os.path.join(ROOT, "build", "fpc", "cadical")
WRAPPER = os.path.join(HERE, "wrapper.py")
ARGS = {"D": ["--phase=1", "--forcephase=0"], "Fp": ["--phase=1", "--forcephase=1"], "Fm": ["--phase=0", "--forcephase=1"]}
MEM_MB = 16000
TICK = os.sysconf("SC_CLK_TCK")
OUT = os.path.join(fprun.DATA, "runs", "stratified_v8")
CNF_DIR = os.path.join(fprun.DATA, "stratified_v8", "cnf")
WORK = os.environ.get("V8_WORK", f"/var/tmp/fp_v8_{os.environ.get('USER', 'user')}")
_SHA = {}


def sha(p):
    if p not in _SHA:
        _SHA[p] = fprun.sha256_file(p)
    return _SHA[p]


def replace_json(path, obj):
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(obj, f, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def cnf_path(inst):
    return os.path.join(CNF_DIR, inst + ".cnf")


def job_key(j, stage):
    key = {"schema": 1, "stage": stage, "instance": j["instance"], "cnf_sha256": j["sha256"], "method": j["method"],
           "rep": j.get("rep", 0), "formal_sha256": sha(FORMAL), "mem_mb": MEM_MB, "cap_cpu": j.get("cap_cpu"),
           "seed": 0, "proof": "lrat"}
    if j["method"] == "W":
        key.update(strategy=j["strategy"], strategy_sha256=sha(os.path.join(ROOT, j["strategy"])),
                   wrapper_sha256=sha(WRAPPER), features_sha256=sha(os.path.join(HERE, "features.py")),
                   obsprofile6_sha256=sha(os.path.join(ROOT, "build", "tools", "obsprofile6")))
    else:
        key["args"] = ["--lrat=1"] + ARGS[j["method"]] + ["--fpc=1"]
    return key, hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()


def proc_cpu(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            parts = f.read().rsplit(")", 1)[1].split()
        return sum(int(parts[i]) for i in (11, 12, 13, 14)) / TICK
    except (OSError, IndexError, ValueError):
        return None


class Job:
    def __init__(self, spec, stage):
        self.spec = spec
        self.key, self.id = job_key(spec, stage)
        self.wd = os.path.join(WORK, self.id)
        self.cpu = 0.0
        self.proc = None
        self.core = None
        self.stop_reason = None
        self.term_at = None
        self.done = False
        self.started = False
        self.start = None

    def launch(self, core):
        self.core, self.started = core, True
        shutil.rmtree(self.wd, ignore_errors=True)
        os.makedirs(self.wd, exist_ok=True)
        self.cnf = cnf_path(self.spec["instance"])
        if sha(self.cnf) != self.spec["sha256"]:
            raise SystemExit(f"CNF checksum mismatch: {self.spec['instance']}")
        self.so, self.proof = os.path.join(self.wd, "final.out"), os.path.join(self.wd, "final.lrat")
        if self.spec["method"] == "W":
            cmd = [sys.executable, WRAPPER, "--strategy", os.path.join(ROOT, self.spec["strategy"]), "--cnf", self.cnf,
                   "--workdir", self.wd, "--mem-mb", str(MEM_MB)]
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "FP_DATA": fprun.DATA}
            out, err = open(os.path.join(self.wd, "wrapper.out"), "wb"), open(os.path.join(self.wd, "wrapper.err"), "wb")

            def pre():
                os.setsid()
                os.sched_setaffinity(0, {core})
        else:
            cmd = [FORMAL, "--lrat=1"] + ARGS[self.spec["method"]] + ["--fpc=1", self.cnf, self.proof]
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C",
                   "FPC_LOG": os.path.join(self.wd, "final.tel.jsonl")}
            out, err = open(self.so, "wb"), open(os.path.join(self.wd, "final.err"), "wb")

            def pre():
                import resource
                os.setsid()
                os.sched_setaffinity(0, {core})
                resource.setrlimit(resource.RLIMIT_AS, (MEM_MB << 20, MEM_MB << 20))
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        self.cmd = cmd
        self.start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.t0 = time.time()
        self.proc = subprocess.Popen(cmd, stdout=out, stderr=err, env=env, preexec_fn=pre)
        out.close()
        err.close()

    def poll(self):
        pid, status, ru = os.wait4(self.proc.pid, os.WNOHANG)
        if pid:
            self.done = True
            self.exit_code = os.waitstatus_to_exitcode(status)
            self.cpu = ru.ru_utime + ru.ru_stime
            self.cpu_user, self.cpu_sys, self.maxrss = ru.ru_utime, ru.ru_stime, ru.ru_maxrss
            self.wall = time.time() - self.t0
            return True
        c = proc_cpu(self.proc.pid)
        if c is not None:
            self.cpu = c
        return False

    def term(self, reason):
        if self.stop_reason is None:
            self.stop_reason = reason
            self.term_at = time.time()
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def kill_if_late(self):
        if self.term_at and time.time() - self.term_at > 60:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def base_record(job):
    return {"id": job.id, "key": job.key, "instance": job.spec["instance"], "method": job.spec["method"],
            "rep": job.spec.get("rep", 0), "host": socket.gethostname(), "slurm_job": os.environ.get("SLURM_JOB_ID")}


def finalize(job, stage_dir):
    dec = None
    if job.spec["method"] == "W":
        p = os.path.join(job.wd, "decision.json")
        dec = json.load(open(p)) if os.path.exists(p) else None
    so, proof = job.so, job.proof
    status_line, stats, _ = twlib.parse_stats(so) if os.path.exists(so) else (None, {}, {})
    ver = None
    answered = job.exit_code in (10, 20)
    if answered:
        ver = fprun.verify(job.exit_code, job.cnf, so, proof, max(300.0, job.cpu), MEM_MB, job.wd)
        status = {True: "solved", False: "wrong"}.get(ver["ok"] if ver else None, "unverified")
    elif job.stop_reason in ("cap", "budget"):
        status = "censored"
    else:
        status = "error"
    rec = base_record(job)
    rec.update(core=job.core, start_utc=job.start, end_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               cpu=job.cpu, cpu_user=job.cpu_user, cpu_sys=job.cpu_sys, wall=job.wall, maxrss_kb=job.maxrss,
               exit_code=job.exit_code, stop_reason=job.stop_reason, status=status, verification=ver,
               status_line=status_line, stats=stats, decision=dec, cmd=job.cmd,
               proof_bytes=os.path.getsize(proof) if os.path.exists(proof) else None)
    if dec is not None:
        rec["formal_cpu"] = job.cpu - dec["cpu_at_exec"]
        rec["action"] = dec["action"]
        rec["observation_cpu"] = dec["cpu_at_exec"]
    raw = os.path.join(stage_dir, "raw", job.id)
    os.makedirs(raw, exist_ok=True)
    for f in ("final.out", "final.err", "final.tel.jsonl", "wrapper.err", "decision.json"):
        p = os.path.join(job.wd, f)
        if not os.path.exists(p):
            continue
        with open(p, "rb") as fi, gzip.open(os.path.join(raw, f + ".gz"), "wb") as fo:
            for line in fi:
                if not (f == "final.out" and line.startswith(b"v ")):
                    fo.write(line)
    fprun.atomic_write_json(os.path.join(stage_dir, job.id + ".json"), rec)
    shutil.rmtree(job.wd, ignore_errors=True)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--budget-cpu-hours", type=float, required=True)
    ap.add_argument("--quiet-outcomes", action="store_true",
                    help="log only job counts (no per-run CPU/answers); used for sealed runs")
    a = ap.parse_args()
    plan = json.load(open(a.plan))
    stage_dir = os.path.join(OUT, a.stage)
    os.makedirs(stage_dir, exist_ok=True)
    jobs = [Job(s, a.stage) for s in plan["jobs"]]
    if len({j.id for j in jobs}) != len(jobs):
        raise SystemExit("duplicate jobs in plan")
    have = {j.id for j in jobs if os.path.exists(os.path.join(stage_dir, j.id + ".json"))}
    prior = sum(json.load(open(os.path.join(stage_dir, i + ".json")))["cpu"] for i in have)
    queue = [j for j in jobs if j.id not in have]
    cores = fprun.physical_cores()
    slots = cores[:max(1, len(cores) - 4)]
    ctrl = [c for c in cores if c not in slots] or cores[:1]
    os.sched_setaffinity(0, set(ctrl))
    budget = a.budget_cpu_hours * 3600.0
    print(f"[runner] {a.stage}: {len(jobs)} jobs, {len(queue)} pending, {len(slots)} slots, budget "
          f"{a.budget_cpu_hours} CPU-h (already spent {prior / 3600:.3f})", flush=True)
    pool = cf.ThreadPoolExecutor(max_workers=8)
    futs, running, free = [], [], list(slots)
    last_hb, stopping = 0, False
    finished = 0
    while True:
        for j in list(running):
            if j.poll():
                running.remove(j)
                free.append(j.core)
                finished += 1
                futs.append(pool.submit(finalize, j, stage_dir))
                if not a.quiet_outcomes:
                    print(f"[runner] exit {j.spec['instance']} {j.spec['method']}{j.spec.get('rep', 0) or ''} "
                          f"code={j.exit_code} cpu={j.cpu:.2f} stop={j.stop_reason}", flush=True)
                continue
            if j.spec.get("cap_cpu") and j.cpu >= j.spec["cap_cpu"]:
                j.term("cap")
            j.kill_if_late()
        spent = prior + sum(j.cpu for j in jobs if j.started)
        if not stopping and spent >= budget:
            stopping = True
            print(f"[runner] budget reached ({spent / 3600:.3f} CPU-h): stopping {len(running)} runs, "
                  f"{len(queue)} not started", flush=True)
            for j in running:
                j.term("budget")
        while not stopping and queue and free:
            j = queue.pop(0)
            j.launch(free.pop(0))
            running.append(j)
        if time.time() - last_hb > 60 or not (running or (queue and not stopping)):
            last_hb = time.time()
            replace_json(os.path.join(stage_dir, "progress.json"),
                         {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "host": socket.gethostname(),
                          "slurm_job": os.environ.get("SLURM_JOB_ID"), "spent_cpu_hours": spent / 3600,
                          "budget_cpu_hours": a.budget_cpu_hours, "finished": finished, "running": len(running),
                          "pending": len(queue),
                          "jobs": [{"id": j.id, "cpu": j.cpu, "state": "running"} for j in running]})
        if not running and (not queue or stopping):
            break
        time.sleep(1)
    for j in queue:  # budget stop: never started
        rec = base_record(j)
        rec.update(status="not_started", cpu=0.0, stop_reason="budget")
        fprun.atomic_write_json(os.path.join(stage_dir, j.id + ".json"), rec)
    recs = [f.result() for f in futs]
    import collections
    print("[runner] done", dict(collections.Counter(r["status"] for r in recs)), f"not_started={len(queue)}",
          f"cpu_h={sum(r['cpu'] for r in recs) / 3600:.3f}",
          f"checker_cpu_h={sum(((r.get('verification') or {}).get('cpu') or 0) for r in recs) / 3600:.4f}", flush=True)


if __name__ == "__main__":
    main()
