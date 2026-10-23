"""Runtime code of goal v6 (docs/STABLE_SELECTION_PROTOCOL_V6.md section 4):
input packages, feature extraction and pure-Python inference for the
readers RG (v5 ridge gate), M05 (solve probability + conditional time) and
the two depth-2 rules. Used identically by the offline analysis
(v6data/v6select) and the deployed wrapper (v6_wrapper.py). Standard library only.
"""

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "observations_v5"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "three_way"))
import szlib  # noqa: E402
import twlib  # noqa: E402
import v5lib  # noqa: E402

OBS6 = os.path.join(ROOT, "build", "tools", "obsprofile6")
LS_FLIPS = 50000                     # chosen in R2 (results/stable_selection_v6/r2_choices.json)
SZ_GROUPS = ["ncnf-constraints", "ncnf-rwh", "unit"]
SECTION_CAPS6 = {"polar": 0.5, "resid": 0.5, "bilat": 0.5, "graph": 0.5, "comm": 1.0, "ls": 1.0}
SEED = 20261023
KAPPA = 0.032                        # v5 measured wrapper overhead of a static package
T, PAR2, RESERVE = 300.0, 600.0, 0.1
S28 = list(twlib.STATIC_FEATURES)
RLS = ["l6_dbest_01", "l6_dbest_0r", "l6_dbest_1r", "l6_ddesc_01", "l6_ddens_01", "l6_agree_01"]
RSYM = ["b03_props_lr_top16", "b03_props_lr_mean", "d01_reach_lr_mean", "d01_reach_pos_gt_frac",
        "c04_inverse_share", "b02_fail_any_frac"]

# package -> obsprofile6 sections (s28 always), whether SATzilla runs, feature set
PACKAGES = {
    "P1": {"sections": [], "sz": False, "feats": "S28"},
    "P2": {"sections": ["resid", "ls"], "sz": False, "feats": "S28+LS6"},
    "P3": {"sections": [], "sz": True, "feats": "S28+SZ"},
    "PLS": {"sections": ["resid", "ls"], "sz": False, "feats": "RLS"},
    "PSYM": {"sections": ["resid", "bilat", "graph"], "sz": False, "feats": "RSYM"},
}
SCAP = 3.0


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def sz_usable(name):
    """SATzilla outputs that are inputs: no timing outputs, no 'solved' flag."""
    n = name.lower()
    return "time" not in n and n != "sz_solved"


def features(pkg, obs6, sz):
    f6 = (obs6 or {}).get("features") or {}
    kind = PACKAGES[pkg]["feats"]
    if kind == "RLS":
        return {k: _f(f6.get(k)) for k in RLS}
    if kind == "RSYM":
        return {k: _f(f6.get(k)) for k in RSYM}
    out = dict(twlib.static_features(f6)) if f6 else {k: None for k in S28}
    if kind == "S28+LS6":
        out.update({k: _f(v) for k, v in f6.items() if k.startswith("l6_")})
    elif kind == "S28+SZ":
        out.update({k: _f(v) for k, v in ((sz or {}).get("features") or {}).items() if sz_usable(k)})
    return out


def observation_ok(pkg, obs6, sz):
    """All needed tool parts completed (else the wrapper keeps D)."""
    secs = (obs6 or {}).get("sections") or {}
    need = ["parse", "s28"] + PACKAGES[pkg]["sections"]
    if not all((secs.get(s) or {}).get("status") == "ok" for s in need):
        return False
    if PACKAGES[pkg]["sz"] and (sz or {}).get("status") != "ok":
        return False
    return True


def static_cpu(pkg, obs6, sz):
    """CPU of the package's tool runs (obsprofile6 with its sections, plus SATzilla)."""
    c = v5lib.static_cost(obs6, PACKAGES[pkg]["sections"]) if obs6 else 0.0
    if PACKAGES[pkg]["sz"]:
        c += (sz or {}).get("cpu", 0.0)
    return c


def run_obs6(cnf, sections, cap, workdir, mem_mb=16000):
    os.makedirs(workdir, exist_ok=True)
    secs = ["s28"] + [s for s in sections if s != "s28"]
    caps = ",".join(f"{k}:{v}" for k, v in SECTION_CAPS6.items())
    cmd = [OBS6, f"--sections={','.join(secs)}", f"--cap={cap}", f"--seccap={caps}", f"--seed={SEED}",
           f"--ls-flips={LS_FLIPS}", cnf]
    so, se = os.path.join(workdir, "obs6.json"), os.path.join(workdir, "obs6.err")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    r = twlib.run_budget(cmd, env, cap + 5.0, mem_mb, so, se)
    out = {"cpu": r["cpu"], "exit_code": r["exit_code"], "terminated_by": r["terminated_by"]}
    try:
        d = json.load(open(so))
        out.update(sections=d["sections"], features=d["features"], meta=d.get("meta"))
    except (OSError, ValueError, KeyError):
        out.update(sections={}, features={})
    return out


# ------------------------------------------------------------- inference

def _sigmoid(z):
    return 1.0 / (1.0 + math.exp(-z)) if z > -700 else 0.0


def gains(reader, feats, h):
    """Predicted gains {Fp, Fm} over D after the same observation (h = its CPU)."""
    kind = reader["kind"]
    z = v5lib.transform(reader["pre"], feats)
    if kind in ("ridge", "tree", "forest"):
        return v5lib.predict_gain(reader, z)
    if kind == "m05":
        par2 = {}
        for a in ("D", "Fp", "Fm"):
            m = reader["models"][a]
            p = m["p_const"] if m["p_const"] is not None else \
                _sigmoid(m["p_intercept"] + sum(w * x for w, x in zip(m["p_coef"], z)))
            t = math.exp(m["t_intercept"] + sum(w * x for w, x in zip(m["t_coef"], z))) * m["t_smear"] - 1.0
            t = max(0.0, t)
            par2[a] = p * (h + t) + (1 - p) * PAR2
        return {"Fp": par2["D"] - par2["Fp"], "Fm": par2["D"] - par2["Fm"]}
    if kind == "rule":
        out = {}
        for a in ("Fp", "Fm"):
            leaf = v5lib.tree_value(reader["models"][a]["root"], z)
            out[a] = leaf["mean"] if leaf["allowed"] else -1e18
        return out
    raise ValueError(kind)


def decide(reader, feats, h):
    g = gains(reader, feats, h)
    best = max(("Fp", "Fm"), key=lambda a: (g[a], a == "Fp"))
    th = reader["theta"]
    return (best if th is not None and g[best] > th else "D"), g
