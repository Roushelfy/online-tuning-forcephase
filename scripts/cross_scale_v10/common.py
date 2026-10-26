"""Goal v10 shared definitions (docs/CROSS_SCALE_PROTOCOL_V10.md): actions, registered features, stop-time
probe parsing and the strategy decision. Used by the deployed wrapper and by the offline simulation, so a
decision computed offline from a MEASURE record and the one taken by the real wrapper go through the same code.
Standard library only.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts", "three_way"))
import twlib  # noqa: E402

ACTS = ("D", "Fp", "Fm")
ARGS = {"D": ["--phase=1", "--forcephase=0"], "Fp": ["--phase=1", "--forcephase=1"], "Fm": ["--phase=0", "--forcephase=1"]}
FORMAL = os.environ.get("FP_FORMAL_OVERRIDE") or os.path.join(ROOT, "build", "fpc", "cadical")  # override: tests only
STATIC_TOOL = os.environ.get("FP_STATIC_OVERRIDE") or os.path.join(ROOT, "build", "tools", "static10")
STATIC_CPU_CAP = 2.0       # CPU s for the static analyser (family A); over the cap -> static features missing
STATIC_WORK_CAP = 5e7      # literal visits of the graph section (tools/static10.c)

# ------------------------------------------------------------------ registered features

STATIC = ["st_log_vars", "st_log_clauses", "st_cv_ratio", "st_mean_len", "st_bin_frac", "st_long_frac", "st_pos_frac",
          "st_horn_frac", "st_antihorn_frac", "st_allneg_frac", "st_allpos_frac", "st_deg_log_mean", "st_deg_cv",
          "st_pol_imbalance", "st_pure_frac", "st_jw_pos", "st_lowdeg_frac", "st_bin_var_frac", "st_vig_deg_log",
          "st_vig_clust"]
ARM = ["conf_rate", "dec_per_conf", "props_per_dec", "learned_len", "glue", "trail", "remaining", "growth",
       "restart_rate"]
ARM_D_EXTRA = ["neg_dec"]
DIFF = ["conf_rate", "dec_per_conf", "props_per_dec", "learned_len", "glue", "trail", "growth"]
V9_OLD = ["s_log_vars", "s_log_clauses", "s_cv_ratio", "s_bin_frac", "s_pos_frac", "r_log_conflicts", "c_dec_per_conf",
          "c_props_per_dec", "c_glue_mean", "x_trail_frac", "x_best_frac", "x_saved_neg_frac"]
PREFIX = {"D": "pD_", "Fp": "pP_", "Fm": "pM_"}


def feature_set(family):
    """Registered feature list of a reader family: A static, B static + D prefix, B_v9 the v9 checkpoint baseline,
    C static + three arms + differences."""
    if family == "A":
        return list(STATIC)
    if family == "B":
        return STATIC + [PREFIX["D"] + f for f in ARM + ARM_D_EXTRA]
    if family == "B_v9":
        return ["v9_" + f for f in V9_OLD]
    if family == "C":
        out = STATIC + [PREFIX["D"] + f for f in ARM + ARM_D_EXTRA]
        out += [PREFIX[a] + f for a in ("Fp", "Fm") for f in ARM]
        out += ["dP_" + f for f in DIFF] + ["dM_" + f for f in DIFF]
        return out
    raise ValueError(family)


def arm_block(arm):
    """Features whose absence means the arm did not reach search (-> missing action)."""
    return [PREFIX[arm] + "conf_rate"]


# ------------------------------------------------------------------ stop-time parsing

def progress_lines(path):
    """(seconds, conflicts, glue, trail_pct, remaining_pct) of CaDiCaL's progress lines (17 columns after the flag:
    seconds MB level reductions restarts rate conflicts redundant size/glue size glue tier1 tier2 trail%
    irredundant variables remaining%)."""
    out = []
    try:
        with open(path, "rb") as f:
            for raw in f:
                if not raw.startswith(b"c ") or raw.startswith(b"c ---"):
                    continue
                toks = raw.decode("utf-8", "replace").split()
                if len(toks) != 19 or len(toks[1]) != 1 or not toks[15].endswith("%") or not toks[18].endswith("%"):
                    continue
                try:
                    out.append((float(toks[2]), int(toks[8]), float(toks[12]), float(toks[15][:-1]), float(toks[18][:-1])))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def _r(a, b):
    return None if a is None or b in (None, 0) else a / b


def _l(x):
    return None if x is None else math.log10(1.0 + max(0.0, x))


def arm_features(arm, out_path, tel_path, cpu):
    """Registered prefix features of one probe arm from what it wrote up to its stop: CaDiCaL's statistics block
    (printed on SIGTERM or at the end), the telemetry 'final' record and the progress lines. A probe that never
    reached search (no conflict) gives None for every feature (explicit missing)."""
    _, st, _ = twlib.parse_stats(out_path) if os.path.exists(out_path) else (None, {}, {})
    final, _ = twlib.parse_telemetry(tel_path)
    final = final or {}
    conf = st.get("conflicts") if st.get("conflicts") is not None else final.get("conflicts")
    dec = st.get("decisions") if st.get("decisions") is not None else final.get("decisions")
    props = st.get("propagations") if st.get("propagations") is not None else final.get("propagations")
    pl = progress_lines(out_path)
    f = {k: None for k in ARM + (ARM_D_EXTRA if arm == "D" else [])}
    if not conf:
        return f, {"conflicts": conf or 0, "decisions": dec, "progress_lines": len(pl)}
    f["conf_rate"] = _l(_r(conf, cpu))
    f["dec_per_conf"] = _r(dec, conf)
    f["props_per_dec"] = _l(_r(props, dec))
    f["learned_len"] = _r(st.get("learned_lits"), st.get("learned"))
    f["restart_rate"] = None if st.get("restarts") is None else 1000.0 * st["restarts"] / conf
    if pl:
        last = pl[-1]
        f["glue"], f["trail"], f["remaining"] = last[2], last[3] / 100.0, last[4] / 100.0
        t_stop = last[0]
        half = [p for p in pl if p[0] <= t_stop / 2.0]
        c_half = half[-1][1] if half else 0
        f["growth"] = math.log10((1.0 + conf) / (1.0 + c_half))
    if arm == "D":
        f["neg_dec"] = _r(final.get("dec_neg"), final.get("dec_free"))
    return f, {"conflicts": conf, "decisions": dec, "progress_lines": len(pl)}


def v9_checkpoint_features(tel_path):
    """v9's 12 content-gate inputs from the last telemetry checkpoint written before the stop (fixed old baseline)."""
    names, last = None, None
    try:
        with open(tel_path) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") == "header":
                    names = d.get("features")
                elif d.get("type") == "checkpoint" and isinstance(d.get("f"), (dict, list)):
                    last = d
    except OSError:
        return {"v9_" + k: None for k in V9_OLD}
    if last is None:
        return {"v9_" + k: None for k in V9_OLD}
    f = last["f"]
    x = dict(f) if isinstance(f, dict) else dict(zip(names or [], f))
    return {"v9_" + k: (x.get(k) if isinstance(x.get(k), (int, float)) and math.isfinite(x[k]) else None) for k in V9_OLD}


def combine(static, arms):
    """Flat feature dict from static features and {arm: arm feature dict}; adds the registered differences."""
    x = dict(static or {})
    for a, fa in arms.items():
        for k, v in fa.items():
            x[PREFIX[a] + k] = v
    for tag, a in (("dP_", "Fp"), ("dM_", "Fm")):
        if "D" in arms and a in arms:
            for k in DIFF:
                u, v = arms[a].get(k), arms["D"].get(k)
                x[tag + k] = None if u is None or v is None else u - v
    return x


# ------------------------------------------------------------------ decision

def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def decide(strategy, x, arms_started):
    """Action and path for an 'observe' strategy after all probes ran without an answer.
    x: flat feature dict; arms_started: {arm: bool}. Rules (protocol section 6):
      - no reader -> base action ('fallback');
      - a probe arm the reader needs did not reach search -> missing_action ('missing');
      - other missing features -> the training-fold median stored in the strategy ('impute');
      - ridge: predicted cost difference vs base per action; deviate only if the best is < -margin;
      - tree: the leaf's action (margin already applied when fitting)."""
    rd = strategy.get("reader")
    if not rd or rd.get("method") == "none":
        return strategy["base"], "fallback"
    for a in strategy.get("needs_arms", []):
        if not arms_started.get(a):
            return strategy["missing_action"], "missing"
    z = {}
    for f in strategy["features"]:
        z[f] = x.get(f) if _num(x.get(f)) else strategy["impute"][f]
    if rd["method"] == "tree":
        node = rd["tree"]
        while "leaf" not in node:
            node = node["left"] if z[node["feature"]] <= node["threshold"] else node["right"]
        return node["leaf"], "reader"
    pred = {}
    for a, m in rd["models"].items():
        pred[a] = m["intercept"] + sum(w * (z[f] - rd["mean"][f]) / rd["std"][f] for f, w in m["coef"].items())
    best = min(sorted(pred), key=lambda a: pred[a])
    return (best if pred[best] < -rd["margin"] else strategy["base"]), "reader"
