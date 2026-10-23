#!/usr/bin/env python3
"""V2 of goal v5: readers with a default gate on every observation package,
old-reader controls, nested family-grouped CV on dev (protocol sections 6-7),
strategy choice and export (section 9).

  $FP_PY scripts/observations_v5/v5select.py [--export]

Writes results/observations_v5/{selection.csv, oof_choices.csv, fallback.csv,
selection_meta.json} and reports/observations_v5/SELECTION_TABLES.md (+ figures);
with --export also configs/observations_v5/frozen/{S1,S2}_fold{k}.json and
{S1,S2}_final.json.
"""

import argparse
import collections
import csv
import hashlib
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "three_way"))
import v5data as VD  # noqa: E402
import v5lib  # noqa: E402

ROOT = v5lib.ROOT
RES = os.path.join(ROOT, "results", "observations_v5")
REP = os.path.join(ROOT, "reports", "observations_v5")
FROZEN = os.path.join(ROOT, "configs", "observations_v5", "frozen")
SEED = 20261023
THETAS = [0.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, None]  # None = never deviate
ALPHAS = [1.0, 10.0, 100.0]
DEPTHS = [1, 2]
THETA1 = [20.0, 50.0, None]
THETA_ASK = [-20.0, -5.0, 0.0]
PAR2 = v5lib.PAR2
STATIC_PKGS = {"R01", "R02", "R03", "R04", "R09"}
PROBE_PKGS = {"R05", "R06", "R07", "R08", "R10", "R11"}


def theta_key(t):
    return float("inf") if t is None else t


# ------------------------------------------------------------ preprocessing

def make_pre(X, names, idx, standardize):
    cols = []
    for j, name in enumerate(names):
        v = X[idx, j]
        nm = ~np.isnan(v)
        if nm.sum() == 0:
            continue
        med = float(np.median(v[nm]))
        x = np.where(nm, v, med)
        has_missing = bool((~nm).any())
        if x.std() == 0 and not has_missing:
            continue
        col = {"name": name, "kind": "value", "median": med}
        if standardize:
            sd = float(x.std())
            col["mean"], col["scale"] = float(x.mean()), (sd if sd > 1e-12 else 1.0)
        if x.std() > 0 or has_missing:
            cols.append(col)
        if has_missing:
            cols.append({"name": name, "kind": "missing"})
    return {"columns": cols, "standardize": bool(standardize)}


def apply_pre(pre, X, names):
    pos = {n: j for j, n in enumerate(names)}
    Z = np.zeros((X.shape[0], len(pre["columns"])))
    for c, col in enumerate(pre["columns"]):
        v = X[:, pos[col["name"]]]
        if col["kind"] == "missing":
            Z[:, c] = np.isnan(v).astype(float)
            continue
        x = np.where(np.isnan(v), col["median"], v)
        if pre["standardize"]:
            x = np.clip((x - col["mean"]) / col["scale"], -5.0, 5.0)
        Z[:, c] = x
    return Z


# ------------------------------------------------------------------ readers

def export_tree(est):
    t = est.tree_

    def node(i):
        if t.children_left[i] == -1:
            return {"value": float(t.value[i][0][0])}
        return {"feature": int(t.feature[i]), "threshold": float(t.threshold[i]),
                "left": node(t.children_left[i]), "right": node(t.children_right[i])}
    return node(0)


def fit_reader(kind, hp, P, idx):
    """kind: ridge | tree | forest; idx: training rows (bool mask)."""
    from sklearn.linear_model import Ridge
    from sklearn.tree import DecisionTreeRegressor
    from sklearn.ensemble import RandomForestRegressor
    X, C, names = P["X"], P["C"], P["names"]
    pre = make_pre(X, names, idx, standardize=(kind == "ridge"))
    Z = apply_pre(pre, X[idx], names)
    models = {}
    for a, j in (("Fp", 1), ("Fm", 2)):
        y = C[idx, 0] - C[idx, j]
        if Z.shape[1] == 0 or len(y) < 2:
            models[a] = {"type": "ridge", "intercept": float(y.mean()) if len(y) else 0.0, "coef": []}
            continue
        if kind == "ridge":
            m = Ridge(alpha=hp).fit(Z, y)
            models[a] = {"type": "ridge", "intercept": float(m.intercept_), "coef": [float(c) for c in m.coef_]}
        elif kind == "tree":
            m = DecisionTreeRegressor(max_depth=hp, min_samples_leaf=20, random_state=0).fit(Z, y)
            models[a] = {"type": "tree", "root": export_tree(m)}
        else:
            m = RandomForestRegressor(n_estimators=300, min_samples_leaf=10, max_features=0.33,
                                      random_state=SEED, n_jobs=8).fit(Z, y)
            models[a] = {"type": "forest", "trees": [export_tree(e) for e in m.estimators_]}
        models[a]["_est"] = m
    return {"pre": pre, "models": models, "kind": kind, "hp": hp}


def predict_gains(reader, P, idx):
    """(n_idx, 2) predicted gains of F+ and F- over D."""
    Z = apply_pre(reader["pre"], P["X"][idx], P["names"])
    G = np.zeros((Z.shape[0], 2))
    for c, a in enumerate(("Fp", "Fm")):
        m = reader["models"][a]
        if m["type"] == "ridge" and "_est" not in m:
            G[:, c] = m["intercept"] + (Z @ np.array(m["coef"]) if m["coef"] else 0.0)
        else:
            G[:, c] = m["_est"].predict(Z)
    return G


def gate(G, theta):
    """choice index (0 D, 1 F+, 2 F-) from predicted gains."""
    best = np.where(G[:, 0] >= G[:, 1], 1, 2)
    g = np.maximum(G[:, 0], G[:, 1])
    if theta is None:
        return np.zeros(len(G), int)
    return np.where(g > theta, best, 0)


def strip(reader):
    out = {"pre": reader["pre"], "models": {}, "kind": reader["kind"], "hp": reader["hp"]}
    for a, m in reader["models"].items():
        out["models"][a] = {k: v for k, v in m.items() if k != "_est"}
    return out


# --------------------------------------------------------------- CV engine

def costs_of(P, choice, rows):
    """Cost of a choice vector on rows (bool mask or index array)."""
    C = P["C"][rows]
    return C[np.arange(len(C)), choice]


def inner_select(kind, hps, P, train, inner):
    """Inner 3-fold family CV on 'train': returns best (hp, theta) and the
    inner OOF gains per hp."""
    n = len(train)
    cons = P["consulted"]
    oof = {}
    for hp in hps:
        G = np.zeros((n, 2))
        for f in range(3):
            fit_idx = train & (inner != f) & cons
            pr_idx = train & (inner == f) & cons
            if pr_idx.sum() == 0:
                continue
            r = fit_reader(kind, hp, P, fit_idx)
            G[pr_idx] = predict_gains(r, P, pr_idx)
        oof[hp] = G
    best = None
    for hp in hps:
        for th in THETAS:
            ch = np.zeros(n, int)
            ch[train & cons] = gate(oof[hp][train & cons], th)
            score = -costs_of(P, ch[train], train).mean()
            key = (round(score, 9), theta_key(th), hp if kind == "ridge" else (-hp if hp else 0))
            if best is None or key > best[0]:
                best = (key, hp, th)
    return best[1], best[2], oof


def cv_reader(kind, P, D, hps=None):
    """Outer 5-fold CV with inner hyperparameter selection.
    Returns dict(choice, cost, G (outer OOF gains), hp/theta per fold)."""
    hps = hps or (ALPHAS if kind == "ridge" else DEPTHS if kind == "tree" else [None])
    n = D.n
    choice = np.zeros(n, int)
    G = np.zeros((n, 2))
    per_fold = []
    for k in range(5):
        train, test = D.outer != k, D.outer == k
        hp, th, _ = inner_select(kind, hps, P, train, D.inner[k])
        r = fit_reader(kind, hp, P, train & P["consulted"])
        tc = test & P["consulted"]
        G[tc] = predict_gains(r, P, tc)
        choice[tc] = gate(G[tc], th)
        per_fold.append({"fold": k, "hp": hp, "theta": th})
    return {"choice": choice, "cost": costs_of(P, choice, np.arange(n)), "G": G, "folds": per_fold}


def cv_old(kind, P, D):
    """v4 readers (twselect) on a package's inputs, trained on consulted rows."""
    import twselect as TS
    n = D.n
    choice = np.zeros(n, int)
    for k in range(5):
        tr = (D.outer != k) & P["consulted"]
        te = (D.outer == k) & P["consulted"]
        model = TS.fit(kind, P["X"][tr], P["C"][tr], P["names"])
        if te.sum():
            choice[te] = TS.predict_all(model, P["X"][te], P["names"])
    return {"choice": choice, "cost": costs_of(P, choice, np.arange(n))}


def cv_v4_exact(kind, budget, D):
    """v4 S2 candidate exactly as twselect (all rows, v4 costs)."""
    import twselect as TS
    Dv = TS.Data(D.rows, VD.KAPPA_V4)
    names, X = Dv.features(budget)
    C, o, ps = Dv.sim_costs(budget)
    choice = np.zeros(D.n, int)
    for k in range(5):
        tr, te = D.outer != k, D.outer == k
        model = TS.fit(kind, X[tr], C[tr], names)
        choice[te] = TS.predict_all(model, X[te], names)
    P = {"C": C, "o": o, "answered": ps, "forced": np.zeros(D.n, bool), "consulted": ~ps}
    return P, {"choice": choice, "cost": C[np.arange(D.n), choice]}


def cv_two_stage(kind, D, P1, P2):
    """R11 (M10): stage 1 on the static part, conditional R06 arms, stage 2."""
    hps = ALPHAS if kind == "ridge" else DEPTHS if kind == "tree" else [None]
    n = D.n
    choice_cost = np.zeros(n)
    path = np.zeros(n, int)  # 0 keep D, 1 direct, 2 probed
    choice = np.zeros(n, int)
    per_fold = []
    for k in range(5):
        train, test = D.outer != k, D.outer == k
        inner = D.inner[k]
        hp1, _, oof1 = inner_select(kind, hps, P1, train, inner)
        hp2, th2, oof2 = inner_select(kind, hps, P2, train, inner)
        G1, G2 = oof1[hp1], oof2[hp2]
        best = None
        for t1 in THETA1:
            for ta in THETA_ASK:
                c = two_stage_cost(P1, P2, G1, G2, t1, ta, th2, train)
                key = (round(-c.mean(), 9), theta_key(t1), ta)
                if best is None or key > best[0]:
                    best = (key, t1, ta)
        _, t1, ta = best
        r1 = fit_reader(kind, hp1, P1, train & P1["consulted"])
        r2 = fit_reader(kind, hp2, P2, train & P2["consulted"])
        g1 = np.zeros((n, 2))
        g2 = np.zeros((n, 2))
        g1[test & P1["consulted"]] = predict_gains(r1, P1, test & P1["consulted"])
        g2[test & P2["consulted"]] = predict_gains(r2, P2, test & P2["consulted"])
        c, ch, pth = two_stage_cost(P1, P2, g1, g2, t1, ta, th2, test, detail=True)
        choice_cost[test], choice[test], path[test] = c, ch, pth
        per_fold.append({"fold": k, "hp1": hp1, "hp2": hp2, "theta1": t1, "theta_ask": ta, "theta2": th2})
    return {"choice": choice, "cost": choice_cost, "path": path, "folds": per_fold}


def two_stage_cost(P1, P2, G1, G2, t1, ta, th2, rows, detail=False):
    idx = np.nonzero(rows)[0]
    cost = np.zeros(len(idx))
    choice = np.zeros(len(idx), int)
    path = np.zeros(len(idx), int)
    for m, i in enumerate(idx):
        if not P1["consulted"][i]:  # static part incomplete (-> D) or (never) answered
            cost[m] = P1["C"][i, 0]
            continue
        g = max(G1[i, 0], G1[i, 1])
        b = 1 if G1[i, 0] >= G1[i, 1] else 2
        if t1 is not None and g > t1:
            cost[m], choice[m], path[m] = P1["C"][i, b], b, 1
        elif g > ta:
            path[m] = 2
            if not P2["consulted"][i]:
                cost[m] = P2["C"][i, 0]
            else:
                c2 = gate(G2[i:i + 1], th2)[0]
                cost[m], choice[m] = P2["C"][i, c2], c2
        else:
            cost[m] = P1["C"][i, 0]
    return (cost, choice, path) if detail else cost


# ---------------------------------------------------------------- statistics

class Boot:
    def __init__(self, fam, B=10000, seed=SEED):
        fams = sorted(set(fam))
        self.fi = np.array([fams.index(f) for f in fam])
        self.nf = len(fams)
        rng = np.random.default_rng(seed)
        self.idx = rng.integers(0, self.nf, size=(B, self.nf))
        self.cnt = np.bincount(self.fi, minlength=self.nf).astype(float)

    def mean_ci(self, x):
        s = np.bincount(self.fi, weights=x, minlength=self.nf)
        num = s[self.idx].sum(1)
        den = self.cnt[self.idx].sum(1)
        m = num / den
        return float(x.mean()), float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))


def summarize(name, pkg, reader, res, P, D, boot, extra=None):
    c0 = D.c0[:, 0]
    cost, choice = res["cost"], res["choice"]
    gain = c0 - cost
    g, lo, hi = boot.mean_ci(gain)
    dev = (choice != 0) & P["consulted"]
    Cd = P["C"][:, 0]
    right = dev & (cost < Cd - 1e-9)
    wrong = dev & (cost > Cd + 1e-9)
    severe = (D.solved[:, 0] & (cost >= PAR2)) | (cost - c0 >= 100)
    pos = np.sort(gain[gain > 0])[::-1]
    row = {"name": name, "package": pkg, "reader": reader, "par2": cost.mean(), "solved": int((cost < PAR2).sum()),
           "gain": g, "gain_lo": lo, "gain_hi": hi, "gain_pct": 100 * g / c0.mean(),
           "gain_pct_lo": 100 * lo / c0.mean(), "gain_pct_hi": 100 * hi / c0.mean(),
           "dev_Fp": int((dev & (choice == 1)).sum()), "dev_Fm": int((dev & (choice == 2)).sum()),
           "precision": (right.sum() / dev.sum()) if dev.sum() else float("nan"),
           "wrong_loss": float((cost - Cd)[wrong].sum() / D.n), "right_gain": float((Cd - cost)[right].sum() / D.n),
           "severe": int(severe.sum()), "top10_share": float(pos[:10].sum() / pos.sum()) if len(pos) else float("nan"),
           "obs_cpu": float(P["o"].mean()), "forced_D": int(P["forced"].sum()), "answered": int(P["answered"].sum())}
    if extra:
        row.update(extra)
    return row


def paired(a, b, boot):
    """mean(cost_b - cost_a): positive = a better; CI."""
    return boot.mean_ci(b - a)


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true")
    a = ap.parse_args()
    os.makedirs(RES, exist_ok=True)
    os.makedirs(REP, exist_ok=True)
    D = VD.Dev()
    assert D.missing_obs == 0 and D.missing_arms == 0, (D.missing_obs, D.missing_arms)
    boot = Boot(D.fam)
    rows, oof, meta = [], {}, {"kappa": D.kappa, "folds": {}}

    def record(name, pkg, reader, res, P, extra=None):
        rows.append(summarize(name, pkg, reader, res, P, D, boot, extra))
        oof[name] = (res, P)
        if "folds" in res:
            meta["folds"][name] = res["folds"]

    # ---- controls
    z = np.zeros(D.n, bool)
    Pd = {"C": D.c0, "o": np.zeros(D.n), "consulted": ~z, "answered": z, "forced": z}
    record("always-D", "-", "-", {"choice": np.zeros(D.n, int), "cost": D.c0[:, 0]}, Pd)
    record("oracle", "-", "-", {"choice": D.c0.argmin(1), "cost": D.c0.min(1)}, Pd)
    for budget, tag in ((None, "v4static"), (0.1, "R00")):
        for kind in ("logreg", "tree1", "tree3"):
            P, res = cv_v4_exact(kind, budget, D)
            record(f"{tag}|v4-{kind}", tag, f"v4-{kind}", res, P, {"control": 1})
    # ---- packages
    PK = {"S28": D.s28_package(), "R00": D.v4_package(0.1)}
    for p in VD.PKGS:
        if p != "R11":
            PK[p] = D.package(p)
    PK["R11s1"] = D.package("R11", stage=1)
    PK["R11s2"] = D.package("R11", stage=2)
    for p in ["S28", "R00"] + [q for q in VD.PKGS if q != "R11"]:
        P = PK[p]
        for kind, rname in (("ridge", "RG"), ("tree", "TG")):
            res = cv_reader(kind, P, D)
            record(f"{p}|{rname}", p, rname, res, P, {"control": int(p == "S28")})
        if p not in ("R00",):
            for kind in ("logreg", "tree1", "tree3"):
                res = cv_old(kind, P, D)
                record(f"{p}|v4-{kind}", p, f"v4-{kind}", res, P, {"control": 1})
    for kind, rname in (("ridge", "RG"), ("tree", "TG")):
        res = cv_two_stage(kind, D, PK["R11s1"], PK["R11s2"])
        P = dict(PK["R11s2"])
        P["o"] = np.where(res["path"] == 2, PK["R11s2"]["o"], PK["R11s1"]["o"])
        record(f"R11|{rname}", "R11", rname, res, P, {"probed": int((res["path"] == 2).sum())})
    # ---- stronger reader for 3 promoted packages (R01-R11 by best of RG/TG)
    best_by_pkg = {}
    for r in rows:
        if r["package"] in VD.PKGS and r["reader"] in ("RG", "TG"):
            best_by_pkg[r["package"]] = max(best_by_pkg.get(r["package"], -1e9), r["gain"])
    promoted = sorted(best_by_pkg, key=lambda p: -best_by_pkg[p])[:3]
    meta["promoted"] = promoted
    for p in promoted:
        if p == "R11":  # two-stage: RF in both stages
            res = cv_two_stage("forest", D, PK["R11s1"], PK["R11s2"])
            P = dict(PK["R11s2"])
            P["o"] = np.where(res["path"] == 2, PK["R11s2"]["o"], PK["R11s1"]["o"])
            record("R11|RF", "R11", "RF", res, P, {"promoted": 1, "probed": int((res["path"] == 2).sum())})
            continue
        res = cv_reader("forest", PK[p], D, hps=[None])
        record(f"{p}|RF", p, "RF", res, PK[p], {"promoted": 1})

    # ---- write tables
    with open(os.path.join(RES, "selection.csv"), "w", newline="") as f:
        keys = list(dict.fromkeys(k for r in rows for k in r))
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(RES, "oof_choices.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "hash", "family_group", "group", "choice", "cost", "cost_D_noobs", "obs_cpu", "consulted"])
        for name, (res, P) in oof.items():
            for i in range(D.n):
                w.writerow([name, D.h[i], D.fam[i], D.group[i], VD.ACTS[res["choice"][i]], round(float(res["cost"][i]), 4),
                            D.c0[i, 0], round(float(P["o"][i]), 4), int(P["consulted"][i])])
    meta["promoted_gain"] = {p: best_by_pkg[p] for p in promoted}
    json.dump(meta, open(os.path.join(RES, "selection_meta.json"), "w"), indent=1, default=str)
    print(f"{'name':24s} {'PAR2':>8s} {'gain':>7s} {'CI':>17s} {'F+':>4s} {'F-':>4s} {'prec':>5s} {'sev':>4s} {'obs':>6s}")
    for r in rows:
        print(f"{r['name']:24s} {r['par2']:8.2f} {r['gain_pct']:+6.1f}% [{r['gain_pct_lo']:+5.1f},{r['gain_pct_hi']:+5.1f}] "
              f"{r['dev_Fp']:4d} {r['dev_Fm']:4d} {r['precision']:5.2f} {r['severe']:4d} {r['obs_cpu']:6.2f}")
    import pickle
    pickle.dump({"rows": rows, "oof": {k: (v[0], {kk: vv for kk, vv in v[1].items() if kk in ("C", "o", "consulted", "answered", "forced")})
                                       for k, v in oof.items()}, "meta": meta},
                open(os.path.join(RES, "selection_state.pkl"), "wb"))


if __name__ == "__main__":
    main()
