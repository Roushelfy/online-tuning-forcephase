"""Real end-to-end runs that check the replay accounting on a sample (same host, same measurement path).

Per instance, two pipelines, each with a total budget of 600 CPU s, one CPU token:
  static : native_linear42 on the .xz (8 s, retry 16 s after the CPU limit) -> chosen mode (frozen OOF action of the
           re-implemented static selector; D if acquisition failed) runs from scratch with cutoff 600 - fees;
           fees = measured acquisition CPU + the replay's measured query CPU.
  probe  : three real probes D -> F+ -> F- of W CPU s each on the full formula (patched binary, telemetry on);
           a probe that exits with a verified answer ends the instance; otherwise every probe is SIGSTOPped at W,
           the frozen OOF action of the dynamic selector is SIGCONTinued, the other two are killed, and the chosen
           process is stopped when the CPU of all three processes reaches 600 s (SIGTERM, SIGKILL after 5 s).
Answers are verified as in the baseline (model check / lrat-trim). Output: one JSON line per instance.

  python3 tools/anni2022_e2e.py --sample SAMPLE.json --out OUT.jsonl --shard I/N --data DATA --tools TOOLS
"""
import argparse
import json
import lzma
import os
import queue
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.anniversary2022_baseline.common import check_model, process_state, sha  # noqa: E402
from src.anniversary2022_baseline.run_one import limited_process  # noqa: E402

MODES = {"D": ["--phase=1", "--forcephase=0"], "Fplus": ["--phase=1", "--forcephase=1"], "Fminus": ["--phase=0", "--forcephase=1"]}
NAMES = list(MODES)
BUDGET = 600.0; MEM = 32 * 1024 ** 3


def verify(status, cnf, log, proof, checker, cpu, work, tag):
    if status == "SAT":
        return check_model(cnf, log)
    if status == "UNSAT":
        clog = work / f"checker_{tag}.log"
        r = limited_process([checker, "--no-trim", str(cnf), str(proof)], clog, 1800, 2400, MEM, MEM, cpu,
                            work / f"checker_{tag}_active.json", 5)
        return r["exit_code"] == 20 and any(l.strip() == "s VERIFIED" for l in clog.read_text(errors="replace").splitlines())
    return False


def static_pipeline(k, cnf, xz, action, query_fee, a, cpu, work):
    fee, attempts, ok = 0.0, [], False
    for name in ("native_linear42", "native_linear42_cpu16"):
        t0 = time.monotonic()
        p = subprocess.Popen(["taskset", "-c", str(cpu), str(Path(a.tools) / name), str(xz)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        p.stdout.read(); _, st, ru = os.wait4(p.pid, 0); code = os.waitstatus_to_exitcode(st); c = ru.ru_utime + ru.ru_stime
        fee += c; attempts.append({"binary": name, "exit": code, "cpu_s": c}); ok = code == 0
        if ok or not (code in (-24, -9) and c >= 7.9): break
    if ok: fee += query_fee
    else: action = "D"
    log, proof = work / "static.log", work / "static.lrat"
    cmd = [a.binary, *MODES[action], "--seed=0", "--stats", "--lrat", "--binary=true", "-t", "1800", str(cnf), str(proof)]
    m = limited_process(cmd, log, max(BUDGET - fee, 0.01), 1800, MEM, MEM, cpu, work / "static_active.json", 5)
    status = {10: "SAT", 20: "UNSAT"}.get(m["exit_code"]) if m["stop_reason"] is None else "CPU_TIMEOUT"
    solved = bool(status) and status != "CPU_TIMEOUT" and verify(status, cnf, log, proof, a.checker, cpu, work, "static") and fee + m["cpu_s"] <= BUDGET
    proof.unlink(missing_ok=True)
    return {"action": action, "acquisition": attempts, "fees_s": fee, "solver_cpu_s": m["cpu_s"], "status": status,
            "solved": solved, "total_cpu_s": fee + m["cpu_s"], "PAR2": fee + m["cpu_s"] if solved else 2 * BUDGET}


def cpu_of(pid):
    s = process_state(pid)
    return s["cpu_s"] if s else None


def probe_pipeline(k, cnf, action, w, a, cpu, work):
    procs, spent, events = {}, {}, []
    def start(m):
        log = (work / f"probe_{m}.log").open("wb")
        backstop = int(BUDGET * 1.02) + 5
        p = subprocess.Popen(["prlimit", f"--as={MEM}", f"--fsize={MEM}", f"--cpu={backstop}:{backstop + 5}", "--", "taskset", "-c", str(cpu),
                              a.binary, *MODES[m], "--anniprobe=50", "--seed=0", "--stats", "--lrat", "--binary=true", "-t", "1800",
                              str(cnf), str(work / f"probe_{m}.lrat")], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        return p, log
    def finish(m, p, log, ru, st):
        log.close(); code = os.waitstatus_to_exitcode(st); c = ru.ru_utime + ru.ru_stime
        status = {10: "SAT", 20: "UNSAT"}.get(code)
        ok = bool(status) and verify(status, cnf, work / f"probe_{m}.log", work / f"probe_{m}.lrat", a.checker, cpu, work, f"probe_{m}")
        return code, c, status, ok
    def kill_all(except_mode=None):
        for m, (p, log) in list(procs.items()):
            if m == except_mode: continue
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            try: os.killpg(p.pid, signal.SIGCONT)
            except ProcessLookupError: pass
            _, st, ru = os.wait4(p.pid, 0); log.close(); spent[m] = ru.ru_utime + ru.ru_stime; del procs[m]
    for m in NAMES:
        p, log = start(m)
        while True:
            pid, st, ru = os.wait4(p.pid, os.WNOHANG)
            if pid:
                code, c, status, ok = finish(m, p, log, ru, st); spent[m] = c
                if ok:
                    kill_all(); total = sum(spent.values())
                    return {"solved_in_probe": m, "status": status, "solved": total <= BUDGET, "total_cpu_s": total,
                            "PAR2": total if total <= BUDGET else 2 * BUDGET, "spent": spent}
                events.append({"mode": m, "exit_before_w": code}); break
            c = cpu_of(p.pid)
            if c is not None and c >= w:
                os.killpg(p.pid, signal.SIGSTOP); procs[m] = (p, log); break
            time.sleep(0.005)
    chosen = action
    if chosen not in procs:  # the chosen probe already ended without a verified answer: nothing left to continue
        kill_all(); total = sum(spent.values())
        return {"chosen": chosen, "status": None, "solved": False, "total_cpu_s": total, "PAR2": 2 * BUDGET, "spent": spent, "events": events}
    kill_all(except_mode=chosen)
    p, log = procs[chosen]; others = sum(spent.values())
    os.killpg(p.pid, signal.SIGCONT); reason = None; stop_at = None
    while True:
        pid, st, ru = os.wait4(p.pid, os.WNOHANG)
        if pid: break
        c = cpu_of(p.pid)
        if reason is None and c is not None and others + c >= BUDGET:
            reason = "CPU_BUDGET"; stop_at = time.monotonic(); os.killpg(p.pid, signal.SIGTERM)
        elif reason and time.monotonic() - stop_at > 5:
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        time.sleep(0.02)
    code, c, status, ok = finish(chosen, p, log, ru, st); spent[chosen] = c
    total = others + c
    solved = ok and reason is None and total <= BUDGET
    return {"chosen": chosen, "status": status if reason is None else "CPU_TIMEOUT", "solved": solved, "total_cpu_s": total,
            "PAR2": total if solved else 2 * BUDGET, "spent": spent, "events": events}


def main():
    ap = argparse.ArgumentParser()
    for x in ("--sample", "--out", "--shard", "--data", "--tools", "--binary", "--checker"): ap.add_argument(x, required=True)
    ap.add_argument("--workers", type=int, default=8); ap.add_argument("--w", type=float, default=2.0)
    a = ap.parse_args(); i, n = map(int, a.shard.split("/"))
    sample = json.load(open(a.sample)); rows = sample["instances"][i::n]
    out = Path(a.out); done = {r["instance_key"] for r in map(json.loads, out.open()) if "error" not in r} if out.exists() else set()
    rows = [r for r in rows if r["instance_key"] not in done]
    receipts = sample["input_sha256"]
    cpus = sorted(os.sched_getaffinity(0))[:a.workers]; tokens = queue.Queue(); [tokens.put(c) for c in cpus]
    local = Path("/var/tmp/anni-e2e") / f"shard-{i:03d}"; local.mkdir(parents=True, exist_ok=True); lock = threading.Lock()
    print(f"shard {i}/{n} {socket.gethostname()} cpus {cpus} todo {len(rows)}", flush=True)

    def job(r):
        cpu = tokens.get(); prev = os.sched_getaffinity(0); k = r["instance_key"]
        work = local / k; shutil.rmtree(work, ignore_errors=True); work.mkdir(parents=True)
        try:
            os.sched_setaffinity(0, {cpu})
            xz = Path(a.data) / "cnf_xz" / f"{k}.cnf.xz"; cnf = work / "input.cnf"
            with lzma.open(xz) as s, cnf.open("wb") as d: shutil.copyfileobj(s, d, 1 << 20)
            assert sha(cnf) == receipts[k], "input SHA"
            rec = {"instance_key": k, "host": socket.gethostname(), "cpu_token": cpu, "replay": r["replay"]}
            rec["static"] = static_pipeline(k, cnf, xz, r["static_action"], r["static_query_fee"], a, cpu, work)
            rec["probe"] = probe_pipeline(k, cnf, r["probe_action"], a.w, a, cpu, work)
        except Exception as e:
            rec = {"instance_key": k, "error": repr(e)}
        finally:
            os.sched_setaffinity(0, prev); tokens.put(cpu); shutil.rmtree(work, ignore_errors=True)
        with lock, out.open("a") as f: f.write(json.dumps(rec) + "\n")

    with ThreadPoolExecutor(len(cpus)) as ex: list(ex.map(job, rows))
    print("done", flush=True)


if __name__ == "__main__":
    main()
