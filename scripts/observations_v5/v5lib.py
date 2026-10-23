"""Runtime code of goal v5 (docs/OBSERVATION_PROTOCOL_V5.md): observation
packages, the obsprofile tool and probe arms. Pure standard library, so the
deployable wrapper (v5_wrapper.py) and the offline dev collection
(obsrun.py) run exactly the same code.

Probe arms use the observation build build/obs (search-equivalent to the
formal binary, verified in V1) with the formal run policy (LRAT proof, seed
0) plus telemetry windows of 100 conflicts; formal solves use build/fpc.
"""

import gzip
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts", "three_way"))
import twlib  # noqa: E402  (run_budget, parse_stats, ACTIONS, RUN_POLICY, RESERVE, static_features)

FORMAL = os.path.join(ROOT, "build", "fpc", "cadical")
PROBE = os.path.join(ROOT, "build", "obs", "cadical")
OBSPROFILE = os.path.join(ROOT, "build", "tools", "obsprofile")
ACTIONS = twlib.ACTIONS              # D / Fp / Fm -> (config name, args)
ACT_ORDER = ("D", "Fp", "Fm")
RUN_POLICY = twlib.RUN_POLICY        # ["--lrat=1"]
RESERVE = twlib.RESERVE              # 0.1
T = 300.0
PAR2 = 600.0
OBS_SEED = 20261023
SECTION_CAPS = {"polar": 0.5, "resid": 0.5, "bilat": 0.5, "graph": 0.5, "comm": 1.0, "ls": 0.6}
PROBE_WIN = 100

# Arm specs: tag -> (budget CPU s, conflict limit or None)
ARMS = {"e02": (0.2, None), "e05": (0.5, None), "ec": (1.0, 512), "fD": (2.0, None)}

# Packages (protocol section 4). static: obsprofile sections; scap: cap of
# the static part (parsing included); arms: (tag, actions) run in order.
PACKAGES = {
    "R01": {"static": ["polar", "resid"], "scap": 3.0, "arms": []},
    "R02": {"static": ["resid", "bilat"], "scap": 3.0, "arms": []},
    "R03": {"static": ["resid", "graph"], "scap": 3.0, "arms": []},
    "R04": {"static": ["resid", "comm"], "scap": 3.0, "arms": []},
    "R05": {"static": [], "scap": 3.0, "arms": [("fD", ("D",))]},
    "R06": {"static": [], "scap": 3.0, "arms": [("e02", ACT_ORDER)]},
    "R07": {"static": [], "scap": 3.0, "arms": [("e05", ACT_ORDER)]},
    "R08": {"static": [], "scap": 3.0, "arms": [("ec", ACT_ORDER)]},
    "R09": {"static": ["resid", "ls"], "scap": 3.0, "arms": []},
    "R10": {"static": ["polar", "resid", "bilat"], "scap": 2.0, "arms": [("e02", ACT_ORDER)]},
    "R11": {"static": ["polar", "resid", "bilat"], "scap": 2.0, "arms": [("e02", ACT_ORDER)], "conditional": True},
}
ALL_SECTIONS = ["s28", "polar", "resid", "bilat", "graph", "comm", "ls"]


# ------------------------------------------------------------ obsprofile

def run_obsprofile(cnf, sections, cap, workdir, mem_mb=16000):
    """Run obsprofile with the given sections ('s28' is always included) and
    total CPU cap. Returns {sections, features, cpu (wait4), exit_code}."""
    os.makedirs(workdir, exist_ok=True)
    secs = ["s28"] + [s for s in sections if s != "s28"]
    caps = ",".join(f"{k}:{v}" for k, v in SECTION_CAPS.items())
    cmd = [OBSPROFILE, f"--sections={','.join(secs)}", f"--cap={cap}", f"--seccap={caps}",
           f"--seed={OBS_SEED}", cnf]
    so, se = os.path.join(workdir, "obsprofile.json"), os.path.join(workdir, "obsprofile.err")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    # guard limit only: the tool enforces 'cap' itself
    r = twlib.run_budget(cmd, env, cap + 5.0, mem_mb, so, se)
    out = {"cpu": r["cpu"], "exit_code": r["exit_code"], "terminated_by": r["terminated_by"], "maxrss_kb": r["maxrss_kb"]}
    try:
        d = json.load(open(so))
        out["sections"], out["features"] = d["sections"], d["features"]
    except (OSError, ValueError, KeyError):
        out["sections"], out["features"] = {}, {}
        out["error"] = open(se, "rb").read()[-500:].decode("utf-8", "replace")
    return out


def static_ok(obs, sections):
    """True when obsprofile ran every requested section to completion."""
    secs = obs.get("sections") or {}
    return all((secs.get(s) or {}).get("status") == "ok" for s in ["parse", "s28"] + list(sections))


def static_cost(obs, sections):
    """CPU of a tool run limited to 'sections' estimated from a full run:
    parse + those sections + the process overhead outside all sections."""
    secs = obs.get("sections") or {}
    inside = sum((v or {}).get("cpu", 0.0) for v in secs.values())
    overhead = max(0.0, obs.get("cpu", 0.0) - inside)
    return overhead + sum((secs.get(s) or {}).get("cpu", 0.0) for s in ["parse", "s28"] + list(sections))


# ------------------------------------------------------------- probe arms

PROF_RE = re.compile(r"^c\s+([\d.]+)\s+([\d.]+)%\s+(\w+)\s*$")


def parse_profile(path):
    """CaDiCaL 'run-time profiling' section: {name: seconds}."""
    prof, inside = {}, False
    with open(path, "rb") as f:
        for raw in f:
            if raw.startswith(b"v "):
                continue
            line = raw.decode("utf-8", "replace")
            if "run-time profiling" in line:
                inside = True
                continue
            if inside:
                if line.startswith("c ---"):
                    break
                m = PROF_RE.match(line)
                if m and m.group(3) not in prof:
                    prof[m.group(3)] = float(m.group(1))
    return prof


WIN_KEYS = ("w_neg_dec_frac", "w_glue_mean", "x_trail_frac", "x_best_frac", "w_learn_pos_frac",
            "w_prop_pos_frac", "x_saved_flip_frac", "x_flip_compared", "x_saved_target_disagree")


def parse_obs_telemetry(path):
    """Final record (complete) and a reduced series of window records."""
    final, wins = None, []
    if not os.path.exists(path):
        return None, wins
    with open(path) as f:
        for line in f:
            try:
                x = json.loads(line)
            except ValueError:
                continue
            t = x.get("type")
            if t == "final":
                final = x
            elif t == "window":
                ff = x.get("f") or {}
                wins.append({"conflicts": x.get("conflicts"), "time": x.get("time"),
                             **{k: ff.get(k) for k in WIN_KEYS}})
    return final, wins


def arm_cmd(action, cnf, proof, conflicts=None):
    cmd = [PROBE] + RUN_POLICY + ACTIONS[action][1] + ["--fpc=1", f"--fpcwin={PROBE_WIN}"]
    if conflicts:
        cmd += ["-c", str(conflicts)]
    return cmd + [cnf, proof]


def run_arm(cnf, action, tag, workdir, mem_mb=16000, keep_raw=None):
    """One probe arm (independent process from the original CNF). Returns a
    record with CPU, exit code, stats, profile times and telemetry. The
    answer (exit 10/20) still has to be verified by the caller.
    keep_raw: directory to keep gzipped stdout (without 'v' lines) and telemetry."""
    budget, conflicts = ARMS[tag]
    os.makedirs(workdir, exist_ok=True)
    stem = os.path.join(workdir, f"{tag}_{action}")
    so, se, tel, proof = stem + ".out", stem + ".err", stem + ".tel.jsonl", stem + ".lrat"
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "FPC_LOG": tel}
    r = twlib.run_budget(arm_cmd(action, cnf, proof, conflicts), env, budget, mem_mb, so, se)
    status, stats, _ = twlib.parse_stats(so)
    final, wins = parse_obs_telemetry(tel)
    rec = {"tag": tag, "action": action, "budget": budget, "conflict_limit": conflicts, **r,
           "status_line": status, "stats": stats, "profile": parse_profile(so),
           "final": final, "windows": wins, "answered": r["exit_code"] in (10, 20),
           "stdout": so, "proof": proof}
    if keep_raw:
        os.makedirs(keep_raw, exist_ok=True)
        with open(so, "rb") as fi, gzip.open(os.path.join(keep_raw, f"{tag}_{action}.out.gz"), "wb") as fo:
            for line in fi:
                if not line.startswith(b"v "):
                    fo.write(line)
        if os.path.exists(tel):
            with open(tel, "rb") as fi, gzip.open(os.path.join(keep_raw, f"{tag}_{action}.tel.jsonl.gz"), "wb") as fo:
                shutil.copyfileobj(fi, fo)
    return rec


# ------------------------------------------------------------- inference

def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v or v in (float("inf"), float("-inf")) else v


def transform(pre, feats):
    """Preprocessing exported by v5select: median imputation, missing
    indicators, standardisation with clipping. Returns the model input list."""
    z = []
    for col in pre["columns"]:
        name, kind = col["name"], col["kind"]
        x = _num(feats.get(name))
        if kind == "missing":
            z.append(1.0 if x is None else 0.0)
            continue
        if x is None:
            x = col["median"]
        if pre.get("standardize"):
            x = (x - col["mean"]) / col["scale"]
            x = max(-5.0, min(5.0, x))
        z.append(x)
    return z


def tree_value(node, z):
    while "value" not in node:
        node = node["left"] if z[node["feature"]] <= node["threshold"] else node["right"]
    return node["value"]


def predict_gain(reader, z):
    """Predicted gains {Fp: g, Fm: g} of a reader (ridge / tree / forest)."""
    out = {}
    for a, m in reader["models"].items():
        if m["type"] == "ridge":
            out[a] = m["intercept"] + sum(w * x for w, x in zip(m["coef"], z))
        elif m["type"] == "tree":
            out[a] = tree_value(m["root"], z)
        elif m["type"] == "forest":
            out[a] = sum(tree_value(t, z) for t in m["trees"]) / len(m["trees"])
        else:
            raise ValueError(m["type"])
    return out


def decide(reader, feats):
    """Gate: deviate to the action with the largest predicted gain only when
    it exceeds theta; else D. Returns (action, gains)."""
    z = transform(reader["pre"], feats)
    g = predict_gain(reader, z)
    best = max(("Fp", "Fm"), key=lambda a: (g[a], a == "Fp"))
    theta = reader["theta"]
    return (best if theta is not None and g[best] > theta else "D"), g
