#!/usr/bin/env python3
"""R3 of goal v6: the 8 registered comparisons (protocol section 4) on dev 401,
family-grouped outer 5 / inner 3 folds (v5 folds), increments, promotion and
export of fold / final models.

  $FP_PY scripts/stable_selection_v6/v6select.py [--export]

Comparisons: P1|RG P1|M05 P2|RG P2|M05 P3|RG P3|M05 R-LS R-SYM.
Writes results/stable_selection_v6/{selection.csv, oof.csv, increments.csv,
selection_meta.json, promoted.json}, reports/stable_selection_v6/SELECTION_TABLES.md,
figures/gain_decomposition.png; with --export configs/stable_selection_v6/frozen/*.json.
"""

import argparse
import csv
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "observations_v5"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "three_way"))
import v5select as VS  # noqa: E402
import make_panels as MP5  # noqa: E402
import v6data as V6D  # noqa: E402
import v6lib  # noqa: E402

ROOT = v6lib.ROOT
RES = os.path.join(ROOT, "results", "stable_selection_v6")
REP = os.path.join(ROOT, "reports", "stable_selection_v6")
FROZEN = os.path.join(ROOT, "configs", "stable_selection_v6", "frozen")
SEED = 20261023
THETAS = VS.THETAS
PAR2 = v6lib.PAR2
ACTS = ("D", "Fp", "Fm")
COMPARISONS = [("P1", "RG"), ("P1", "M05"), ("P2", "RG"), ("P2", "M05"), ("P3", "RG"), ("P3", "M05"),
               ("PLS", "RULE"), ("PSYM", "RULE")]
NAMES = {("PLS", "RULE"): "R-LS", ("PSYM", "RULE"): "R-SYM"}


def cname(p, r):
    return NAMES.get((p, r), f"{p}|{r}")


# ------------------------------------------------------------- readers

def fit_rg(hp, P, idx, fam):
    return VS.fit_reader("ridge", hp, P, idx)


def pred_rg(r, P, idx):
    return VS.predict_gains(r, P, idx)


def fit_m05(hp, P, idx, fam):
    from sklearn.linear_model import LogisticRegression, Ridge
    X, names = P["X"], P["names"]
    pre = VS.make_pre(X, names, idx, standardize=True)
    Z = VS.apply_pre(pre, X[idx], names)
    h = P["o"][idx]
    models = {}
    for j, a in enumerate(ACTS):
        sol = P["C"][idx, j] < PAR2
        t = np.maximum(0.0, P["C"][idx, j] - h)
        m = {"p_const": None, "p_intercept": 0.0, "p_coef": [], "t_intercept": math.log1p(300.0), "t_coef": [],
             "t_smear": 1.0}
        if Z.shape[1] == 0 or sol.all() or (~sol).all():
            m["p_const"] = float(sol.mean()) if len(sol) else 0.0
        else:
            lr = LogisticRegression(C=hp, max_iter=5000).fit(Z, sol)
            m["p_intercept"], m["p_coef"] = float(lr.intercept_[0]), [float(c) for c in lr.coef_[0]]
        if sol.sum() >= 5 and Z.shape[1] > 0:
            y = np.log1p(t[sol])
            rr = Ridge(alpha=10.0).fit(Z[sol], y)
            res = y - rr.predict(Z[sol])
            m["t_intercept"], m["t_coef"] = float(rr.intercept_), [float(c) for c in rr.coef_]
            m["t_smear"] = float(np.mean(np.exp(res)))
        elif sol.any():
            m["t_intercept"] = float(math.log1p(t[sol].mean()))
            m["t_coef"] = [0.0] * Z.shape[1]
        else:
            m["t_coef"] = [0.0] * Z.shape[1]
        models[a] = m
    return {"kind": "m05", "pre": pre, "models": models, "hp": hp}


def m05_par2(r, Z, h):
    out = {}
    for a in ACTS:
        m = r["models"][a]
        if m["p_const"] is not None:
            p = np.full(len(Z), m["p_const"])
        else:
            zz = m["p_intercept"] + Z @ np.array(m["p_coef"])
            p = 1.0 / (1.0 + np.exp(-np.clip(zz, -700, 700)))
        coef = np.array(m["t_coef"]) if m["t_coef"] else np.zeros(Z.shape[1])
        t = np.maximum(0.0, np.exp(m["t_intercept"] + Z @ coef) * m["t_smear"] - 1.0)
        out[a] = p * (h + t) + (1 - p) * PAR2
    return out


def pred_m05(r, P, idx):
    Z = VS.apply_pre(r["pre"], P["X"][idx], P["names"])
    par = m05_par2(r, Z, P["o"][idx])
    return np.stack([par["D"] - par["Fp"], par["D"] - par["Fm"]], 1)


def fit_rule(hp, P, idx, fam):
    from sklearn.tree import DecisionTreeRegressor
    X, names = P["X"], P["names"]
    pre = VS.make_pre(X, names, idx, standardize=False)
    Z = VS.apply_pre(pre, X[idx], names)
    fams = np.array(fam)[idx]
    models = {}
    for a, j in (("Fp", 1), ("Fm", 2)):
        y = P["C"][idx, 0] - P["C"][idx, j]
        if Z.shape[1] == 0 or len(y) < 30:
            models[a] = {"type": "tree", "root": {"value": {"mean": float(y.mean()) if len(y) else 0.0, "allowed": False,
                                                            "n": int(len(y)), "families": 0}}}
            continue
        est = DecisionTreeRegressor(max_depth=2, min_samples_leaf=15, random_state=0).fit(Z, y)
        leaf_of = est.apply(Z)
        t = est.tree_

        def node(i):
            if t.children_left[i] == -1:
                sel = leaf_of == i
                n, nf = int(sel.sum()), int(len(set(fams[sel])))
                return {"value": {"mean": float(t.value[i][0][0]), "n": n, "families": nf,
                                  "allowed": bool(n >= 15 and nf >= 3)}}
            return {"feature": int(t.feature[i]), "threshold": float(t.threshold[i]),
                    "left": node(t.children_left[i]), "right": node(t.children_right[i])}
        models[a] = {"type": "tree", "root": node(0)}
    return {"kind": "rule", "pre": pre, "models": models, "hp": hp}


def pred_rule(r, P, idx):
    Z = VS.apply_pre(r["pre"], P["X"][idx], P["names"])
    G = np.zeros((len(Z), 2))
    for c, a in enumerate(("Fp", "Fm")):
        for i in range(len(Z)):
            node = r["models"][a]["root"]
            while "value" not in node:
                node = node["left"] if Z[i, node["feature"]] <= node["threshold"] else node["right"]
            G[i, c] = node["value"]["mean"] if node["value"]["allowed"] else -1e18
    return G


READERS = {"RG": (fit_rg, pred_rg, [1.0, 10.0, 100.0], lambda hp: hp),
           "M05": (fit_m05, pred_m05, [0.1, 1.0], lambda hp: -hp),
           "RULE": (fit_rule, pred_rule, [None], lambda hp: 0)}


# --------------------------------------------------------------- CV

def inner_select(rd, P, train, inner, fam):
    fit, pred, hps, pref = READERS[rd]
    n = len(train)
    cons = P["consulted"]
    best = None
    for hp in hps:
        G = np.zeros((n, 2))
        for f in range(3):
            fi, pi = train & (inner != f) & cons, train & (inner == f) & cons
            if pi.sum() == 0 or fi.sum() < 10:
                continue
            G[pi] = pred(fit(hp, P, fi, fam), P, pi)
        for th in THETAS:
            ch = np.zeros(n, int)
            ch[train & cons] = VS.gate(G[train & cons], th)
            score = -VS.costs_of(P, ch[train], train).mean()
            key = (round(score, 9), VS.theta_key(th), pref(hp))
            if best is None or key > best[0]:
                best = (key, hp, th)
    return best[1], best[2]


def cv(rd, P, D):
    fit, pred, hps, _ = READERS[rd]
    choice = np.zeros(D.n, int)
    G = np.zeros((D.n, 2))
    folds = []
    for k in range(5):
        train, test = D.outer != k, D.outer == k
        hp, th = inner_select(rd, P, train, D.inner[k], D.fam)
        r = fit(hp, P, train & P["consulted"], D.fam)
        tc = test & P["consulted"]
        if tc.sum():
            G[tc] = pred(r, P, tc)
            choice[tc] = VS.gate(G[tc], th)
        folds.append({"fold": k, "hp": hp, "theta": th})
    return {"choice": choice, "cost": VS.costs_of(P, choice, np.arange(D.n)), "G": G, "folds": folds}


def strip_reader(r, theta):
    out = {"kind": r["kind"], "pre": r["pre"], "hp": r["hp"], "theta": theta, "models": {}}
    for a, m in r["models"].items():
        out["models"][a] = {k: v for k, v in m.items() if k != "_est"}
    return out


# --------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true")
    a = ap.parse_args()
    os.makedirs(RES, exist_ok=True)
    os.makedirs(os.path.join(REP, "figures"), exist_ok=True)
    D = V6D.Dev6()
    assert D.missing["obs6"] == 0 and D.missing["sz"] == 0, D.missing
    boot = VS.Boot(D.fam)
    c0 = D.c0[:, 0]
    PK = {p: D.package(p) for p in ("P1", "P2", "P3", "PLS", "PSYM")}
    rows, res_all = [], {}
    grp = np.array(D.group)
    for p, rd in COMPARISONS:
        res = cv(rd, PK[p], D)
        P = PK[p]
        name = cname(p, rd)
        res_all[name] = res
        row = VS.summarize(name, p, rd, res, P, D, boot)
        dev = (res["choice"] != 0) & P["consulted"]
        row.update({"completion": float(P["consulted"].mean()),
                    "fallback_rate": float(((res["choice"] == 0) & P["consulted"]).sum() / max(1, P["consulted"].sum())),
                    "dev_families": int(len({D.fam[i] for i in np.nonzero(dev)[0]})),
                    "d_solved_to_timeout": int((D.solved[:, 0] & (res["cost"] >= PAR2) & (P["C"][:, 0] < PAR2)).sum()),
                    "n_pos": int(((c0 - res["cost"]) > 1e-9).sum()), "n_neg": int(((c0 - res["cost"]) < -1e-9).sum()),
                    "folds": json.dumps(res["folds"])})
        for g in ("D-adv", "Fp-adv", "Fm-adv", "close", "all-timeout"):
            sel = grp == g
            row[f"gain_{g}"] = float((c0 - res["cost"])[sel].sum() / D.n)
            row[f"dev_{g}"] = int((dev & sel).sum())
        rows.append(row)
    # increments
    inc = []
    for rd in ("RG", "M05"):
        for p in ("P2", "P3"):
            m, lo, hi = VS.paired(res_all[f"{p}|{rd}"]["cost"], res_all[f"P1|{rd}"]["cost"], boot)
            inc.append({"test": "feature_increment_vs_P1", "a": f"{p}|{rd}", "b": f"P1|{rd}", "diff": m, "lo": lo, "hi": hi})
    for p in ("P1", "P2", "P3"):
        m, lo, hi = VS.paired(res_all[f"{p}|M05"]["cost"], res_all[f"{p}|RG"]["cost"], boot)
        inc.append({"test": "M05_vs_RG", "a": f"{p}|M05", "b": f"{p}|RG", "diff": m, "lo": lo, "hi": hi})
    # promotion (protocol section 4)
    stab = json.load(open(os.path.join(RES, "stability.json"))) if os.path.exists(os.path.join(RES, "stability.json")) else {}
    cap = 1 if stab.get("shrink_rule_triggered") else 2
    pos = sorted((r for r in rows if r["gain"] > 0), key=lambda r: -r["gain"])[:cap]
    if pos:
        promoted = [r["name"] for r in pos]
        mode = "positive OOF gain"
    else:
        promoted = [max(rows, key=lambda r: (round(r["gain"], 9), -r["obs_cpu"]))["name"]]
        mode = "negative-control deployment (no comparison with OOF gain > 0)"
    json.dump({"promoted": promoted, "mode": mode, "cap": cap}, open(os.path.join(RES, "promoted.json"), "w"), indent=1)
    # tables
    with open(os.path.join(RES, "selection.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(RES, "increments.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(inc[0]))
        w.writeheader()
        w.writerows(inc)
    with open(os.path.join(RES, "oof.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "hash", "family_group", "group", "choice", "cost", "cost_D_noobs", "gain_Fp", "gain_Fm", "consulted"])
        for name, res in res_all.items():
            p = [pp for (pp, rr) in COMPARISONS if cname(pp, rr) == name][0]
            for i in range(D.n):
                w.writerow([name, D.h[i], D.fam[i], D.group[i], ACTS[res["choice"][i]], round(float(res["cost"][i]), 4),
                            c0[i], round(float(res["G"][i, 0]), 3), round(float(res["G"][i, 1]), 3), int(PK[p]["consulted"][i])])
    L = ["# R3 选择表（由 `scripts/stable_selection_v6/v6select.py` 生成；dev 401，外层 5 折 OOF）", "",
         f"始终 D（不观察）PAR2 = {c0.mean():.2f}；事后最优 {D.c0.min(1).mean():.2f}。区间为家族 cluster bootstrap 95%。", "",
         "| 比较 | PAR2 | 相对始终 D | 观察完成率 | 默认回退率 | 偏离 F+/F− | 偏离涉及家族 | 精度 | 正确偏离 s/题 | 错误偏离 s/题 | D 可解→超时 | 正 / 负收益实例 | 平均观察 CPU s |",
         "|---|---:|---|---:|---:|---|---:|---:|---:|---:|---:|---|---:|"]
    for r in rows:
        prec = "—" if math.isnan(r["precision"]) else f"{r['precision']:.2f}"
        L.append(f"| {r['name']} | {r['par2']:.2f} | {r['gain_pct']:+.2f}% [{r['gain_pct_lo']:+.2f}, {r['gain_pct_hi']:+.2f}] | "
                 f"{r['completion']:.0%} | {r['fallback_rate']:.0%} | {r['dev_Fp']}/{r['dev_Fm']} | {r['dev_families']} | {prec} | "
                 f"{r['right_gain']:.2f} | {r['wrong_loss']:.2f} | {r['d_solved_to_timeout']} | {r['n_pos']} / {r['n_neg']} | {r['obs_cpu']:.3f} |")
    L += ["", "## 按原优势组（单 seed 标签）的净收益贡献（秒/题，401 题平均）与偏离次数", "",
          "| 比较 | D 优势 | F+ 优势 | F− 优势 | 接近 | 全部超时 |", "|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['name']} | " + " | ".join(f"{r['gain_' + g]:+.2f}（{r['dev_' + g]}）" for g in
                                                  ("D-adv", "Fp-adv", "Fm-adv", "close", "all-timeout")) + " |")
    L += ["", "## 增量（配对差 = b 的成本 − a 的成本，秒/题；正 = a 更好）", "", "| 检验 | a | b | 差值 [95% 区间] |", "|---|---|---|---|"]
    for x in inc:
        L.append(f"| {x['test']} | {x['a']} | {x['b']} | {x['diff']:+.2f} [{x['lo']:+.2f}, {x['hi']:+.2f}]{' *' if x['lo'] > 0 or x['hi'] < 0 else ''} |")
    L += ["", f"晋级（上限 {cap}）：{', '.join(promoted)}（{mode}）。", ""]
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(9, 3.8))
        x = np.arange(len(rows))
        rg = [r["right_gain"] for r in rows]
        wl = [-r["wrong_loss"] for r in rows]
        net = [r["gain"] for r in rows]
        ax.bar(x - 0.25, rg, 0.25, label="right deviations (s/inst saved)", color="#2a9d8f")
        ax.bar(x, wl, 0.25, label="wrong deviations (s/inst lost)", color="#e76f51")
        ax.bar(x + 0.25, net, 0.25, label="net gain vs always-D (incl. observation)", color="#264653")
        ax.axhline(0, color="k", lw=0.6)
        ax.set_xticks(x)
        ax.set_xticklabels([r["name"] for r in rows], fontsize=8)
        ax.set_ylabel("seconds per instance (dev 401, OOF)")
        ax.legend(fontsize=7)
        fig.tight_layout()
        fig.savefig(os.path.join(REP, "figures", "gain_decomposition.png"), dpi=130)
        L += ["![收益分解](figures/gain_decomposition.png)", ""]
    except ImportError:
        pass
    open(os.path.join(REP, "SELECTION_TABLES.md"), "w").write("\n".join(L) + "\n")
    meta = {"folds": {n: r["folds"] for n, r in res_all.items()}, "promoted": promoted}
    json.dump(meta, open(os.path.join(RES, "selection_meta.json"), "w"), indent=1, default=str)
    print("\n".join(L))

    if a.export:
        os.makedirs(FROZEN, exist_ok=True)
        allt = np.ones(D.n, bool)
        ffold = MP5.balanced_folds(D.fam, 3, SEED, "final")
        final_inner = np.array([ffold[f] for f in D.fam])
        check = {}
        smap = {}
        for name in promoted:
            p, rd = [(pp, rr) for (pp, rr) in COMPARISONS if cname(pp, rr) == name][0]
            P = PK[p]
            fit, pred, hps, _ = READERS[rd]
            mism = 0
            tag = name.replace("|", "_")
            for fd in res_all[name]["folds"]:
                k = fd["fold"]
                r = fit(fd["hp"], P, (D.outer != k) & P["consulted"], D.fam)
                obj = {"name": f"{tag}_fold{k}", "package": p, "reader": strip_reader(r, fd["theta"])}
                path = os.path.join(FROZEN, f"{tag}_fold{k}.json")
                json.dump(obj, open(path, "w"))
                for i in np.nonzero(D.outer == k)[0]:
                    smap.setdefault(D.h[i], []).append(os.path.relpath(path, ROOT))
                    if not P["consulted"][i]:
                        continue
                    f = v6lib.features(p, D.obs6[i], D.sz[i])
                    act, _ = v6lib.decide(obj["reader"], f, float(P["o"][i]))
                    mism += ACTS.index(act) != res_all[name]["choice"][i]
            hp, th = inner_select(rd, P, allt, final_inner, D.fam)
            r = fit(hp, P, P["consulted"], D.fam)
            json.dump({"name": f"{tag}_final", "package": p, "reader": strip_reader(r, th),
                       "source": "fit on all dev 401; hyperparameters by 3-fold family CV on dev"},
                      open(os.path.join(FROZEN, f"{tag}_final.json"), "w"))
            check[name] = {"fold_model_mismatches": int(mism), "final_hp": hp, "final_theta": th}
            print(name, "fold-model choice mismatches", mism, "final", hp, th)
        json.dump(smap, open(os.path.join(FROZEN, "strategy_map_dev.json"), "w"), indent=0)
        json.dump(check, open(os.path.join(RES, "export_check.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
