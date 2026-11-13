"""Analyses for the week of 2026-11-16 (all on the 4719-instance Anniversary 2022 cohort, 600 CPU s, PAR-2 = 1200).

  PY tools/anni2022_week_analysis.py baseline --data DATA --gbd-base BASE --gbd-meta META --inputs inputs_mu --out OUT
  PY tools/anni2022_week_analysis.py unitunique ...   (descriptive unit / unique-literal statistics)
  PY tools/anni2022_week_analysis.py probe ...        (level hypothesis, simple rules, learned dynamic selectors)
  PY tools/anni2022_week_analysis.py family ...       (per-family and family-balanced evaluation)
Each subcommand writes OUT/<name>.json and prints a compact summary. Shared scoring: a policy's per-instance cost is
its fees (feature extraction, model queries, probes) plus the T600 time of the mode it runs, solved iff <= 600 s.
"""
import argparse
import csv
import glob
import json
import math
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anni2022_selector as S  # noqa: E402

MODES = ("D", "Fplus", "Fminus")
BUDGET = 600.0


# ----------------------------------------------------------------------------------------------------------------- data
class Data:
    def __init__(self, a):
        self.a = a
        rows = sorted(S.read_csv(Path(a.data) / "cluster_v3_analysis/matrix.csv"), key=lambda r: r["instance_key"])
        self.keys = [r["instance_key"] for r in rows]; self.n = len(self.keys); self.index = {k: i for i, k in enumerate(self.keys)}
        self.time = np.array([[float(r[m + "_cpu_s"]) for m in MODES] for r in rows])
        self.ok = np.array([[r[m + "_status"] in ("SAT", "UNSAT") for m in MODES] for r in rows])
        self.cost = np.array([[float(r[m + "_par2"]) for m in MODES] for r in rows])
        self.answer = [next((r[m + "_status"] for m in MODES if r[m + "_status"] in ("SAT", "UNSAT")), "none") for r in rows]
        with sqlite3.connect(f"file:{a.gbd_meta}?mode=ro", uri=True) as db:
            fam = {h: f for h, f in db.execute("select hash, family from features")}
        self.family = np.array([fam.get(k) or "unknown" for k in self.keys])
        self.x42, self.valid42 = S.linear42(self.keys, a.gbd_base)
        self.folds, self.inner = S.folds_and_inner(self.keys, a.inputs)
        self.extract = {}
        for f in glob.glob(str(Path(a.data) / "week20261116/features/features-*.jsonl")):
            for line in open(f):
                r = json.loads(line); self.extract[r["instance_key"]] = r
        self.flargest = {}
        for f in glob.glob(str(Path(a.data) / "week20261116/flargest/results/flargest-*.json")):
            r = json.loads(open(f).read()); self.flargest[r["instance_key"]] = r

    def flargest_arrays(self):
        if len(self.flargest) < self.n: return None
        t = np.array([self.flargest[k]["cpu_s"] for k in self.keys]); ok = np.array([self.flargest[k]["solved"] for k in self.keys])
        return t, ok


def policy(name, d, cost, total_cpu, extra=None):
    """Summary of per-instance PAR-2 costs `cost` and actually consumed CPU `total_cpu`."""
    D = d.cost[:, 0]
    out = {"policy": name, "solved": int((cost < 2 * BUDGET).sum()), "mean_PAR2": float(cost.mean()),
           "gain_vs_D_pct": 100 * float(D.sum() - cost.sum()) / float(D.sum()), "total_CPU_h": float(total_cpu.sum() / 3600),
           "rescued_vs_D": int(((D == 2 * BUDGET) & (cost < 2 * BUDGET)).sum()), "lost_vs_D": int(((D < 2 * BUDGET) & (cost == 2 * BUDGET)).sum())}
    if extra: out.update(extra)
    return out


def compose_static(d, action, fees_ok, fee):
    """Cost when the policy runs mode `action` after paying `fee` (PAR-2 and CPU actually consumed)."""
    t = d.time[np.arange(d.n), action]; ok = d.ok[np.arange(d.n), action]
    end = fee + t
    cost = np.where(ok & (end <= BUDGET), end, 2 * BUDGET)
    cpu = np.minimum(end, BUDGET)
    return cost, cpu


# ------------------------------------------------------------------------------------------------------------ features
UNIQUE = ("uniq_frac", "uniq_pos_share", "uniq_mean_len", "log_uniq_count", "uniq_allpos_frac", "uniq_allneg_frac", "lit_once_frac")
UNIT = ("unit_frac", "unit_pos_share", "unit_per_var", "log_unit_count")


def unit_unique_matrix(d):
    rows, ok, fee = [], np.zeros(d.n, bool), np.zeros(d.n)
    for i, k in enumerate(d.keys):
        r = d.extract.get(k, {}); u = r.get("unit_unique")
        fee[i] = r.get("uu_cpu_s", 0.0)
        if not u:
            rows.append([0.0] * (len(UNIQUE) + len(UNIT))); continue
        ok[i] = True; uc = max(u["uniq_count"], 1)
        feats = {"uniq_frac": u["uniq_frac"], "uniq_pos_share": u["uniq_pos_share"], "uniq_mean_len": u["uniq_mean_len"],
                 "log_uniq_count": math.log1p(u["uniq_count"]), "uniq_allpos_frac": u["uniq_allpos"] / uc,
                 "uniq_allneg_frac": u["uniq_allneg"] / uc, "lit_once_frac": u["lit_once_frac"], "unit_frac": u["unit_frac"],
                 "unit_pos_share": u["unit_pos_share"], "unit_per_var": u["unit_per_var"], "log_unit_count": math.log1p(u["unit_count"])}
        rows.append([feats[f] for f in UNIQUE + UNIT])
    return np.array(rows), ok, fee


def native_fees(d):
    ok = np.array([bool(d.extract.get(k, {}).get("native_ok")) for k in d.keys])
    fee = np.array([d.extract.get(k, {}).get("native_cpu_s", 0.0) for k in d.keys])
    return ok, fee


# ------------------------------------------------------------------------------------------------------------ baseline
def static_policy(d, x, valid, acq_ok, acq_fee, name, time_queries=True, folds=None, inner=None):
    """Re-implemented mean3 selector with cluster-measured fees; failed acquisition pays its CPU and runs D."""
    usable = valid & acq_ok
    folds = d.folds if folds is None else folds; inner = d.inner if inner is None else inner
    action, query, cuts = S.cross_validate(x, usable, d.cost, folds, inner, time_queries=time_queries)
    fee = acq_fee + np.where(usable, query, 0.0)
    cost, cpu = compose_static(d, action, usable, fee)
    free_cost = np.where(d.ok[np.arange(d.n), action], d.time[np.arange(d.n), action], 2 * BUDGET)
    s = policy(name, d, cost, cpu, {"actions": {m: int((action == i).sum()) for i, m in enumerate(MODES)},
                                    "acquisition_failures_run_D": int((~usable).sum()), "mean_fee_s": float(fee.mean()),
                                    "free_feature_gain_vs_D_pct": 100 * float(d.cost[:, 0].sum() - free_cost.sum()) / float(d.cost[:, 0].sum()),
                                    "cuts": cuts})
    s["_query"] = query
    return s, action, cost


def cmd_baseline(a):
    d = Data(a); out = {"parents": d.n, "policies": []}
    for j, m in enumerate(MODES):
        out["policies"].append(policy(m, d, d.cost[:, j], np.minimum(d.time[:, j], BUDGET)))
    vbs = d.cost.min(axis=1); best = d.cost.argmin(axis=1)
    out["policies"].append(policy("VBS {D,F+,F-} (free oracle)", d, vbs, np.minimum(d.time[np.arange(d.n), best], BUDGET)))
    r54 = {r["instance_key"]: r for r in S.read_csv(Path(a.inputs) / "R54_predictions.csv")}
    c54 = np.array([float(r54[k]["mean3_PAR2"]) for k in d.keys])
    a54 = np.array([MODES.index(r54[k]["mean3_action"]) for k in d.keys])
    fee54 = np.array([float(r54[k]["mean3_native_CPU_s"]) + float(r54[k]["mean3_query_CPU_s"]) for k in d.keys])
    out["policies"].append(policy("static selector R54 mean3 (Mu's OOF predictions, Mac feature/query fees)", d, c54,
                                  np.minimum(fee54 + d.time[np.arange(d.n), a54], BUDGET)))
    acq_ok, acq_fee = native_fees(d)
    s, action, cost = static_policy(d, d.x42, d.valid42, acq_ok, acq_fee, "static selector, re-implemented, cluster fees")
    s["native_acquisition"] = {"ok": int(acq_ok.sum()), "failed": int((~acq_ok).sum()), "mean_cpu_s": float(acq_fee.mean()),
                               "retried": int(sum(len(d.extract.get(k, {}).get("native_attempts", [])) > 1 for k in d.keys))}
    out["policies"].append(s)
    np.save(Path(a.out) / "static_actions.npy", action); np.save(Path(a.out) / "static_query_fee.npy", s.pop("_query"))
    save_costs(a, "static_cluster", cost); save_costs(a, "static_R54_mac", c54)
    fl = d.flargest_arrays()
    if fl:
        t, ok = fl; c = np.where(ok, t, 2 * BUDGET)
        out["policies"].append(policy("F-largest (per-variable majority sign)", d, c, np.minimum(t, BUDGET)))
        save_costs(a, "flargest", c)
        c4 = np.minimum(vbs, c)
        out["policies"].append(policy("VBS {D,F+,F-,F-largest} (free oracle)", d, c4, np.minimum(np.where(c <= vbs, t, d.time[np.arange(d.n), best]), BUDGET)))
        out["flargest_vs_D"] = {"only_flargest_solved": int((ok & ~d.ok[:, 0]).sum()), "only_D_solved": int((~ok & d.ok[:, 0]).sum()),
                                "both_solved": int((ok & d.ok[:, 0]).sum()),
                                "flargest_2x_faster": int((ok & d.ok[:, 0] & (2 * t <= d.time[:, 0]) & (d.time[:, 0] >= 1)).sum()),
                                "D_2x_faster": int((ok & d.ok[:, 0] & (2 * d.time[:, 0] <= t) & (t >= 1)).sum()),
                                "majority_counts": summarize_majority(d)}
    write(a, "baseline", out)
    for p in out["policies"]:
        print(f"{p['policy'][:70]:70s} solved {p['solved']:5d}  PAR2 {p['mean_PAR2']:7.2f}  gain {p['gain_vs_D_pct']:6.2f}%  CPU-h {p['total_CPU_h']:7.1f}")


def summarize_majority(d):
    vals = [d.flargest[k].get("flargest") or {} for k in d.keys]
    tot = [v.get("positive", 0) + v.get("negative", 0) + v.get("ties_positive", 0) for v in vals]
    return {"median_positive_share": float(np.median([v.get("positive", 0) / t for v, t in zip(vals, tot) if t])),
            "median_negative_share": float(np.median([v.get("negative", 0) / t for v, t in zip(vals, tot) if t])),
            "median_tie_share": float(np.median([v.get("ties_positive", 0) / t for v, t in zip(vals, tot) if t]))}


# ---------------------------------------------------------------------------------------------------------- unit/unique
def spearman(x, y):
    from scipy.stats import spearmanr
    if len(x) < 10: return None
    r = spearmanr(x, y); return {"rho": float(r.statistic), "p": float(r.pvalue), "n": int(len(x))}


def cmd_unitunique(a):
    d = Data(a); X, ok, uu_fee = unit_unique_matrix(d); names = UNIQUE + UNIT
    U = {k: d.extract[k]["unit_unique"] for k in d.keys if d.extract.get(k, {}).get("unit_unique")}
    has_unit = np.array([U.get(k, {}).get("unit_count", 0) > 0 for k in d.keys]); has_uniq = np.array([U.get(k, {}).get("uniq_count", 0) > 0 for k in d.keys])
    unit_total = sum(U[k]["unit_count"] for k in U); uniq_total = sum(U[k]["uniq_count"] for k in U); both = sum(U[k]["uniq_units"] for k in U)
    out = {"extracted": int(ok.sum()), "failed": int((~ok).sum()), "uu_cpu_s": {"mean": float(uu_fee[ok].mean()), "p99": float(np.quantile(uu_fee[ok], .99)), "total_h": float(uu_fee.sum() / 3600)},
           "instances_with_unit": int(has_unit.sum()), "instances_with_unique": int(has_uniq.sum()), "instances_with_both": int((has_unit & has_uniq).sum()),
           "clauses": {"unit_total": unit_total, "unique_total": uniq_total, "unit_and_unique": both,
                       "share_of_units_that_are_unique": both / max(unit_total, 1), "share_of_unique_that_are_units": both / max(uniq_total, 1)},
           "medians_all": {n: float(np.median(X[ok, j])) for j, n in enumerate(names)}}
    # relation to forced-phase gains: groups by which mode is best (2x and 1 s rule) and rank correlation on both-solved
    t, okm = d.time, d.ok
    def better(i, j):  # mode i clearly better than mode j
        return okm[:, i] & (~okm[:, j] | ((2 * t[:, i] <= t[:, j]) & (t[:, j] >= 1)))
    groups = {"F+ better than D": better(1, 0), "F- better than D": better(2, 0), "D better than both F": better(0, 1) & better(0, 2),
              "no clear difference": ~(better(1, 0) | better(2, 0) | better(0, 1) | better(0, 2))}
    out["group_sizes"] = {g: int((m & ok).sum()) for g, m in groups.items()}
    out["group_medians"] = {g: {n: float(np.median(X[m & ok, j])) if (m & ok).any() else None for j, n in enumerate(names)} for g, m in groups.items()}
    out["group_share_with_unit"] = {g: float(has_unit[m & ok].mean()) for g, m in groups.items() if (m & ok).any()}
    out["group_share_with_unique"] = {g: float(has_uniq[m & ok].mean()) for g, m in groups.items() if (m & ok).any()}
    corr = {}
    for fi, fname in ((1, "log(T_F+/T_D)"), (2, "log(T_F-/T_D)")):
        m = ok & okm[:, 0] & okm[:, fi] & (np.maximum(t[:, 0], t[:, fi]) >= 1)
        y = np.log(t[m, fi] / t[m, 0])
        corr[fname] = {n: spearman(X[m, j], y) for j, n in enumerate(names)}
    m = ok & okm[:, 1] & okm[:, 2] & (np.maximum(t[:, 1], t[:, 2]) >= 1)
    corr["log(T_F+/T_F-)"] = {n: spearman(X[m, j], np.log(t[m, 1] / t[m, 2])) for j, n in enumerate(names)}
    out["spearman_vs_log_time_ratio"] = corr
    # selector ablation: same recipe, same folds; fees add the unit/unique extractor CPU when its features are used
    acq_ok, acq_fee = native_fees(d)
    sets = {"base42": (d.x42, np.zeros(d.n)), "base42+unique": (np.c_[d.x42, X[:, :len(UNIQUE)]], uu_fee),
            "base42+unit": (np.c_[d.x42, X[:, len(UNIQUE):]], uu_fee), "base42+unique+unit": (np.c_[d.x42, X], uu_fee)}
    out["ablation"] = []
    for name, (x, extra_fee) in sets.items():
        valid = d.valid42 & (ok if name != "base42" else True)
        s, _, c = static_policy(d, x, valid, acq_ok, acq_fee + extra_fee, name, time_queries=True)
        s.pop("_query", None); out["ablation"].append(s); save_costs(a, f"ablation_{name}", c)
        print(f"{name:20s} solved {s['solved']} gain {s['gain_vs_D_pct']:.3f}% free {s['free_feature_gain_vs_D_pct']:.3f}%", flush=True)
    write(a, "unitunique", out)


def write(a, name, obj):
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / f"{name}.json").write_text(json.dumps(obj, indent=1, default=float))


def save_costs(a, name, cost):
    (Path(a.out) / "costs").mkdir(parents=True, exist_ok=True)
    np.save(Path(a.out) / "costs" / f"{name}.npy", cost)


# --------------------------------------------------------------------------------------------------------------- probes
import anni2022_probe_lib as P  # noqa: E402

# single-statistic rules: (feature, direction); 'min' picks the mode with the smallest value. level first: the
# hypothesis under test is 'lower level -> better mode'.
RULES = [("level_ema", "min"), ("conflict_level_mean", "min"), ("backtrack_level_mean", "min"), ("jump_mean", "max"),
         ("jump_ema", "max"), ("trail_slow", "min"), ("glue_slow", "min"), ("size_ema", "min"),
         ("conflicts_per_s", "max"), ("decisions_per_s", "max"), ("propagations_per_s", "max"), ("fixed", "max"),
         ("decisions_per_conflict", "min"), ("learned_lits_per_cls", "min"), ("active", "min")]
DYN = ("conflicts", "decisions", "propagations", "restarts", "fixed", "active", "redundant", "level_ema", "jump_ema",
       "trail_fast", "trail_slow", "glue_fast", "glue_slow", "size_ema", "decision_rate_ema", "conflict_level_mean",
       "backtrack_level_mean", "jump_mean", "conflicts_per_s", "decisions_per_s", "propagations_per_s",
       "decisions_per_conflict", "propagations_per_decision", "learned_lits_per_cls", "stable")
LOGGED = {"conflicts", "decisions", "propagations", "restarts", "fixed", "active", "redundant", "conflicts_per_s",
          "decisions_per_s", "propagations_per_s"}


def probe_setup(d, probes, w, semantics):
    """Per-instance probe outcome and the cost matrix of choosing each mode afterwards."""
    solved_p = np.zeros(d.n, bool); probe_cost = np.zeros(d.n); feats = []
    choice_cost = np.zeros((d.n, 3)); choice_cpu = np.zeros((d.n, 3))
    paid = (2 if semantics == "continue" else 3) * w
    for i, k in enumerate(d.keys):
        s, c, _ = P.probe_phase(probes[k], w); solved_p[i] = s; probe_cost[i] = c
        feats.append(P.features(probes[k], w))
        for j in range(3):
            end = paid + d.time[i, j]
            choice_cost[i, j] = c if s else (end if d.ok[i, j] and end <= BUDGET else 2 * BUDGET)
            choice_cpu[i, j] = c if s else min(end, BUDGET)
    return solved_p, probe_cost, feats, choice_cost, choice_cpu


def dyn_matrix(feats):
    rows, ok = [], []
    for f in feats:
        if any(f[m] is None for m in MODES):
            rows.append([0.0] * (3 * len(DYN) + 2 * len(DYN))); ok.append(False); continue
        v = []
        for m in MODES:
            v += [math.log1p(max(f[m][k], 0)) if k in LOGGED else f[m][k] for k in DYN]
        for m in ("Fplus", "Fminus"):  # relative to D, the reference mode
            v += [(math.log1p(max(f[m][k], 0)) - math.log1p(max(f["D"][k], 0))) if k in LOGGED else f[m][k] - f["D"][k] for k in DYN]
        rows.append(v); ok.append(True)
    return np.array(rows), np.array(ok)


def rule_actions(feats, feature, direction):
    act = np.zeros(len(feats), dtype=int); usable = np.zeros(len(feats), bool)
    for i, f in enumerate(feats):
        if any(f[m] is None for m in MODES): continue
        vals = np.array([f[m][feature] for m in MODES]); usable[i] = True
        act[i] = int(np.argmin(vals) if direction == "min" else np.argmax(vals))   # ties keep the first, i.e. D
    return act, usable


def margin_rule_cv(d, feats, feature, cc, folds, inner, eligible):
    """'Use the forced mode with the lowest <feature> only if it is below D's by more than a margin' with the margin
    (relative, from a fixed grid) chosen on inner-validation parents of each outer fold."""
    grid = (0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, math.inf)  # inf = never switch
    vals = np.full((d.n, 3), np.nan)
    for i, f in enumerate(feats):
        if eligible[i] and all(f[m] is not None for m in MODES): vals[i] = [f[m][feature] for m in MODES]
    have = np.isfinite(vals).all(axis=1)

    def act_for(mask, margin):
        a = np.zeros(d.n, dtype=int)
        j = 1 + np.nanargmin(np.where(have[:, None], vals[:, 1:], np.inf), axis=1)
        rel = (vals[np.arange(d.n), j] - vals[:, 0]) / np.maximum(np.abs(vals[:, 0]), 1e-9)
        a[mask & have & (rel < -margin)] = j[mask & have & (rel < -margin)]
        return a
    action = np.zeros(d.n, dtype=int); chosen = []
    for fold in range(int(folds.max()) + 1):
        held = folds == fold; val = ~held & inner & eligible
        best = min(grid, key=lambda g: cc[np.arange(d.n), act_for(val, g)][val].sum())
        chosen.append(best); a = act_for(held & eligible, best); action[held] = a[held]
    return action, chosen


def cmd_probe(a):
    d = Data(a); probes = P.load_probes(Path(a.data) / "week20261116/probe5", d.keys)
    missing = [k for k in d.keys if len(probes[k]) < 3]
    if missing: raise SystemExit(f"{len(missing)} instances lack probe results")
    out = {"windows": {}}; D = d.cost[:, 0]
    for w in P.WINDOWS:
        for sem in ("continue", "restart"):
            tag = f"w{w:g}_{sem}"
            solved_p, pcost, feats, cc, ccpu = probe_setup(d, probes, w, sem)
            elig = ~solved_p
            res = {"solved_in_probe": int(solved_p.sum()), "no_telemetry_fallback_D": int(sum(any(f[m] is None for m in MODES) for f, e in zip(feats, elig) if e)),
                   "policies": []}
            def add(name, act, extra=None):
                c = cc[np.arange(d.n), act]; cpu = ccpu[np.arange(d.n), act]
                res["policies"].append(policy(name, d, c, cpu, {"actions_on_unsolved": {m: int(((act == j) & elig).sum()) for j, m in enumerate(MODES)}, **(extra or {})}))
                if w == 2.0:
                    save_costs(a, f"probe_{tag}_{name.split(' ')[0]}", c)
                    (Path(a.out) / "actions").mkdir(exist_ok=True)
                    np.save(Path(a.out) / "actions" / f"probe_{tag}_{name.split(' ')[0]}.npy", act)
                return c
            add("probe+D (always D after probing)", np.zeros(d.n, dtype=int))
            add("probe+oracle (best mode after probing; upper bound)", cc.argmin(axis=1))
            for feat, direction in RULES:
                act, usable = rule_actions(feats, feat, direction); act[~elig] = 0
                add(f"rule:{direction}_{feat}", act)
            for feat in ("level_ema", "conflict_level_mean", "backtrack_level_mean"):
                act, margins = margin_rule_cv(d, feats, feat, cc, d.folds, d.inner, elig)
                add(f"rule:{feat}_below_D_by_cv_margin", act, {"margins_by_fold": margins})
            X, okx = dyn_matrix(feats); usable = okx & elig
            for name, x in (("learned:dynamic", X), ("learned:dynamic+static42", np.c_[X, d.x42])):
                v = usable & (d.valid42 if "static" in name else True)
                act, query, cuts = S.cross_validate(x, v, cc, d.folds, d.inner, time_queries=False)
                add(name, act, {"cuts": cuts})
            out["windows"][tag] = res
            best = sorted(res["policies"], key=lambda p: p["mean_PAR2"])[:4]
            print(tag, "probe-solved", res["solved_in_probe"], "|", "; ".join(f"{p['policy'][:40]} {p['gain_vs_D_pct']:.2f}%" for p in best), flush=True)
    out["level_hypothesis"] = level_hypothesis(d, probes)
    write(a, "probe", out)


def level_hypothesis(d, probes):
    """Does a lower early level go with a better final result? Tested on instances unsolved by all probes."""
    res = {}
    for w in P.WINDOWS:
        rows = []
        for i, k in enumerate(d.keys):
            if P.probe_phase(probes[k], w)[0]: continue
            f = P.features(probes[k], w)
            if any(f[m] is None for m in MODES): continue
            h = P.features(probes[k], w / 2)
            rows.append((i, [f[m]["level_ema"] for m in MODES], [f[m]["conflict_level_mean"] for m in MODES],
                         [None if h[m] is None else f[m]["level_ema"] - h[m]["level_ema"] for m in MODES]))
        idx = np.array([r[0] for r in rows]); lev = np.array([r[1] for r in rows]); clev = np.array([r[2] for r in rows])
        cost = d.cost[idx]; best = cost.argmin(axis=1); distinct = np.ptp(cost, axis=1) > 0
        out = {"instances": int(len(idx)), "with_a_strictly_better_mode": int(distinct.sum())}
        for name, v in (("level_ema", lev), ("conflict_level_mean", clev)):
            low = v.argmin(axis=1)
            out[name] = {"lowest_is_best_share": float((low == best)[distinct].mean()),
                         "D_is_best_share": float((best == 0)[distinct].mean()),
                         "lowest_mode_counts": {m: int((low == j).sum()) for j, m in enumerate(MODES)}}
            for j, m in ((1, "F+"), (2, "F-")):
                both = np.ptp(cost[:, [0, j]], axis=1) > 0
                rel = (v[both, j] - v[both, 0]) / np.maximum(np.abs(v[both, 0]), 1e-9)
                y = np.log(cost[both, j] / cost[both, 0])
                lower_level = v[both, j] < v[both, 0]; lower_cost = cost[both, j] < cost[both, 0]
                out[name][f"{m}_vs_D"] = {"pairs": int(both.sum()), "spearman_rel_level_vs_log_cost_ratio": spearman(rel, y),
                                          "concordance_lower_level_and_lower_cost": float((lower_level == lower_cost).mean()),
                                          "P(F better | F level lower)": float(lower_cost[lower_level].mean()) if lower_level.any() else None,
                                          "P(F better | F level not lower)": float(lower_cost[~lower_level].mean()) if (~lower_level).any() else None}
        res[f"w{w:g}"] = out
    return res


# --------------------------------------------------------------------------------------------------------------- switch
def round_robin_cost(t, ok, s):
    """Time-sliced portfolio on one core: D, F+, F- take turns for s CPU seconds each and every mode keeps its state
    (SIGSTOP/SIGCONT); the first mode to finish ends the instance. Returns (PAR-2 cost, CPU consumed)."""
    spent = [0.0, 0.0, 0.0]; total = 0.0
    while total < BUDGET:
        for j in range(3):
            if not ok[j] and spent[j] >= BUDGET: continue
            need = t[j] - spent[j] if ok[j] else math.inf
            step = min(s, need, BUDGET - total)
            spent[j] += step; total += step
            if ok[j] and spent[j] >= t[j] - 1e-9: return (total, total) if total <= BUDGET else (2 * BUDGET, BUDGET)
            if total >= BUDGET: break
    return 2 * BUDGET, BUDGET


def two_stage_cost(i, d, w, m1, m2, t2, solved_p, pcost):
    """Probes (continue), run m1; if unsolved after t2 CPU s of m1, continue m2 from its probe state."""
    if solved_p[i]: return pcost[i]
    t, ok = d.time[i], d.ok[i]; base = 2 * w             # the two probes not chosen first
    if ok[m1] and base + t[m1] <= min(BUDGET, base + t2): return base + t[m1]
    if m2 is None or t2 == math.inf: return 2 * BUDGET
    used = base + t2 - w                                    # m1 ran t2 in total (its first w is the probe), m2's probe w is in base
    end = used + t[m2]
    return end if ok[m2] and end <= BUDGET else 2 * BUDGET


def cmd_switch(a):
    d = Data(a); out = {"round_robin_continue": [], "two_stage": {}}
    for s in (1, 2, 5, 20, 60, 200):
        res = [round_robin_cost(d.time[i], d.ok[i], s) for i in range(d.n)]
        c = np.array([r[0] for r in res]); cpu = np.array([r[1] for r in res])
        out["round_robin_continue"].append(policy(f"round robin D/F+/F-, slice {s} s, continuation", d, c, cpu)); save_costs(a, f"switch_rr_{s}", c)
    probes = P.load_probes(Path(a.data) / "week20261116/probe5", d.keys); w = 2.0
    solved_p, pcost, feats, cc, ccpu = probe_setup(d, probes, w, "continue")
    X, okx = dyn_matrix(feats)
    act, _, cuts, sc = S.cross_validate(X, okx & ~solved_p, cc, d.folds, d.inner, time_queries=False, return_scores=True)
    scores3 = np.c_[np.zeros(d.n), sc]                      # D is the reference with score 0
    second = np.array([int(np.argsort(-scores3[i])[1]) if act[i] == int(np.argmax(scores3[i])) else int(np.argmax(scores3[i])) for i in range(d.n)])
    usable = okx & ~solved_p
    grid = (10, 30, 60, 120, 300, math.inf)
    def costs_for(t2, idx):
        return np.array([two_stage_cost(i, d, w, act[i], second[i] if usable[i] else None, t2, solved_p, pcost) for i in idx])
    chosen, final = [], np.zeros(d.n)
    for fold in range(5):
        held = np.flatnonzero(d.folds == fold); val = np.flatnonzero((d.folds != fold) & d.inner)
        best = min(grid, key=lambda g: costs_for(g, val).sum()); chosen.append(best)
        final[held] = costs_for(best, held)
    cpu = np.minimum(final, BUDGET)
    out["two_stage"]["cv_switch_time"] = policy("probe 2 s, learned choice, switch to 2nd choice at CV-chosen time", d, final, cpu, {"switch_times_by_fold": [str(x) for x in chosen]})
    save_costs(a, "switch_two_stage_cv", final)
    for g in grid:
        c = costs_for(g, range(d.n))
        out["two_stage"][f"fixed_{g}"] = policy(f"two-stage, switch at {g} s (in-sample, no selection)", d, c, np.minimum(c, BUDGET))
    once = cc[np.arange(d.n), act]
    out["two_stage"]["choose_once_reference"] = policy("probe 2 s, learned choice, no switching", d, once, ccpu[np.arange(d.n), act])
    write(a, "switch", out)
    for p_ in out["round_robin_continue"] + list(out["two_stage"].values()):
        print(f"{p_['policy'][:70]:70s} solved {p_['solved']}  gain {p_['gain_vs_D_pct']:6.2f}%  {p_.get('switch_times_by_fold', '')}")


# ------------------------------------------------------------------------------------------------------------------ e2e
def cmd_e2e(a):
    """Real end-to-end pipelines vs replay on the stratified 500-instance sample."""
    root = Path(a.data) / "week20261116/e2e"; sample = json.loads((root / "sample.json").read_text())
    meta = {r["instance_key"]: r for r in sample["instances"]}
    rec = {}
    for f in sorted(root.glob("e2e-*.jsonl")):
        for line in f.open():
            r = json.loads(line)
            if "error" not in r: rec[r["instance_key"]] = r
    weight = {"switch": sample["switch_population"] / 250, "rest": sample["rest_population"] / 250}
    out = {"sample": len(meta), "completed": len(rec), "missing": sorted(set(meta) - set(rec))}
    for pipe in ("static", "probe"):
        rows = [(meta[k]["stratum"], r["replay"][pipe + "_PAR2"], r[pipe]["PAR2"], r[pipe]) for k, r in rec.items()]
        rep = np.array([x[1] for x in rows]); real = np.array([x[2] for x in rows]); wts = np.array([weight[x[0]] for x in rows])
        both = (rep < 1200) & (real < 1200); ratio = real[both] / np.maximum(rep[both], 1e-3)
        dis = [(k, x[1], x[2], x[3].get("status"), x[3].get("chosen", x[3].get("action")), x[3].get("solved_in_probe"))
               for k, x in zip(rec, rows) if (x[1] < 1200) != (x[2] < 1200)]
        out[pipe] = {"solved_agree": int(((rep < 1200) == (real < 1200)).sum()), "replay_solved": int((rep < 1200).sum()), "real_solved": int((real < 1200).sum()),
                     "real_over_replay_cost_both_solved": {"median": float(np.median(ratio)), "q10": float(np.quantile(ratio, .1)), "q90": float(np.quantile(ratio, .9))},
                     "sum_replay_PAR2": float(rep.sum()), "sum_real_PAR2": float(real.sum()),
                     "population_weighted_real_minus_replay_s": float((wts * (real - rep)).sum()),
                     "population_weighted_real_minus_replay_pct_of_D": None, "disagreements": dis[:20]}
    rows = sorted(S.read_csv(Path(a.data) / "cluster_v3_analysis/matrix.csv"), key=lambda r: r["instance_key"])
    dsum = sum(float(r["D_par2"]) for r in rows)
    for pipe in ("static", "probe"):
        out[pipe]["population_weighted_real_minus_replay_pct_of_D"] = 100 * out[pipe]["population_weighted_real_minus_replay_s"] / dsum
    write(a, "e2e", out)
    print(json.dumps({k: (v if k not in ("static", "probe") else {x: y for x, y in v.items() if x != "disagreements"}) for k, v in out.items() if k != "missing"}, indent=1))


# --------------------------------------------------------------------------------------------------------------- family
def cmd_family(a):
    d = Data(a); costs = {p.stem: np.load(p) for p in sorted((Path(a.out) / "costs").glob("*.npy"))}
    for j, m in enumerate(MODES): costs[m] = d.cost[:, j]
    costs["VBS3"] = d.cost.min(axis=1)
    fams, counts = np.unique(d.family, return_counts=True); D = d.cost[:, 0]
    out = {"families": int(len(fams)), "family_sizes": {f: int(c) for f, c in zip(fams, counts)}, "per_policy": {}}
    rng = np.random.default_rng(20261116)
    members = {f: np.flatnonzero(d.family == f) for f in fams}
    draws = [np.concatenate([rng.choice(members[f], size=min(5, len(members[f])), replace=False) for f in fams]) for _ in range(1000)]
    for name, c in costs.items():
        contrib = {f: float(D[m].sum() - c[m].sum()) for f, m in members.items()}
        total = sum(contrib.values())
        top = sorted(contrib.items(), key=lambda kv: -abs(kv[1]))[:8]
        bal = np.array([100 * (D[s].sum() - c[s].sum()) / D[s].sum() for s in draws])
        without_top = 100 * (total - top[0][1]) / (D.sum() - D[members[top[0][0]]].sum()) if top else None
        out["per_policy"][name] = {"overall_gain_pct": 100 * total / float(D.sum()),
                                   "families_better_than_D": int(sum(v > 1e-6 for v in contrib.values())),
                                   "families_worse_than_D": int(sum(v < -1e-6 for v in contrib.values())),
                                   "top_family_contributions_s": top, "gain_without_top_family_pct": without_top,
                                   "balanced_5_per_family_gain_pct": {"mean": float(bal.mean()), "q2.5": float(np.quantile(bal, .025)), "q97.5": float(np.quantile(bal, .975))}}
    # family-cluster bootstrap (resample families with replacement) for overall gains and paired differences
    fam_idx = [members[f] for f in fams]; B = 2000
    boot = rng.integers(0, len(fams), size=(B, len(fams)))
    fam_sum = lambda c: np.array([c[m].sum() for m in fam_idx])
    Ds = fam_sum(D); sums = {name: fam_sum(c) for name, c in costs.items()}
    def gain_ci(name, ref="D"):
        r = Ds if ref == "D" else sums[ref]
        g = np.array([100 * (r[b].sum() - sums[name][b].sum()) / Ds[b].sum() for b in boot])
        return {"point": float(100 * (r.sum() - sums[name].sum()) / Ds.sum()), "q2.5": float(np.quantile(g, .025)), "q97.5": float(np.quantile(g, .975))}
    for name in costs:
        out["per_policy"][name]["family_bootstrap_gain_ci"] = gain_ci(name)
    out["paired_vs_base42"] = {n: gain_ci(n, "ablation_base42") for n in costs if n.startswith("ablation_") and n != "ablation_base42"}
    out["paired_vs_static"] = {n: gain_ci(n, "static_cluster") for n in costs if n.startswith("probe_") or n == "flargest"}
    # family-grouped validation of the static selector: whole families held out, margin from other families
    order = sorted(fams, key=lambda f: (-len(members[f]), f))
    ffold = {f: i % 5 for i, f in enumerate(order)}; finner = {f: (i // 5) % 5 == 0 for i, f in enumerate(order)}
    folds = np.array([ffold[f] for f in d.family]); inner = np.array([finner[f] for f in d.family])
    acq_ok, acq_fee = native_fees(d)
    s, _, c = static_policy(d, d.x42, d.valid42, acq_ok, acq_fee, "static selector, family-grouped CV, cluster fees",
                            folds=folds, inner=inner); s.pop("_query", None)
    s["fold_families"] = {int(f): int(sum(1 for x in ffold.values() if x == f)) for f in range(5)}
    s["inner_families"] = int(sum(finner.values()))
    # the dynamic selector (w = 2, continuation) under the same family-grouped folds
    probes = P.load_probes(Path(a.data) / "week20261116/probe5", d.keys)
    solved_p, _, feats, cc, ccpu = probe_setup(d, probes, 2.0, "continue")
    X, okx = dyn_matrix(feats)
    act, _, cuts = S.cross_validate(X, okx & ~solved_p, cc, folds, inner, time_queries=False)
    out["dynamic_family_grouped_cv"] = policy("learned:dynamic w2 continue, family-grouped CV", d, cc[np.arange(d.n), act], ccpu[np.arange(d.n), act], {"cuts": cuts})
    out["static_family_grouped_cv"] = s
    write(a, "family", out)
    for name, v in out["per_policy"].items():
        b = v["balanced_5_per_family_gain_pct"]
        print(f"{name[:48]:48s} overall {v['overall_gain_pct']:6.2f}%  balanced {b['mean']:6.2f}% [{b['q2.5']:.2f},{b['q97.5']:.2f}]  better/worse families {v['families_better_than_D']}/{v['families_worse_than_D']}")
    print("family-grouped static:", s["gain_vs_D_pct"], s["solved"])


def main():
    p = argparse.ArgumentParser(); p.add_argument("cmd", choices=["baseline", "unitunique", "probe", "family", "switch", "e2e"])
    for x in ("--data", "--gbd-base", "--gbd-meta", "--inputs", "--out"): p.add_argument(x, required=True)
    a = p.parse_args(); Path(a.out).mkdir(parents=True, exist_ok=True)
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=4):
        {"baseline": cmd_baseline, "unitunique": cmd_unitunique, "probe": cmd_probe, "family": cmd_family, "switch": cmd_switch, "e2e": cmd_e2e}[a.cmd](a)


if __name__ == "__main__":
    main()
