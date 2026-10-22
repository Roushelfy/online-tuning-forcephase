#!/usr/bin/env python3
"""Runner for the three-way study's non-baseline measurements.

  twrun.py profile --hashes configs/three_way/dev_hashes.txt [--jobs 48]
  twrun.py probe   --hashes configs/three_way/dev_hashes.txt --budgets 0.1,0.5,2 [--jobs 48]
  twrun.py wrap    --hashes configs/three_way/test_hashes.txt --model configs/three_way/frozen/X.json [--jobs 48]
  twrun.py collect --hashes ... --what profile|probe|wrap [--budgets ...] [--model ...] --out file.csv

The fixed D / F+ / F- baselines are ordinary scripts/fprun.py runs
(configs/three_way/*_fixed.json). Here: static profiles (cnfprofile), D
probes for the offline dev analysis (twlib.run_probe, the code the wrapper
uses), and real wrapper runs (select_solve.py). Each job is pinned to one
physical core like fprun; records are immutable JSON files under
$FP_DATA/runs/three_way/<kind>/<id[:2]>/<id>.json with content-addressed
ids (inputs, code and binary hashes); existing records are skipped.
A probe or wrapper answer counts only after verification (fprun.verify:
checkmodel / lrat-trim); checker CPU is recorded separately.
"""

import argparse
import csv
import hashlib
import json
import multiprocessing as mp
import os
import random
import shutil
import socket
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE)))
import fprun  # noqa: E402
import twlib  # noqa: E402

OUT = os.environ.get("TW_OUT", os.path.join(fprun.DATA, "runs", "three_way"))
TIMEOUT = 300
MEM_MB = 16000
SCHEMA = 1


def code_sha():
    h = hashlib.sha256()
    for f in ("twlib.py", "select_solve.py"):
        h.update(open(os.path.join(HERE, f), "rb").read())
    return h.hexdigest()


def hashes(path):
    hs = []
    for p in path.split(","):
        hs += [l.split()[0] for l in open(p) if l.strip() and not l.startswith("#")]
    return sorted(set(hs))


def rec_path(kind, rid):
    return os.path.join(OUT, kind, rid[:2], rid + ".json")


def key_id(key):
    return hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()


def plan(a):
    fpc = fprun.binary_info("fpc")["binary_sha256"]
    prof_sha = fprun.sha256_file(twlib.PROFILER)
    base = {"schema": SCHEMA, "binary_sha256": fpc, "profiler_sha256": prof_sha, "code_sha256": code_sha()}
    jobs = []
    for h in hashes(a.hashes):
        if a.cmd == "profile":
            key = dict(base, kind="profile", instance=h)
            key.pop("binary_sha256")
            jobs.append(("profile", key))
        elif a.cmd == "probe":
            for b in map(float, a.budgets.split(",")):
                jobs.append(("probe", dict(base, kind="probe", instance=h, budget=b, mem_mb=MEM_MB)))
        elif a.cmd == "wrap":
            msha = fprun.sha256_file(a.model)
            jobs.append(("wrap", dict(base, kind="wrap", instance=h, model=os.path.basename(a.model),
                                      model_sha256=msha, timeout=TIMEOUT, mem_mb=MEM_MB)))
    return [(k, key, key_id(key)) for k, key in jobs]


def verify_answer(code, cnf, stdout_path, proof_path, work):
    if code not in (10, 20):
        return None
    return fprun.verify(code, cnf, stdout_path, proof_path, TIMEOUT, MEM_MB, work)


def do_profile(key, rid, work):
    cnf = fprun.stage_cnf(key["instance"], "orig", 0)
    t0 = time.time()
    prof = twlib.run_profile(cnf)
    return {"profile": prof, "wall": time.time() - t0}


def do_probe(key, rid, work):
    cnf = fprun.stage_cnf(key["instance"], "orig", 0)
    pr = twlib.run_probe(cnf, key["budget"], work, key["mem_mb"])
    ver = verify_answer(pr["exit_code"], cnf, pr["stdout"], pr["proof"], work)
    pr["verification"] = ver
    pr["solved"] = bool(pr["answered"] and ver and ver["ok"] is True)  # as in the wrapper: any verified answer
    for k in ("stdout", "proof", "telemetry"):
        pr.pop(k, None)
    return pr


def do_wrap(key, rid, work, model_path):
    cnf = fprun.stage_cnf(key["instance"], "orig", 0)
    wd = os.path.join(work, "w")
    cmd = [sys.executable, os.path.join(HERE, "select_solve.py"), "--model", model_path, "--cnf", cnf,
           "--timeout", str(key["timeout"]), "--workdir", wd, "--mem-mb", str(key["mem_mb"])]
    so, se = os.path.join(work, "wrapper.out"), os.path.join(work, "wrapper.err")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    # guard only: select_solve.py enforces the budget itself
    r = fprun.run_limited(cmd, env, key["timeout"] + 30, key["mem_mb"] + 4000, None, so, se,
                          wall_limit=2 * key["timeout"] + 120)
    res_path = os.path.join(wd, "result.json")
    res = json.load(open(res_path)) if os.path.exists(res_path) else None
    rec = {"wrapper_exit": r["exit_code"], "wrapper_terminated_by": r["terminated_by"], "total_cpu": r["cpu"],
           "wall": r["wall"], "maxrss_kb": r["maxrss_kb"], "result": res,
           "wrapper_stderr_tail": open(se, "rb").read()[-1500:].decode("utf-8", "replace")}
    ver = None
    if res and res.get("answer_exit") in (10, 20):
        ver = verify_answer(res["answer_exit"], cnf, res["answer_stdout"], res["answer_proof"], work)
        o, so_ = fprun.parse_solver_output(res["answer_stdout"])[0:2]
        rec["answer_stats"] = so_
    rec["verification"] = ver
    answered = bool(res and res.get("answer_exit") in (10, 20))
    within = r["cpu"] <= key["timeout"] and r["terminated_by"] is None
    if answered and within:
        rec["status"] = {True: "solved", False: "wrong"}.get(ver["ok"] if ver else None, "unverified")
    elif res is None:
        rec["status"] = "error"
    else:
        rec["status"] = "timeout"
    rec["result_label"] = {10: "SAT", 20: "UNSAT"}.get(res.get("answer_exit")) if rec["status"] == "solved" else None
    rd = os.path.join(OUT, "wrap_raw", rid[:2], rid)
    os.makedirs(rd, exist_ok=True)
    for f in ("final.err", "probe.err", "final.tel.jsonl", "probe.tel.jsonl"):
        fprun.compress_into(os.path.join(wd, f), os.path.join(rd, f + ".gz"))
    for f in ("final.out", "probe.out"):  # drop witness lines, keep the log
        p = os.path.join(wd, f)
        if os.path.exists(p):
            with open(p, "rb") as fi, open(p + ".nov", "wb") as fo:
                for line in fi:
                    if not line.startswith(b"v "):
                        fo.write(line)
            fprun.compress_into(p + ".nov", os.path.join(rd, f + ".gz"))
    fprun.compress_into(se, os.path.join(rd, "wrapper.err.gz"))
    return rec


def execute(job, core, model_path, log):
    kind, key, rid = job
    path = rec_path(kind, rid)
    if os.path.exists(path):
        return "exists"
    os.makedirs(os.path.join(fprun.LOCAL, "work"), exist_ok=True)
    work = tempfile.mkdtemp(prefix=f"tw_{kind}_{rid[:10]}_", dir=os.path.join(fprun.LOCAL, "work"))
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        if kind == "profile":
            body = do_profile(key, rid, work)
        elif kind == "probe":
            body = do_probe(key, rid, work)
        else:
            body = do_wrap(key, rid, work, model_path)
        rec = {"id": rid, "key": key, "host": socket.gethostname(), "core": core, "cpu_model": fprun.cpu_model(),
               "slurm_job": os.environ.get("SLURM_JOB_ID"), "start_utc": start,
               "end_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **body}
        fprun.atomic_write_json(path, rec)
        with open(log, "a") as f:
            f.write(json.dumps({"id": rid, "kind": kind, "event": "done", "start": start,
                                "status": body.get("status") or body.get("solved")}) + "\n")
        return "done"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def worker(args):
    jobs, core, model_path, log = args
    if core is not None:
        os.sched_setaffinity(0, {core})
    out = {}
    for j in jobs:
        try:
            st = execute(j, core, model_path, log)
        except Exception as e:
            st = "runner-error"
            with open(log, "a") as f:
                f.write(json.dumps({"id": j[2], "event": "runner-error", "error": repr(e),
                                    "traceback": traceback.format_exc()[-2000:]}) + "\n")
        out[st] = out.get(st, 0) + 1
    return out


def cmd_run(a):
    jobs = plan(a)
    i, n = map(int, a.shard.split("/"))
    mine = [j for j in jobs if int(j[2][:8], 16) % n == i and not os.path.exists(rec_path(j[0], j[2]))]
    random.Random(a.order_seed).shuffle(mine)
    cores = fprun.physical_cores()
    if a.jobs and a.jobs < len(cores):
        step = len(cores) / a.jobs
        cores = [cores[int(k * step)] for k in range(a.jobs)]
    nj = min(a.jobs or len(cores), len(cores), max(1, len(mine)))
    os.makedirs(os.path.join(OUT, "attempts"), exist_ok=True)
    log = os.path.join(OUT, "attempts", f"{a.cmd}-{socket.gethostname()}-{os.getpid()}.jsonl")
    print(f"[twrun] {a.cmd}: {len(jobs)} jobs, {len(mine)} to run on {nj} cores", flush=True)
    chunks = [mine[k::nj] for k in range(nj)]
    model_path = os.path.abspath(a.model) if getattr(a, "model", None) else None
    totals = {}
    with mp.Pool(nj) as pool:
        for out in pool.imap_unordered(worker, [(chunks[k], cores[k], model_path, log) for k in range(nj)]):
            for s, c in out.items():
                totals[s] = totals.get(s, 0) + c
    print(f"[twrun] done {totals}", flush=True)


def cmd_status(a):
    jobs = plan(a)
    done = sum(os.path.exists(rec_path(k, rid)) for k, _, rid in jobs)
    print(json.dumps({"cmd": a.cmd, "jobs": len(jobs), "done": done}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["profile", "probe", "wrap"])
    ap.add_argument("--hashes", required=True)
    ap.add_argument("--budgets", default="0.1,0.5,2")
    ap.add_argument("--model")
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--order-seed", type=int, default=1)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.cmd == "wrap" and not a.model:
        raise SystemExit("--model required")
    (cmd_status if a.status else cmd_run)(a)


if __name__ == "__main__":
    main()
