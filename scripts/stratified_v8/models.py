#!/usr/bin/env python3
"""v8 S2: SBS, skip rule, the two small methods (depth-2 rule tree, ridge on t_a - t_D) with nested
grouped CV, scale-only controls, and the freeze decision (docs/STRATIFIED_PROTOCOL_V8.md sections 6-7).
Standard library only; development data only.

  models.py --features results/stratified_v8/features_dev.json --times results/stratified_v8/dev_times.json
            [--freeze configs/stratified_v8/frozen/strategy.json]

dev_times.json: {instance: {"D": t, "Fp": t, "Fm": t, "bound": {"D": bool, ...}}} (normalize.py).
Writes results/stratified_v8/s2_models.json.
"""

import argparse
import itertools
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CFG = os.path.join(ROOT, "configs", "stratified_v8")
P = json.load(open(os.path.join(CFG, "protocol.json")))
M = P["methods"]
FE = P["features"]
FULL = FE["scale_only"] + FE["structure"]
SCALE = FE["scale_only"]
ACTS = ("D", "Fp", "Fm")
OVER = FE["wrapper_overhead_seconds_in_cv"]


# ------------------------------------------------------------------ helpers

def folds(ids, split, k):
    """Within a cell, rank by split hash among `ids`; fold = rank mod k (empty folds are skipped)."""
    out, cells = {}, {}
    for i in ids:
        cells.setdefault((split[i]["type"], split[i]["scale"]), []).append(i)
    for c in cells.values():
        for r, i in enumerate(sorted(c, key=lambda i: split[i]["split_hash"])):
            out[i] = r % k
    return out


def quantile(vals, q):
    v = sorted(vals)
    return v[int(round(q * (len(v) - 1)))]


def total(ids, choice, T, obs):
    return sum(T[i][choice[i]] + (obs[i] if obs is not None else 0.0) for i in ids)


# ------------------------------------------------------------------ tree

def leaf_action(S, T, margin):
    if not S:
        return "D"
    sums = {a: sum(T[i][a] for i in S) for a in ACTS}
    best = min(ACTS, key=lambda a: (sums[a], ACTS.index(a)))
    if best != "D" and len(S) >= M["tree"]["min_leaf"] and sums["D"] - sums[best] > margin:
        return best
    return "D"


def leaf_cost(S, T, margin):
    a = leaf_action(S, T, margin)
    return sum(T[i][a] for i in S), {"leaf": a}


def best_subtree(S, T, X, cands, margin, depth):
    cost, node = leaf_cost(S, T, margin)
    best = (cost, 0, node)
    if depth == 0:
        return best
    for f, thr in cands:
        L = [i for i in S if X[i][f] <= thr]
        R = [i for i in S if X[i][f] > thr]
        if not L or not R:
            continue
        cl, nl, tl = best_subtree(L, T, X, cands, margin, depth - 1)
        cr, nr, tr = best_subtree(R, T, X, cands, margin, depth - 1)
        if (cl + cr, 1 + nl + nr) < best[:2]:
            best = (cl + cr, 1 + nl + nr, {"feature": f, "threshold": thr, "left": tl, "right": tr})
    return best


def fit_tree(ids, T, X, names, margin):
    cands = [(f, quantile([X[i][f] for i in ids], q)) for f in names for q in M["tree"]["threshold_quantiles"]]
    cands = sorted(set(cands), key=lambda c: (names.index(c[0]), c[1]))
    return {"method": "tree", "tree": best_subtree(ids, T, X, cands, margin, M["tree"]["max_depth"])[2],
            "margin": margin, "features": names}


# ------------------------------------------------------------------ ridge

def solve(A, b):
    n = len(A)
    M_ = [row[:] + [b[k]] for k, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M_[r][c]))
        M_[c], M_[p] = M_[p], M_[c]
        if abs(M_[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r != c:
                f = M_[r][c] / M_[c][c]
                M_[r] = [x - f * y for x, y in zip(M_[r], M_[c])]
    return [M_[k][n] / M_[k][k] if abs(M_[k][k]) > 1e-12 else 0.0 for k in range(n)]


def fit_ridge(ids, T, X, names, alpha, margin):
    mean = {f: sum(X[i][f] for i in ids) / len(ids) for f in names}
    std = {}
    for f in names:
        v = sum((X[i][f] - mean[f]) ** 2 for i in ids) / len(ids)
        std[f] = v ** 0.5 if v > 1e-18 else 1.0
    Z = [[1.0] + [(X[i][f] - mean[f]) / std[f] for f in names] for i in ids]
    k = len(names) + 1
    A = [[sum(z[r] * z[c] for z in Z) + (alpha if r == c and r > 0 else 0.0) for c in range(k)] for r in range(k)]
    models = {}
    for a in ("Fp", "Fm"):
        y = [T[i][a] - T[i]["D"] for i in ids]
        w = solve(A, [sum(z[r] * yy for z, yy in zip(Z, y)) for r in range(k)])
        models[a] = {"intercept": w[0], "coef": dict(zip(names, w[1:]))}
    return {"method": "ridge", "mean": mean, "std": std, "models": models, "margin": margin, "alpha": alpha,
            "features": names}


def predict(strategy, x):
    if strategy["method"] == "tree":
        node = strategy["tree"]
        while "leaf" not in node:
            node = node["left"] if x[node["feature"]] <= node["threshold"] else node["right"]
        return node["leaf"]
    pred = {a: m["intercept"] + sum(w * (x[f] - strategy["mean"][f]) / strategy["std"][f] for f, w in m["coef"].items())
            for a, m in strategy["models"].items()}
    best = min(sorted(pred), key=lambda a: pred[a])
    return best if pred[best] < -strategy["margin"] else "D"


# ------------------------------------------------------------------ CV

def grid(method):
    if method == "tree":
        # ties -> more conservative (larger margin): listed last, compared with <=
        return [{"margin": m} for m in M["tree"]["leaf_margin_seconds"]]
    return [{"alpha": a, "margin": m} for a in M["ridge"]["alpha"] for m in M["ridge"]["margin_seconds"]]


def fit(method, ids, T, X, names, hp):
    return fit_tree(ids, T, X, names, hp["margin"]) if method == "tree" else fit_ridge(ids, T, X, names, hp["alpha"], hp["margin"])


def cv_total(method, ids, T, X, obs, names, hp, split, k):
    fo = folds(ids, split, k)
    choice = {}
    for f in sorted(set(fo.values())):
        tr = [i for i in ids if fo[i] != f]
        te = [i for i in ids if fo[i] == f]
        s = fit(method, tr, T, X, names, hp)
        for i in te:
            choice[i] = predict(s, X[i])
    return total(ids, choice, T, obs), choice


def select_hp(method, ids, T, X, obs, names, split):
    best = None
    for hp in grid(method):
        c, _ = cv_total(method, ids, T, X, obs, names, hp, split, M["inner_folds"])
        if best is None or c <= best[0]:
            best = (c, hp)
    return best[1], best[0]


def nested(method, ids, T, X, obs, names, split):
    fo = folds(ids, split, M["outer_folds"])
    choice, chosen = {}, {}
    for f in sorted(set(fo.values())):
        tr = [i for i in ids if fo[i] != f]
        te = [i for i in ids if fo[i] == f]
        hp, _ = select_hp(method, tr, T, X, obs, names, split)
        s = fit(method, tr, T, X, names, hp)
        chosen[f] = hp
        for i in te:
            choice[i] = predict(s, X[i])
    return {"cv_total": total(ids, choice, T, obs), "choices": choice, "hyper_by_fold": chosen,
            "deviations": sum(1 for i in ids if choice[i] != "D")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--times", required=True)
    ap.add_argument("--freeze")
    a = ap.parse_args()
    split = json.load(open(os.path.join(CFG, "split.json")))
    fe = json.load(open(os.path.join(ROOT, a.features)))["instances"]
    tm = json.load(open(os.path.join(ROOT, a.times)))
    ids = sorted(i for i in tm if split[i]["split"] == "dev")
    assert all(split[i]["split"] == "dev" for i in ids) and len(ids) == len(tm)
    T = {i: {x: tm[i][x] for x in ACTS} for i in ids}
    X = {i: fe[i]["features"] for i in ids}
    obs = {i: fe[i]["cpu"] + OVER for i in ids}
    bad = [i for i in ids if not fe[i]["ok"]]
    out = {"n_dev": len(ids), "observation_incomplete": bad,
           "bounds_used": {i: tm[i].get("bound") for i in ids if any((tm[i].get("bound") or {}).values())}}
    for i in bad:  # deployment falls back to D: never deviate; keep features only for fitting if present
        pass
    tot = {x: sum(T[i][x] for i in ids) for x in ACTS}
    sbs = min(ACTS, key=lambda x: (tot[x], ACTS.index(x)))
    orc = {i: min(ACTS, key=lambda x: (T[i][x], ACTS.index(x))) for i in ids}
    out.update(totals_fixed=tot, SBS=sbs, oracle_total=sum(T[i][orc[i]] for i in ids),
               observation_total=sum(obs.values()))
    gap = tot[sbs] - out["oracle_total"]
    out["skip_training"] = gap <= 2 * out["observation_total"]
    out["sbs_minus_oracle"] = gap
    if out["skip_training"]:
        print(json.dumps(out, indent=1))
        json.dump(out, open(os.path.join(ROOT, "results", "stratified_v8", "s2_models.json"), "w"), indent=1)
        return
    usable = [i for i in ids if fe[i]["ok"]]
    if len(usable) != len(ids):
        raise SystemExit(f"observation incomplete on dev instances {bad}: handle before fitting")
    res = {}
    for method, names, tag in (("tree", FULL, "T"), ("ridge", FULL, "R"), ("tree", SCALE, "T_s"), ("ridge", SCALE, "R_s")):
        res[tag] = nested(method, ids, T, X, obs, names, split)
        print(tag, round(res[tag]["cv_total"], 2), "deviations", res[tag]["deviations"], flush=True)
    out["cv"] = res
    best = min(("T", "R"), key=lambda k: (res[k]["cv_total"], k))
    out["best_full"] = best
    out["freeze"] = res[best]["cv_total"] < tot[sbs]
    if out["freeze"]:
        method = "tree" if best == "T" else "ridge"
        hp, inner = select_hp(method, ids, T, X, obs, FULL, split)
        strat = fit(method, ids, T, X, FULL, hp)
        strat.update(name=f"v8_{method}", hyper=hp, inner_cv_total_all_dev=inner, trained_on=ids,
                     fallback="D on missing or incomplete observation")
        out["frozen_strategy"] = strat
        out["in_sample_total"] = total(ids, {i: predict(strat, X[i]) for i in ids}, T, obs)
        if a.freeze:
            os.makedirs(os.path.dirname(os.path.join(ROOT, a.freeze)), exist_ok=True)
            json.dump(strat, open(os.path.join(ROOT, a.freeze), "w"), indent=1, sort_keys=True)
    json.dump(out, open(os.path.join(ROOT, "results", "stratified_v8", "s2_models.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k not in ("cv", "frozen_strategy")}, indent=1))


if __name__ == "__main__":
    main()
