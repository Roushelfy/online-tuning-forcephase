"""Static cost-classifier selector: a compact re-implementation of Mu's R13b/R54 recipe plus feature ablations.

Recipe (score_static_cost_classifier.py in Mu's archive, commit 1384bea):
  * inputs: 42 statistics from GBD base features (base.db, SHA 15a3d19f, identical to Mu's), valid = all 57 raw
    fields finite and >= 0;
  * outer folds: R11 diagnostic_iso_fold (5); inner validation flags from splits.csv; train = not held, not inner,
    valid; validation = not held, inner, valid;
  * three ExtraTreesClassifier(256 trees, depth 12, min leaf 8, max_features 0.8, log_loss), random_state =
    20261111 / 12 / 13 + fold, trained on (parent, action) pairs weighted by (max cost - action cost) / 1200;
  * score = class-probability(F) - class-probability(D); mean3 averages the three models' scores;
  * one switching margin per fold, chosen on the inner validation parents among {0, quantiles 0..0.99 of max score}
    by total timed cost (fee 0.003 s), else D;
  * PAR2 of a choice = chosen action's T600 time + fees if <= 600 s, else 1200.

  PY tools/anni2022_selector.py reproduce --data DATA --gbd GBD_BASE --inputs inputs_mu --out OUT
  PY tools/anni2022_selector.py ablation  --data DATA --gbd GBD_BASE --inputs inputs_mu --features F.jsonl --out OUT
"""
import argparse
import csv
import json
import math
import sqlite3
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier
from threadpoolctl import threadpool_limits

ACTIONS = ("D", "Fplus", "Fminus")
SEEDS = (20261111, 20261112, 20261113)
QUANTILES = (0, .25, .5, .75, .9, .95, .99)
STAT = ("mean", "variance", "min", "max", "entropy")
PREFIXES = ("balancecls", "balancevars", "vcg_vdegree", "hornvars", "invhornvars", "vcg_cdegree", "vg_degree", "cg_degree")
FIELDS = ["variables", "clauses", *[f"cls{i}" for i in range(1, 10)], "cls10p", "positive", "negative", "horn", "invhorn",
          *[p + "_" + s for p in PREFIXES for s in STAT]]


def read_csv(p):
    with open(p, newline="") as f: return list(csv.DictReader(f))


def load(data):
    rows = sorted(read_csv(Path(data) / "cluster_v3_analysis/matrix.csv"), key=lambda r: r["instance_key"])
    keys = [r["instance_key"] for r in rows]
    costs = np.array([[float(r[a + "_par2"]) for a in ACTIONS] for r in rows])
    return keys, costs


def linear42(keys, gbd):
    with sqlite3.connect(f"file:{gbd}?mode=ro", uri=True) as db:
        got = {k: v for k, *v in db.execute("select hash," + ",".join(FIELDS) + " from features")}
    raw = np.array([got[k] for k in keys], dtype=float)
    valid = np.isfinite(raw).all(axis=1) & (raw >= 0).all(axis=1)
    s = np.where(np.isfinite(raw), np.maximum(raw, 0), 0)
    n, m = s[:, 0], s[:, 1]
    widths = s[:, 2:12] / np.maximum(m[:, None], 1)
    empty = np.maximum(0, 1 - widths.sum(axis=1))[:, None]
    basic = np.c_[np.log1p(n), np.log1p(m), empty, widths, s[:, 12:16] / np.maximum(m[:, None], 1), s[:, 16:26]]

    def deg(prefix):
        k = 16 + 5 * PREFIXES.index(prefix)
        mean, var, lo, hi, ent = s[:, k:k + 5].T
        return np.c_[np.log1p(mean), np.log1p(var / np.maximum(mean ** 2, 1e-12)), lo / np.maximum(mean, 1e-12),
                     np.log1p(hi / np.maximum(mean, 1e-12)), ent]
    return np.c_[basic, *[deg(p) for p in ("vcg_vdegree", "hornvars", "invhornvars")]], valid


def folds_and_inner(keys, inputs):
    fold = {r["instance_key"]: int(r["diagnostic_iso_fold"]) for r in read_csv(Path(inputs) / "R11_iso_folds.csv")}
    inner = {r["instance_key"]: r["inner_validation"] == "True" for r in read_csv(Path(inputs) / "splits.csv")}
    return np.array([fold[k] for k in keys]), np.array([inner[k] for k in keys])


def timed_cost(runtime, overhead, budget=600):
    end = runtime + overhead
    return np.where(end <= budget, end, 2 * budget)


def expanded_rewards(costs):
    w = (costs.max(axis=1, keepdims=True) - costs) / 1200
    parent, action = np.nonzero(w > 0)
    return parent, action, w[parent, action]


def fit(x, costs, seed):
    parent, action, weight = expanded_rewards(costs)
    if not len(parent): return None
    model = ExtraTreesClassifier(n_estimators=256, max_depth=12, min_samples_leaf=8, max_features=.8,
                                 criterion="log_loss", n_jobs=4, random_state=seed)
    model.fit(x[parent], action, sample_weight=weight); model.n_jobs = 1
    return model


def scores(model, x, k=3):
    """Class-probability of each non-D action minus that of D (k actions, D = action 0)."""
    if model is None: return np.zeros((len(x), k - 1))
    p = np.zeros((len(x), k)); p[:, model.classes_] = model.predict_proba(x)
    return p[:, 1:] - p[:, :1]


def measured(model, x, k=3):
    scores(model, x[:1], k); val = np.empty((len(x), k - 1)); fee = np.empty(len(x))
    for i in range(len(x)):
        t = time.process_time(); val[i] = scores(model, x[i:i + 1], k)[0]; fee[i] = time.process_time() - t
    return val, fee


def choose(g, cut):
    if cut is None: return np.zeros(len(g), dtype=int)
    best = g.argmax(axis=1)
    return np.where(g[np.arange(len(best)), best] > cut, best + 1, 0)


def calibrate(g, costs, fee):
    maxima = g.max(axis=1)
    cuts = np.unique(np.maximum(0, np.r_[0, np.quantile(maxima, QUANTILES)]))
    best_cut, best = None, float(costs[:, 0].sum())
    for cut in cuts:
        a = choose(g, float(cut))
        total = float(timed_cost(costs[np.arange(len(costs)), a], fee + .003).sum())
        if total < best - 1e-8: best_cut, best = float(cut), total
    return best_cut


def cross_validate(x, valid, costs, folds, inner, n_folds=None, time_queries=True, return_scores=False):
    """Out-of-fold mean3 actions, per-instance query CPU (3 inferences + aggregation) and per-fold margins."""
    n, k = costs.shape; action = np.zeros(n, dtype=int); query = np.zeros(n); cuts = []; held_scores = np.zeros((n, k - 1))
    n_folds = n_folds or int(folds.max()) + 1
    for fold in range(n_folds):
        held = folds == fold
        train, val = ~held & ~inner & valid, ~held & inner & valid
        ids = np.flatnonzero(held & valid)
        vp, hp, hf = [], [], []
        for seed in SEEDS:
            model = fit(x[train], costs[train], seed + fold)
            vp.append(scores(model, x[val], k))
            if time_queries:
                p, f = measured(model, x[ids], k)
            else:
                p, f = scores(model, x[ids], k), np.zeros(len(ids))
            hp.append(p); hf.append(f)
        vp, hp, hf = map(np.asarray, (vp, hp, hf))
        agg = np.zeros(len(ids))
        for i in range(len(ids)):
            t = time.process_time(); hp[:, i].mean(axis=0); hp[:, i].min(axis=0); agg[i] = time.process_time() - t
        cut = calibrate(vp.mean(axis=0), costs[val], np.zeros(val.sum()))
        action[ids] = choose(hp.mean(axis=0), cut); held_scores[ids] = hp.mean(axis=0)
        if cut is not None: query[ids] = hf.sum(axis=0) + agg
        cuts.append(cut)
    return (action, query, cuts, held_scores) if return_scores else (action, query, cuts)


def summarize(name, keys, costs, action, fee, d_ref=None):
    paid = timed_cost(costs[np.arange(len(costs)), action], fee)
    d = costs[:, 0] if d_ref is None else d_ref
    return {"policy": name, "mean_PAR2": float(paid.mean()), "solved": int((paid < 1200).sum()),
            "gain_vs_D_pct": 100 * float(d.sum() - paid.sum()) / float(d.sum()),
            "rescued_vs_D": int(((d == 1200) & (paid < 1200)).sum()), "lost_vs_D": int(((d < 1200) & (paid == 1200)).sum()),
            "actions": {a: int((action == i).sum()) for i, a in enumerate(ACTIONS)}, "total_cost_s": float(paid.sum())}, paid


def cmd_reproduce(a):
    keys, costs = load(a.data); x, valid = linear42(keys, a.gbd); folds, inner = folds_and_inner(keys, a.inputs)
    with threadpool_limits(limits=4):
        action, query, cuts = cross_validate(x, valid, costs, folds, inner)
    r13 = {r["instance_key"]: ACTIONS.index(r["iso_diagnostic_linear42_mean3_action"]) for r in read_csv(Path(a.inputs) / "R13b_iso_linear42.csv")}
    r54 = {r["instance_key"]: r for r in read_csv(Path(a.inputs) / "R54_predictions.csv")}
    same13 = sum(action[i] == r13[k] for i, k in enumerate(keys))
    fails = [k for k in keys if float(r54[k]["mean3_query_CPU_s"]) == 0 and r54[k]["mean3_action"] == "D"]
    same54 = sum(action[i] == ACTIONS.index(r54[k]["mean3_action"]) for i, k in enumerate(keys))
    s_free, _ = summarize("reimplemented mean3, free features", keys, costs, action, np.zeros(len(keys)))
    out = {"valid": int(valid.sum()), "cuts": cuts, "actions_equal_R13b_mean3": int(same13),
           "actions_equal_R54_mean3": int(same54), "parents": len(keys), "free": s_free}
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "reproduce.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("cmd", choices=["reproduce"])
    for x in ("--data", "--gbd", "--inputs", "--out"): p.add_argument(x, required=True)
    a = p.parse_args()
    {"reproduce": cmd_reproduce}[a.cmd](a)
