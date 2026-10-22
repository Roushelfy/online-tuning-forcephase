"""Shared code of the three-way (D / F+ / F-) one-shot selection study.

Pure standard library, so the deployable wrapper (select_solve.py) starts
fast and charges little CPU. Used identically by the offline dev runner
(twrun.py profile/probe) and by the wrapper, so dev features and deployed
features are computed by the same code.

Actions are the round-1 solver configurations (configs/solver_configs.json)
on the round-1 binary build/fpc with the round-1 run policy (--lrat=1 proof,
--fpc=1 telemetry, seed 0), so a wrapper's final solve of action X is the
same search as the fixed baseline X.
"""

import json
import math
import os
import re
import signal
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BINARY = os.path.join(ROOT, "build", "fpc", "cadical")
PROFILER = os.path.join(ROOT, "build", "tools", "cnfprofile")
ACTIONS = {  # name -> (round-1 config name, CaDiCaL args)
    "D": ("D", ["--phase=1", "--forcephase=0"]),
    "Fp": ("Fplus", ["--phase=1", "--forcephase=1"]),
    "Fm": ("Fminus", ["--phase=0", "--forcephase=1"]),
}
ACTION_ORDER = ("D", "Fp", "Fm")
RUN_POLICY = ["--lrat=1"]  # proof policy; telemetry (--fpc=1) appended as fprun does
RESERVE = 0.1  # CPU seconds the wrapper keeps back for its own work after the final solve

STATIC_FEATURES = [
    "p_log_vars", "p_log_clauses", "p_cv_ratio", "p_len_mean", "p_len_std", "p_len_max_log",
    "p_unit_frac", "p_bin_frac", "p_ter_frac", "p_len4p_frac", "p_len10p_frac", "p_pos_lit_frac",
    "p_horn_frac", "p_antihorn_frac", "p_allpos_cls_frac", "p_allneg_cls_frac", "p_binpos_frac",
    "p_binneg_frac", "p_var_bal_mean", "p_var_bal_std", "p_var_absbal_mean", "p_var_purepos_frac",
    "p_var_pureneg_frac", "p_var_posmaj_frac", "p_var_negmaj_frac", "p_occ_mean_log", "p_occ_cv",
    "p_occ_max_rel_log"]
PROBE_FEATURES = [
    "q_started", "q_log_conflicts", "q_log_decisions", "q_log_props", "q_conf_per_sec_log",
    "q_dec_per_conf", "q_props_per_dec_log", "q_fixed_frac", "q_elim_frac", "q_learned_len",
    "q_chrono_frac", "q_restarts_per_kconf", "q_neg_dec_frac", "q_native_pos_frac", "q_target_src_frac",
    "q_saved_src_frac", "q_fallback_src_frac", "q_has_checkpoint", "q_cp_glue_mean", "q_cp_glue_low_frac",
    "q_cp_stable_frac", "q_cp_trail_frac", "q_cp_saved_neg_frac", "q_cp_target_neg_frac"]


# ---------------------------------------------------------------- timing

def cpu_of(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            parts = f.read().rsplit(")", 1)[1].split()
        return (int(parts[11]) + int(parts[12])) / os.sysconf("SC_CLK_TCK")
    except (OSError, IndexError, ValueError):
        return None


def self_cpu():
    import resource
    s = resource.getrusage(resource.RUSAGE_SELF)
    c = resource.getrusage(resource.RUSAGE_CHILDREN)
    return s.ru_utime + s.ru_stime + c.ru_utime + c.ru_stime


def run_budget(cmd, env, cpu_limit, mem_mb, stdout_path, stderr_path, grace=None, max_sleep=1.0):
    """Run cmd; SIGTERM when its CPU time reaches cpu_limit, SIGKILL after
    `grace` more seconds. The child (CaDiCaL) is single-threaded, so its CPU
    time grows at most as fast as wall time: we sleep for the CPU time still
    left (at most max_sleep) instead of polling at a fixed rate, which keeps
    the polling CPU (charged to the wrapper) small and stops within ~10 ms
    (/proc tick) of the limit. Returns exit code, CPU (wait4) etc."""
    def pre():
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb << 20, mem_mb << 20))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.setsid()
    grace = max(1.0, cpu_limit) if grace is None else grace
    t0 = time.time()
    with open(stdout_path, "wb") as so, open(stderr_path, "wb") as se:
        p = subprocess.Popen(cmd, stdout=so, stderr=se, env=env, preexec_fn=pre)
        killed_by, term_at = None, None
        while True:
            pid, status, ru = os.wait4(p.pid, os.WNOHANG)
            if pid:
                break
            now = time.time()
            if term_at is None:
                c = cpu_of(p.pid)
                c = 0.0 if c is None else c
                if c >= cpu_limit:
                    killed_by = "cpu"
                elif now - t0 > 4 * cpu_limit + 120:
                    killed_by = "wall"
                if killed_by:
                    os.killpg(p.pid, signal.SIGTERM)
                    term_at = now
                    continue
                time.sleep(min(max(0.002, cpu_limit - c), max_sleep))
            else:
                if now - term_at > grace and not killed_by.endswith("+kill"):
                    os.killpg(p.pid, signal.SIGKILL)
                    killed_by += "+kill"
                time.sleep(0.005)
    code = os.waitstatus_to_exitcode(status)
    return {"exit_code": code, "cpu": ru.ru_utime + ru.ru_stime, "wall": time.time() - t0,
            "maxrss_kb": ru.ru_maxrss, "terminated_by": killed_by}


# ---------------------------------------------------------- static profile

def run_profile(cnf):
    t0 = self_cpu()
    r = subprocess.run([PROFILER, cnf], capture_output=True, text=True)
    cpu = self_cpu() - t0
    if r.returncode != 0:
        return {"error": r.stderr.strip()[:300], "cpu": cpu}
    d = json.loads(r.stdout)
    d["cpu"] = cpu  # profiler + its children, measured from outside
    return d


def _log(x):
    return None if x is None else math.log10(1.0 + max(0.0, x))


def static_features(prof):
    if "error" in prof:
        return {k: None for k in STATIC_FEATURES}
    f = {k: prof.get(k) for k in STATIC_FEATURES if k in prof}
    f["p_len_max_log"] = _log(prof.get("p_len_max"))
    f["p_occ_mean_log"] = _log(prof.get("p_occ_mean"))
    f["p_occ_max_rel_log"] = _log(prof.get("p_occ_max_rel"))
    return {k: f.get(k) for k in STATIC_FEATURES}


# ----------------------------------------------------------- D probe

STAT_RE = re.compile(r"^c (\w+):\s+(\d+)\s+([\d.]+)?")


def parse_stats(path):
    stats, pct, status = {}, {}, None
    with open(path, "rb") as f:
        for raw in f:
            if raw.startswith(b"v "):
                continue
            line = raw.decode("utf-8", "replace")
            if line.startswith("s "):
                status = line[2:].strip()
            m = STAT_RE.match(line)
            if m and m.group(1) not in stats:
                stats[m.group(1)] = int(m.group(2))
                if m.group(3):
                    try:
                        pct[m.group(1)] = float(m.group(3))
                    except ValueError:
                        pass
    return status, stats, pct


def parse_telemetry(path):
    final, last_cp = None, None
    if not os.path.exists(path):
        return None, None
    with open(path) as f:
        for line in f:
            try:
                x = json.loads(line)
            except json.JSONDecodeError:
                continue
            if x.get("type") == "final":
                final = x
            elif x.get("type") == "checkpoint":
                last_cp = x
    return final, last_cp


def run_probe(cnf, budget, workdir, mem_mb=16000):
    """Native D on the original CNF for `budget` CPU seconds, same command as
    the fixed D baseline (LRAT proof + telemetry). Returns a record."""
    os.makedirs(workdir, exist_ok=True)
    so, se = os.path.join(workdir, "probe.out"), os.path.join(workdir, "probe.err")
    tel, proof = os.path.join(workdir, "probe.tel.jsonl"), os.path.join(workdir, "probe.lrat")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "FPC_LOG": tel}
    cmd = [BINARY] + RUN_POLICY + ACTIONS["D"][1] + ["--fpc=1", cnf, proof]
    r = run_budget(cmd, env, budget, mem_mb, so, se)
    status, stats, pct = parse_stats(so)
    final, cp = parse_telemetry(tel)
    r.update({"budget": budget, "status_line": status, "stats": stats, "pct": pct,
              "final": final, "checkpoint": cp, "stdout": so, "proof": proof, "telemetry": tel,
              "answered": r["exit_code"] in (10, 20)})
    return r


def _ratio(a, b):
    return None if a is None or b in (None, 0) else a / b


def probe_features(pr, prof):
    st, pct, fin = pr.get("stats", {}), pr.get("pct", {}), pr.get("final") or {}
    conf, dec, props = st.get("conflicts"), st.get("decisions"), st.get("propagations")
    started = 1.0 if (dec or 0) > 0 or (conf or 0) > 0 else 0.0
    dfree = fin.get("dec_free") or None
    src = fin.get("dec_src") or [None] * 7
    vars_ = prof.get("vars") if "error" not in prof else None
    f = {
        "q_started": started,
        "q_log_conflicts": _log(conf), "q_log_decisions": _log(dec), "q_log_props": _log(props),
        "q_conf_per_sec_log": _log(_ratio(conf, pr.get("cpu"))),
        "q_dec_per_conf": _ratio(dec, conf), "q_props_per_dec_log": _log(_ratio(props, dec)),
        "q_fixed_frac": _ratio(st.get("fixed"), vars_), "q_elim_frac": _ratio(st.get("eliminated"), vars_),
        "q_learned_len": _ratio(st.get("learned_lits"), st.get("learned")),
        "q_chrono_frac": _ratio(st.get("chronological"), conf),
        "q_restarts_per_kconf": None if not conf else 1000.0 * (st.get("restarts") or 0) / conf,
        "q_neg_dec_frac": _ratio(fin.get("dec_neg"), dfree),
        "q_native_pos_frac": _ratio(fin.get("dec_native_pos"), dfree),
        "q_target_src_frac": _ratio(src[3], dfree), "q_saved_src_frac": _ratio(src[4], dfree),
        "q_fallback_src_frac": _ratio(src[6], dfree),
    }
    cp = (pr.get("checkpoint") or {}).get("f") or {}
    f["q_has_checkpoint"] = 1.0 if cp else 0.0
    for k, src_k in (("q_cp_glue_mean", "c_glue_mean"), ("q_cp_glue_low_frac", "c_glue_low_frac"),
                     ("q_cp_stable_frac", "c_stable_frac"), ("q_cp_trail_frac", "x_trail_frac"),
                     ("q_cp_saved_neg_frac", "x_saved_neg_frac"), ("q_cp_target_neg_frac", "x_target_neg_frac")):
        f[k] = cp.get(src_k)
    return {k: f.get(k) for k in PROBE_FEATURES}


# ------------------------------------------------------------- models

def _num(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def predict(model, feats):
    """Pure-Python inference for the exported model formats."""
    kind = model["type"]
    if kind == "const":
        return model["action"]
    if kind == "tree":
        node = model["root"]
        while "leaf" not in node:
            x = _num(feats.get(node["feature"]))
            if x is None:
                x = node["missing_value"]
            node = node["left"] if x <= node["threshold"] else node["right"]
        return node["leaf"]
    if kind == "logreg":
        z = []
        for a in model["classes"]:
            s = model["intercept"][a]
            for k, w in model["coef"][a].items():
                x = _num(feats.get(k))
                x = model["impute"][k] if x is None else x
                s += w * (x - model["mean"][k]) / model["scale"][k]
            z.append(s)
        return model["classes"][max(range(len(z)), key=lambda i: z[i])]
    raise ValueError(kind)
