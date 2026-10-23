#!/usr/bin/env python3
"""v7 long-run controller (docs/COMPLETION_RUN_PLAN_V7.md sections 2-4).

  longrun.py --plan configs/completion_v7/stage1.json --stage stage1 --budget-cpu-hours 40

Starts every pending job of the plan at the same time, one physical core each
(fair: unfinished jobs always have received the same CPU), with NO scoring
cutoff. Administrative stops only:
  * budget: when the summed CPU of all jobs of this stage (finished + running)
    reaches the stage budget, every running job gets SIGTERM (CaDiCaL stops
    cleanly), SIGKILL after 60 s -> status 'censored' with its actual CPU;
  * cap (optional per job, stage 2 oracle arms): SIGTERM once the job's own CPU
    reaches cap -> status 'noncompetitive_bound'.
Jobs: kind 'fixed' runs build/fpc with the action's flags (the fixed-run
command); kind 'wrapper' runs scripts/completion_v7/wrapper_long.py
(P1_M05_long). Answers are verified at once (checkmodel / lrat-trim with
max(1800 s, 4 x CPU)); proofs live on node-local disk (/var/tmp) and are
deleted after checking. Every 60 s a heartbeat with each job's actual CPU is
written to $FP_DATA/runs/completion_v7/<stage>/progress.json.
Records: $FP_DATA/runs/completion_v7/<stage>/<id>.json (finished jobs are skipped).
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
WRAPPER = os.path.join(HERE, "wrapper_long.py")
STRATEGY = os.path.join(ROOT, "configs", "stable_selection_v6", "frozen", "P1_M05_final.json")
ARGS = {"D": ["--phase=1", "--forcephase=0"], "Fp": ["--phase=1", "--forcephase=1"], "Fm": ["--phase=0", "--forcephase=1"]}
MEM_MB = 16000
TICK = os.sysconf("SC_CLK_TCK")
OUT = os.path.join(fprun.DATA, "runs", "completion_v7")
WORK = os.environ.get("V7_WORK", f"/var/tmp/fp_v7_{os.environ.get('USER', 'user')}")


def sha(p):
    return fprun.sha256_file(p)


def job_key(j, stage):
    key = {"schema": 1, "stage": stage, "instance": j["instance"], "method": j["method"], "kind": j["kind"],
           "formal_sha256": sha(FORMAL), "mem_mb": MEM_MB, "cap_cpu": j.get("cap_cpu"), "seed": 0, "proof": "lrat"}
    if j["kind"] == "wrapper":
        key.update(strategy_sha256=sha(STRATEGY), wrapper_sha256=sha(WRAPPER),
                   v6lib_sha256=sha(os.path.join(ROOT, "scripts", "stable_selection_v6", "v6lib.py")),
                   obsprofile6_sha256=sha(os.path.join(ROOT, "build", "tools", "obsprofile6")))
    else:
        key["args"] = ["--lrat=1"] + ARGS[j["method"]] + ["--fpc=1"]
    return key, hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()


def proc_cpu(pid):
    """utime + stime + cutime + cstime of a live process (s)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            parts = f.read().rsplit(")", 1)[1].split()
        return sum(int(parts[i]) for i in (11, 12, 13, 14)) / TICK
    except (OSError, IndexError, ValueError):
        return None


class Job:
    def __init__(self, spec, stage, core):
        self.spec, self.core = spec, core
        self.key, self.id = job_key(spec, stage)
        self.wd = os.path.join(WORK, self.id)
        self.cpu = 0.0
        self.proc = None
        self.stop_reason = None
        self.term_at = None
        self.done = False
        self.start = None

    def launch(self):
        shutil.rmtree(self.wd, ignore_errors=True)
        os.makedirs(self.wd, exist_ok=True)
        self.cnf = fprun.stage_cnf(self.spec["instance"], "orig", 0)
        core = self.core
        if self.spec["kind"] == "fixed":
            self.so, self.proof = os.path.join(self.wd, "final.out"), os.path.join(self.wd, "final.lrat")
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
        else:
            cmd = [sys.executable, WRAPPER, "--strategy", STRATEGY, "--cnf", self.cnf, "--workdir", self.wd,
                   "--mem-mb", str(MEM_MB)]
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "FP_DATA": fprun.DATA}
            out, err = open(os.path.join(self.wd, "wrapper.out"), "wb"), open(os.path.join(self.wd, "wrapper.err"), "wb")

            def pre():
                os.setsid()
                os.sched_setaffinity(0, {core})
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


def finalize(job, stage_dir):
    """Classify, verify, write the record (runs in a worker thread)."""
    dec = None
    if job.spec["kind"] == "wrapper":
        p = os.path.join(job.wd, "decision.json")
        dec = json.load(open(p)) if os.path.exists(p) else None
        so = (dec or {}).get("answer_stdout") or os.path.join(job.wd, "final.out")
        proof = (dec or {}).get("answer_proof") or os.path.join(job.wd, "final.lrat")
    else:
        so, proof = job.so, job.proof
    status_line, stats, _ = twlib.parse_stats(so) if os.path.exists(so) else (None, {}, {})
    ver = None
    answered = job.exit_code in (10, 20)
    if answered:
        ver = fprun.verify(job.exit_code, job.cnf, so, proof, max(300.0, job.cpu), MEM_MB, job.wd)
    if answered:
        status = {True: "solved", False: "wrong"}.get(ver["ok"] if ver else None, "unverified")
    elif job.stop_reason == "cap":
        status = "noncompetitive_bound"
    elif job.stop_reason == "budget":
        status = "censored"
    else:
        status = "error"
    rec = {"id": job.id, "key": job.key, "instance": job.spec["instance"], "method": job.spec["method"],
           "kind": job.spec["kind"], "host": socket.gethostname(), "core": job.core, "slurm_job": os.environ.get("SLURM_JOB_ID"),
           "start_utc": job.start, "end_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "cpu": job.cpu, "cpu_user": job.cpu_user, "cpu_sys": job.cpu_sys, "wall": job.wall, "maxrss_kb": job.maxrss,
           "exit_code": job.exit_code, "stop_reason": job.stop_reason, "status": status, "verification": ver,
           "status_line": status_line, "stats": stats, "decision": dec, "cmd": job.cmd,
           "proof_bytes": os.path.getsize(proof) if os.path.exists(proof) else None}
    if dec is not None:
        rec["formal_cpu"] = job.cpu - dec["cpu_at_exec"]
        rec["action"] = dec["action"]
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
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    plan = json.load(open(a.plan))
    stage_dir = os.path.join(OUT, a.stage)
    os.makedirs(stage_dir, exist_ok=True)
    specs = plan["jobs"]
    if a.status:
        done = sum(os.path.exists(os.path.join(stage_dir, job_key(s, a.stage)[1] + ".json")) for s in specs)
        print(json.dumps({"stage": a.stage, "jobs": len(specs), "done": done}))
        return
    cores = fprun.physical_cores()
    pending = [s for s in specs if not os.path.exists(os.path.join(stage_dir, job_key(s, a.stage)[1] + ".json"))]
    prior = sum(json.load(open(os.path.join(stage_dir, job_key(s, a.stage)[1] + ".json")))["cpu"]
                for s in specs if s not in pending)
    if len(pending) > len(cores) - 4:
        raise SystemExit("more jobs than free physical cores")
    step = max(1, (len(cores) - 4) // max(1, len(pending)))
    jobs = [Job(s, a.stage, cores[k * step]) for k, s in enumerate(pending)]
    free = [c for c in cores if c not in {j.core for j in jobs}]
    budget = a.budget_cpu_hours * 3600.0
    print(f"[longrun] {a.stage}: {len(specs)} jobs, {len(jobs)} pending, budget {a.budget_cpu_hours} CPU-h "
          f"(already spent {prior / 3600:.2f})", flush=True)
    for j in jobs:
        j.launch()
    os.sched_setaffinity(0, set(free))  # controller and checkers stay off the job cores
    pool = cf.ThreadPoolExecutor(max_workers=8)
    futs = []
    last_hb = 0
    stopping = False
    while True:
        running = [j for j in jobs if not j.done]
        for j in running:
            if j.poll():
                futs.append(pool.submit(finalize, j, stage_dir))
                print(f"[longrun] exit {j.spec['instance'][:10]} {j.spec['method']} code={j.exit_code} "
                      f"cpu={j.cpu:.1f} stop={j.stop_reason}", flush=True)
            elif j.spec.get("cap_cpu") and j.cpu >= j.spec["cap_cpu"]:
                j.term("cap")
            j.kill_if_late()
        running = [j for j in jobs if not j.done]
        spent = prior + sum(j.cpu for j in jobs)
        if not stopping and spent >= budget and running:
            stopping = True
            print(f"[longrun] budget reached ({spent / 3600:.2f} CPU-h): stopping {len(running)} jobs", flush=True)
            for j in running:
                j.term("budget")
        if time.time() - last_hb > 60 or not running:
            last_hb = time.time()
            hb = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "host": socket.gethostname(),
                  "slurm_job": os.environ.get("SLURM_JOB_ID"), "spent_cpu_hours": spent / 3600,
                  "budget_cpu_hours": a.budget_cpu_hours,
                  "jobs": [{"id": j.id, "instance": j.spec["instance"], "method": j.spec["method"], "cpu": j.cpu,
                            "state": "finished" if j.done else ("stopping" if j.stop_reason else "running")} for j in jobs]}
            fprun.atomic_write_json(os.path.join(stage_dir, "progress.json"), hb)
        if not running:
            break
        time.sleep(2)
    for f in futs:
        r = f.result()
        print(f"[longrun] record {r['instance'][:10]} {r['method']} {r['status']} cpu={r['cpu']:.1f}", flush=True)
    print("[longrun] done", flush=True)


if __name__ == "__main__":
    main()
