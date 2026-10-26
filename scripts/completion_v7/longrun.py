#!/usr/bin/env python3
"""Run a queued research stage with CPU accounting and no CPU-hour stop.

Aggregate compute is unlimited (no project / stage CPU-hour stop; legacy
--budget-cpu-hours is accepted but ignored). Since 2026-10-25 every run is
capped at 3600 CPU s of process-tree CPU (configs/run_timeout_policy.json via
scripts/run_timeout_policy.py): controller stop at cap_cpu plus kernel
RLIMIT_CPU; unanswered runs at the cap -> status 'policy_timeout'. A shorter
explicit oracle_noncompetitive_bound keeps its value. Historical protocols
describe past runs; reproduce those using their pinned historical commit.
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
WRAPPER = os.path.join(HERE, "wrapper_long.py")
STRATEGY = os.path.join(ROOT, "configs", "stable_selection_v6", "frozen", "P1_M05_final.json")
ARGS = {"D": ["--phase=1", "--forcephase=0"], "Fp": ["--phase=1", "--forcephase=1"], "Fm": ["--phase=0", "--forcephase=1"]}
MEM_MB = 16000
TICK = os.sysconf("SC_CLK_TCK")
OUT = os.path.join(fprun.DATA, "runs", "completion_v7")
WORK = os.environ.get("V7_WORK", f"/var/tmp/fp_v7_{os.environ.get('USER', 'user')}")


def sha(p):
    return fprun.sha256_file(p)


def replace_json(path, obj):
    """Overwrite (heartbeats); fprun.atomic_write_json never replaces an existing file."""
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(obj, f, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


DISK_MIN_GB = float(os.environ.get("V7_DISK_MIN_GB", "400"))


def proof_size(job):
    try:
        return os.path.getsize(os.path.join(job.wd, "final.lrat"))
    except (OSError, AttributeError, TypeError):
        return 0


def work_free_gb():
    try:
        return shutil.disk_usage(WORK).free / 1e9
    except OSError:
        return None


def job_key(j, stage):
    key = {"schema": 1, "stage": stage, "instance": j["instance"], "method": j["method"], "kind": j["kind"],
           "formal_sha256": sha(FORMAL), "mem_mb": MEM_MB, "cap_cpu": j.get("cap_cpu"), "seed": 0, "proof": "lrat"}
    if j.get("resource_policy_id"):
        key["resource_policy_id"] = j["resource_policy_id"]
        key["cap_kind"] = j.get("cap_kind")
    if j.get("run_policy_id"):
        key["run_policy_id"] = j["run_policy_id"]
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
        cpu_cap = self.spec.get("cap_cpu") if self.spec.get("cap_kind") == "policy_timeout" else None
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
                if cpu_cap:  # kernel-enforced per-run cap (SIGXCPU), besides the controller's own stop
                    resource.setrlimit(resource.RLIMIT_CPU, (int(math.ceil(cpu_cap)), int(math.ceil(cpu_cap)) + 60))
        else:
            cmd = [sys.executable, WRAPPER, "--strategy", STRATEGY, "--cnf", self.cnf, "--workdir", self.wd,
                   "--mem-mb", str(MEM_MB)]
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
        status = run_timeout_policy.classify_after_cap(True, job.cpu, job.spec, status)
    elif run_timeout_policy.is_timeout(job.cpu, job.spec, job.exit_code):
        status = "policy_timeout"
    elif job.stop_reason == "cap":
        status = {"oracle_noncompetitive_bound": "noncompetitive_bound",
                  "policy_timeout": "policy_timeout"}.get(job.spec.get("cap_kind"), "censored")
    elif job.stop_reason in ("budget", "platform_disk"):
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
    ap.add_argument("--budget-cpu-hours", type=float, default=None,
                    help="deprecated compatibility argument; ignored by current no-limit policy")
    ap.add_argument("--status", action="store_true")
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
    print(f"[longrun] {a.stage}: {len(specs)} jobs, {len(jobs)} pending; "
          f"CPU-hour limit: none (accounted {prior / 3600:.2f})", flush=True)
    for j in jobs:
        j.launch()
    os.sched_setaffinity(0, set(free))  # controller and checkers stay off the job cores
    pool = cf.ThreadPoolExecutor(max_workers=8)
    futs = []
    last_hb = 0
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
        if time.time() - last_hb > 60 or not running:
            last_hb = time.time()
            free_gb = work_free_gb()
            # platform guard (not a CPU limit): LRAT proofs live on node-local disk; when it is nearly
            # full, stop the running job with the largest proof -> 'censored', stop_reason 'platform_disk'
            if free_gb is not None and free_gb < DISK_MIN_GB and running and not any(j.stop_reason == "platform_disk" and not j.done for j in jobs):
                victim = max(running, key=lambda j: proof_size(j))
                print(f"[longrun] platform guard: {free_gb:.0f} GB free on {WORK}; stopping "
                      f"{victim.spec['instance'][:10]} {victim.spec['method']} (proof {proof_size(victim) / 1e9:.0f} GB)",
                      flush=True)
                victim.term("platform_disk")
            hb = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "host": socket.gethostname(),
                  "slurm_job": os.environ.get("SLURM_JOB_ID"), "spent_cpu_hours": spent / 3600,
                  "budget_cpu_hours": None, "resource_policy_id": policy["policy_id"], "work_free_gb": free_gb,
                  "proof_gb": {j.id: proof_size(j) / 1e9 for j in running},
                  "jobs": [{"id": j.id, "instance": j.spec["instance"], "method": j.spec["method"], "cpu": j.cpu,
                            "state": "finished" if j.done else ("stopping" if j.stop_reason else "running")} for j in jobs]}
            replace_json(os.path.join(stage_dir, "progress.json"), hb)
        if not running:
            break
        time.sleep(2)
    for f in futs:
        r = f.result()
        print(f"[longrun] record {r['instance'][:10]} {r['method']} {r['status']} cpu={r['cpu']:.1f}", flush=True)
    print("[longrun] done", flush=True)


if __name__ == "__main__":
    main()
