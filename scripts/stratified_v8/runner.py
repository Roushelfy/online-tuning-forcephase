#!/usr/bin/env python3
"""Run a queued research stage with CPU accounting and no CPU-hour stop.

Aggregate compute is unlimited (no project / stage CPU-hour stop; legacy
--budget-cpu-hours is accepted but ignored). Since 2026-10-25 every run is
capped at 3600 CPU s of process-tree CPU (configs/run_timeout_policy.json via
scripts/run_timeout_policy.py): controller stop at cap_cpu plus kernel
RLIMIT_CPU (wrappers enforce the remaining budget before exec); unanswered runs
at the cap -> status 'policy_timeout'. Historical protocols describe past runs;
reproduce those using their pinned historical commit.
"""

import argparse
import concurrent.futures as cf
import gzip
import hashlib
import json
import math
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
import resource_policy  # noqa: E402
import run_timeout_policy  # noqa: E402

FORMAL = os.environ.get("FP_FORMAL_OVERRIDE") or os.path.join(ROOT, "build", "fpc", "cadical")  # override: tests only
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
    if j.get("resource_policy_id"):
        key["resource_policy_id"] = j["resource_policy_id"]
        key["cap_kind"] = j.get("cap_kind")
    if j.get("run_policy_id"):
        key["run_policy_id"] = j["run_policy_id"]
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
        cpu_cap = self.spec.get("cap_cpu") if self.spec.get("cap_kind") == "policy_timeout" else None
        self.so, self.proof = os.path.join(self.wd, "final.out"), os.path.join(self.wd, "final.lrat")
        if self.spec["method"] == "W":
            cmd = [sys.executable, WRAPPER, "--strategy", os.path.join(ROOT, self.spec["strategy"]), "--cnf", self.cnf,
                   "--workdir", self.wd, "--mem-mb", str(MEM_MB)]
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "FP_DATA": fprun.DATA}
            if self.spec.get("cap_kind") == "policy_timeout":  # the wrapper enforces the cap on its whole tree too
                env[run_timeout_policy.ENV_LIMIT] = repr(float(self.spec["cap_cpu"]))
            for k in ("FP_RUN_TIMEOUT_POLICY", "FP_FORMAL_OVERRIDE"):  # tests only
                if os.environ.get(k):
                    env[k] = os.environ[k]
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
                if cpu_cap:  # kernel-enforced per-run cap (SIGXCPU), besides the controller's own stop
                    resource.setrlimit(resource.RLIMIT_CPU, (int(math.ceil(cpu_cap)), int(math.ceil(cpu_cap)) + 60))
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
        status = run_timeout_policy.classify_after_cap(True, job.cpu, job.spec, status)
    elif job.stop_reason == "cap" and job.spec.get("cap_kind") == "oracle_noncompetitive_bound":
        status = "noncompetitive_bound"
    elif run_timeout_policy.is_timeout(job.cpu, job.spec, job.exit_code):
        status = "policy_timeout"
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
    ap.add_argument("--budget-cpu-hours", type=float, default=None,
                    help="deprecated compatibility argument; ignored by current no-limit policy")
    ap.add_argument("--quiet-outcomes", action="store_true",
                    help="log only job counts (no per-run CPU/answers); used for sealed runs")
    a = ap.parse_args()
    policy = resource_policy.load_policy(ROOT)
    with open(a.plan) as plan_file:
        plan = resource_policy.prepare_plan(json.load(plan_file), policy)
    plan = run_timeout_policy.apply(plan, run_timeout_policy.load(ROOT))  # per-run 3600 CPU s
    if a.budget_cpu_hours is not None:
        print("[resource-policy] ignoring legacy --budget-cpu-hours; no CPU-hour limit", flush=True)
    stage_dir = os.path.join(OUT, a.stage)
    os.makedirs(stage_dir, exist_ok=True)
    replace_json(os.path.join(stage_dir, "effective_plan.json"), plan)
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
    print(f"[runner] {a.stage}: {len(jobs)} jobs, {len(queue)} pending, {len(slots)} slots; "
          f"CPU-hour limit: none (accounted {prior / 3600:.3f})", flush=True)
    pool = cf.ThreadPoolExecutor(max_workers=8)
    futs, running, free = [], [], list(slots)
    last_hb = 0
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
        while queue and free:
            j = queue.pop(0)
            j.launch(free.pop(0))
            running.append(j)
        if time.time() - last_hb > 60 or not (running or queue):
            last_hb = time.time()
            replace_json(os.path.join(stage_dir, "progress.json"),
                         {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "host": socket.gethostname(),
                          "slurm_job": os.environ.get("SLURM_JOB_ID"), "spent_cpu_hours": spent / 3600,
                          "budget_cpu_hours": None, "resource_policy_id": policy["policy_id"], "finished": finished, "running": len(running),
                          "pending": len(queue),
                          "jobs": [{"id": j.id, "cpu": j.cpu, "state": "running"} for j in running]})
        if not running and not queue:
            break
        time.sleep(1)
    recs = [f.result() for f in futs]
    import collections
    print("[runner] done", dict(collections.Counter(r["status"] for r in recs)), f"not_started={len(queue)}",
          f"cpu_h={sum(r['cpu'] for r in recs) / 3600:.3f}",
          f"checker_cpu_h={sum(((r.get('verification') or {}).get('cpu') or 0) for r in recs) / 3600:.4f}", flush=True)


if __name__ == "__main__":
    main()
