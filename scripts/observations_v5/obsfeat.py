"""Feature definitions of goal v5 (docs/OBSERVATION_PROTOCOL_V5.md section 4).

Pure standard library; used by the offline analysis and by the deployed
wrapper, so both see identical features. Frozen before any feature-outcome
analysis (protocol section 4): definitions below are not changed after that.

  package_features(pkg, obs, arms, nvars) -> {name: value or None}

obs: an obsprofile record (v5lib.run_obsprofile) or None;
arms: {(tag, action): arm record (v5lib.run_arm)}.
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "three_way"))
import twlib  # noqa: E402

S28 = list(twlib.STATIC_FEATURES)
SECTION_PREFIXES = {
    "R01": ("a01_", "a02_", "a03_", "a04_", "a05_", "a07_", "a09_", "a10_", "a11_", "c01_", "c02_"),
    "R02": ("b01_", "b02_", "b03_", "b05_", "b07_", "b10_"),
    "R03": ("d01_", "d02_", "d03_", "d07_", "c04_"),
    "R04": ("d04_", "d05_", "d10_", "a12_"),
    "R09": ("g01_", "g02_", "g03_", "g04_", "g06_", "g_found"),
}
ARM_METRICS = ["started", "lconf", "ldec", "lprop", "cps_log", "dpc", "ppd_log", "fixed_frac", "units_pk",
               "bins_pk", "glue", "glue_low", "size", "trail", "best", "target", "stable", "rephased",
               "parse_frac", "search_frac", "answered"]
DIFF_METRICS = ["lconf", "ldec", "lprop", "cps_log", "dpc", "ppd_log", "fixed_frac", "units_pk", "bins_pk",
                "glue", "glue_low", "size", "trail", "best", "stable", "search_frac"]


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _ratio(a, b):
    a, b = _f(a), _f(b)
    return None if a is None or b in (None, 0.0) else a / b


def _log(x):
    x = _f(x)
    return None if x is None else math.log10(1.0 + max(0.0, x))


def _sub(a, b):
    return None if a is None or b is None else a - b


# ------------------------------------------------------------------ static

def s28(obs):
    if not obs or not obs.get("features"):
        return {k: None for k in S28}
    return twlib.static_features(obs["features"])


def section_features(obs, prefixes):
    f = (obs or {}).get("features") or {}
    return {k: _f(v) for k, v in f.items() if k.startswith(prefixes)}


def section_names(prefixes, example_obs):
    return sorted(k for k in ((example_obs or {}).get("features") or {}) if k.startswith(prefixes))


# ------------------------------------------------------------------- arms

def arm_metrics(arm, nvars):
    """Per-arm metrics; all None when the arm record is missing."""
    if arm is None:
        return {k: None for k in ARM_METRICS}
    st, fin, prof = arm.get("stats") or {}, arm.get("final") or {}, arm.get("profile") or {}
    ff = fin.get("f") or {}
    conf, dec, props = st.get("conflicts"), st.get("decisions"), st.get("propagations")
    cpu = arm.get("cpu")
    learned = fin.get("learned") or st.get("learned")
    started = 1.0 if (conf or 0) > 0 else 0.0
    m = {
        "started": started,
        "lconf": _log(conf or 0), "ldec": _log(dec or 0), "lprop": _log(props or 0),
        "cps_log": _log(_ratio(conf or 0, cpu)),
        "dpc": _ratio(dec, conf), "ppd_log": _log(_ratio(props, dec)),
        "fixed_frac": _ratio(fin.get("fixed", st.get("fixed")), nvars),
        "units_pk": None if not conf else 1000.0 * (fin.get("units") or 0) / conf if fin else None,
        "bins_pk": None if not conf else 1000.0 * (fin.get("binaries") or 0) / conf if fin else None,
        "glue": _ratio(fin.get("glue_sum"), learned) if fin else None,
        "glue_low": _ratio(fin.get("glue_low"), learned) if fin else None,
        "size": _ratio(fin.get("learn_lits"), learned) if fin else None,
        "trail": _f(ff.get("x_trail_frac")), "best": _f(ff.get("x_best_frac")),
        "target": _f(ff.get("x_target_frac")),
        "stable": _f(ff.get("c_stable_frac")),
        "rephased": _f(fin.get("rephased")) if fin else None,
        "parse_frac": _ratio(prof.get("parse"), cpu), "search_frac": _ratio(prof.get("search"), cpu),
        "answered": 1.0 if arm.get("answered") else 0.0,
    }
    if not started:  # no search yet: rate/quality metrics are not observed
        for k in ("dpc", "ppd_log", "units_pk", "bins_pk", "glue", "glue_low", "size", "trail", "best",
                  "target", "stable", "search_frac"):
            m[k] = None
    return m


def arms_block(tag, arms, nvars, actions=("D", "Fp", "Fm")):
    out, ms = {}, {}
    for a in actions:
        ms[a] = arm_metrics(arms.get((tag, a)), nvars)
        for k, v in ms[a].items():
            out[f"{tag}_{a}_{k}"] = v
        if tag == "ec":
            arm = arms.get((tag, a))
            st = (arm or {}).get("stats") or {}
            out[f"{tag}_{a}_cpu_log"] = None if arm is None else math.log10(max(1e-3, arm["cpu"]))
            out[f"{tag}_{a}_reached"] = None if arm is None else float((st.get("conflicts") or 0) >= 512)
    if len(actions) == 3:
        dm = DIFF_METRICS + (["cpu_log"] if tag == "ec" else [])
        for k in dm:
            g = (lambda a: out.get(f"{tag}_{a}_{k}"))
            out[f"{tag}_{k}_dFp"] = _sub(g("Fp"), g("D"))
            out[f"{tag}_{k}_dFm"] = _sub(g("Fm"), g("D"))
            out[f"{tag}_{k}_dPM"] = _sub(g("Fp"), g("Fm"))
    return out


def _half_delta(wins, key):
    xs = [_f(w.get(key)) for w in wins]
    xs = [x for x in xs if x is not None]
    if len(xs) < 4:
        return None
    h = len(xs) // 2
    return sum(xs[h:]) / len(xs[h:]) - sum(xs[:h]) / h


def f_block(arm, nvars):
    """R05: phase memory and trajectory of the 2 s D arm (obs telemetry)."""
    names = ["f01_flip_mean", "f01_flip_final", "f01_nwin_flip", "f03_dec_neg", "f03_prop_pos", "f03_root_pos",
             "f03_decpos_minus_proppos", "f04_disagree", "f04_target_set", "f04_target_neg", "f04_saved_neg",
             "f08_learn_pos", "f08_learn_minus_prop", "f10_chrono", "f10_glue_diff", "f10_lpos_diff",
             "f11_negdec_delta", "f11_glue_delta", "f11_trail_delta", "f11_best_delta", "f11_negdec_std",
             "f12_started", "f12_stable", "f12_rephased", "f12_has_target", "f12_nwin_log", "f12_elim_frac",
             "f12_subst_frac"]
    out = {k: None for k in names}
    if arm is None:
        return out
    fin = arm.get("final") or {}
    ff = fin.get("f") or {}
    wins = arm.get("windows") or []
    conf = (arm.get("stats") or {}).get("conflicts") or 0
    out["f12_started"] = 1.0 if conf > 0 else 0.0
    out["f12_nwin_log"] = _log(len(wins))
    if not fin:
        return out
    fl = [_f(w.get("x_saved_flip_frac")) for w in wins if (_f(w.get("x_flip_compared")) or 0) >= 32]
    fl = [x for x in fl if x is not None]
    out["f01_flip_mean"] = sum(fl) / len(fl) if fl else None
    out["f01_nwin_flip"] = float(len(fl))
    out["f01_flip_final"] = _f(ff.get("x_saved_flip_frac")) if (_f(ff.get("x_flip_compared")) or 0) >= 32 else None
    out["f03_dec_neg"] = _f(ff.get("c_neg_dec_frac"))
    out["f03_prop_pos"] = _f(ff.get("c_prop_pos_frac"))
    out["f03_root_pos"] = _f(ff.get("c_root_pos_frac"))
    if out["f03_dec_neg"] is not None and out["f03_prop_pos"] is not None:
        out["f03_decpos_minus_proppos"] = (1.0 - out["f03_dec_neg"]) - out["f03_prop_pos"]
    out["f04_disagree"] = _f(ff.get("x_saved_target_disagree"))
    out["f04_target_set"] = _f(ff.get("x_target_set_frac"))
    out["f04_target_neg"] = _f(ff.get("x_target_neg_frac"))
    out["f04_saved_neg"] = _f(ff.get("x_saved_neg_frac"))
    out["f08_learn_pos"] = _f(ff.get("c_learn_pos_frac"))
    out["f08_learn_minus_prop"] = _sub(out["f08_learn_pos"], out["f03_prop_pos"])
    out["f10_chrono"] = _f(ff.get("c_chrono_bt_frac"))
    out["f10_glue_diff"] = _sub(_f(ff.get("c_glue_chrono")), _f(ff.get("c_glue_nonchrono")))
    out["f10_lpos_diff"] = _sub(_f(ff.get("c_learn_pos_chrono")), _f(ff.get("c_learn_pos_nonchrono")))
    out["f11_negdec_delta"] = _half_delta(wins, "w_neg_dec_frac")
    out["f11_glue_delta"] = _half_delta(wins, "w_glue_mean")
    out["f11_trail_delta"] = _half_delta(wins, "x_trail_frac")
    out["f11_best_delta"] = _half_delta(wins, "x_best_frac")
    nd = [_f(w.get("w_neg_dec_frac")) for w in wins]
    nd = [x for x in nd if x is not None]
    if len(nd) >= 4:
        mu = sum(nd) / len(nd)
        out["f11_negdec_std"] = math.sqrt(sum((x - mu) ** 2 for x in nd) / len(nd))
    out["f12_stable"] = 1.0 if (fin.get("stabphases") or 0) > 0 else 0.0
    out["f12_rephased"] = 1.0 if (fin.get("rephased") or 0) > 0 else 0.0
    out["f12_has_target"] = 1.0 if (_f(ff.get("x_target_set_frac")) or 0) > 0 else 0.0
    out["f12_elim_frac"] = _ratio(fin.get("eliminated"), nvars)
    out["f12_subst_frac"] = _ratio(fin.get("substituted"), nvars)
    return out


# --------------------------------------------------------------- packages

def nvars_of(obs):
    f = (obs or {}).get("features") or {}
    return _f(f.get("vars"))


def package_features(pkg, obs, arms, stage=None):
    """Feature dict of a package. R11: stage 1 (static) or 2 (static + R06)."""
    nv = nvars_of(obs)
    out = dict(s28(obs))
    if pkg in SECTION_PREFIXES:
        out.update(section_features(obs, SECTION_PREFIXES[pkg]))
    elif pkg == "R05":
        out.update(f_block(arms.get(("fD", "D")), nv))
    elif pkg == "R06":
        out.update(arms_block("e02", arms, nv))
    elif pkg == "R07":
        out.update(arms_block("e05", arms, nv))
    elif pkg == "R08":
        out.update(arms_block("ec", arms, nv))
    elif pkg in ("R10", "R11"):
        out.update(section_features(obs, SECTION_PREFIXES["R01"] + SECTION_PREFIXES["R02"]))
        if pkg == "R10" or stage == 2:
            out.update(arms_block("e02", arms, nv))
    return out
