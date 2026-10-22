#!/usr/bin/env python3
"""S2: the 12 pre-listed selector candidates, family-grouped 5-fold CV on
dev, choice of one static and one probe selector, refit on all dev and
export for the wrapper (docs/THREE_WAY_PROTOCOL.md sections 4 and 8).

  $FP_PY scripts/three_way/twselect.py --kappa K [--export configs/three_way/frozen]

Reads results/three_way/winner_profiles.csv (dev only, written by
baseline_profile.py). Writes reports/three_way/SELECTOR_CV.md and
results/three_way/selector_cv.csv; with --export also the frozen model JSON.
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import twlib  # noqa: E402

ROOT = twlib.ROOT
ACTS = twlib.ACTION_ORDER
LBL = {"D": "D", "Fp": "F+", "Fm": "F−"}
T, PAR2 = 300.0, 600.0
SEED = 20261022
SENTINEL = -10.0
BUDGETS = (None, 0.1, 0.5, 2.0)
MODELS = ("tree1", "tree3", "logreg")
CANDIDATES = [(b, m) for b in BUDGETS for m in MODELS]  # 12, in protocol order


def rkey(*parts):
    return hashlib.sha256(":".join(map(str, (SEED,) + parts)).encode()).hexdigest()


def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


class Data:
    def __init__(self, rows, kappa):
        self.rows = rows
        self.n = len(rows)
        self.fam = [r["family_group"] for r in rows]
        self.split = [r["split"] for r in rows]
        self.kappa = kappa
        self.c = np.array([[fnum(r[f"cost_{a}"]) for a in ACTS] for r in rows])
        self.solved = np.array([[r[f"status_{a}"] == "solved" for a in ACTS] for r in rows])
        self.prof_cpu = np.array([fnum(r["profile_cpu"]) or 0.0 for r in rows])

    def features(self, budget):
        names = list(twlib.STATIC_FEATURES)
        cols = [[fnum(r[k]) for r in self.rows] for k in names]
        if budget is not None:
            tag = f"b{budget:g}"
            for k in twlib.PROBE_FEATURES:
                names.append(k)
                cols.append([fnum(r.get(f"{k}@{tag}")) for r in self.rows])
        X = np.array(cols, dtype=float).T  # None -> nan
        return names, X

    def sim_costs(self, budget):
        """Simulated wrapper cost per (instance, chosen action), protocol section 4."""
        o = self.prof_cpu + self.kappa
        probe_solved = np.zeros(self.n, bool)
        if budget is not None:
            tag = f"b{budget:g}"
            pc = np.array([fnum(r.get(f"probe_{tag}_cpu")) or budget for r in self.rows])
            o = o + pc
            probe_solved = np.array([r.get(f"probe_{tag}_solved") in ("1", 1) for r in self.rows])
        C = np.full((self.n, 3), PAR2)
        for j in range(3):
            ok = self.solved[:, j] & (o + self.c[:, j] <= T - twlib.RESERVE)
            C[ok, j] = o[ok] + self.c[ok, j]
        ps = probe_solved & (o <= T)
        C[ps, :] = o[ps, None]
        return C, o, probe_solved


# ------------------------------------------------------------------ models

def fit_tree(X, C, depth, min_leaf, names, max_thr=64):
    Xs = np.where(np.isnan(X), SENTINEL, X)

    def leaf(idx):
        return {"leaf": ACTS[int(np.argmin(C[idx].sum(0)))]}

    def build(idx, d):
        tot = C[idx].sum(0).min()
        if d == depth or len(idx) < 2 * min_leaf:
            return leaf(idx)
        best = None
        for f in range(X.shape[1]):
            x = Xs[idx, f]
            order = np.argsort(x, kind="mergesort")
            xs, cs = x[order], np.cumsum(C[idx][order], axis=0)
            total = cs[-1]
            pos = np.nonzero(xs[1:] != xs[:-1])[0] + 1  # split before position
            pos = pos[(pos >= min_leaf) & (pos <= len(idx) - min_leaf)]
            if not len(pos):
                continue
            if len(pos) > max_thr:
                pos = pos[np.unique(np.linspace(0, len(pos) - 1, max_thr).round().astype(int))]
            left = cs[pos - 1]
            val = left.min(1) + (total - left).min(1)
            k = int(np.argmin(val))
            if val[k] < tot - 1e-9 and (best is None or val[k] < best[0] - 1e-12):
                best = (val[k], f, (xs[pos[k] - 1] + xs[pos[k]]) / 2)
        if best is None:
            return leaf(idx)
        _, f, thr = best
        li = idx[Xs[idx, f] <= thr]
        ri = idx[Xs[idx, f] > thr]
        return {"feature": names[f], "threshold": float(thr), "missing_value": SENTINEL,
                "left": build(li, d + 1), "right": build(ri, d + 1)}

    return {"type": "tree", "root": build(np.arange(len(X)), 0)}


def fit_logreg(X, C, names, Cpen=0.1):
    from sklearn.linear_model import LogisticRegression
    best = C.argmin(1)
    srt = np.sort(C, 1)
    w = np.log2((srt[:, 1] + 1) / (srt[:, 0] + 1))
    keep = w > 1e-9
    med = np.nanmedian(np.where(np.isnan(X), np.nan, X), axis=0)
    med = np.where(np.isnan(med), 0.0, med)
    Xi = np.where(np.isnan(X), med, X)
    mu, sd = Xi.mean(0), Xi.std(0)
    sd = np.where(sd > 1e-12, sd, 1.0)
    Z = (Xi - mu) / sd
    classes = sorted(set(best[keep].tolist()))
    model = {"type": "logreg", "classes": [ACTS[k] for k in classes],
             "impute": dict(zip(names, map(float, med))), "mean": dict(zip(names, map(float, mu))),
             "scale": dict(zip(names, map(float, sd)))}
    if len(classes) == 0:
        return {"type": "const", "action": ACTS[int(np.argmin(C.sum(0)))]}
    if len(classes) == 1:
        return {"type": "const", "action": ACTS[classes[0]]}
    lr = LogisticRegression(C=Cpen, max_iter=10000)
    lr.fit(Z[keep], best[keep], sample_weight=w[keep])
    coef, icpt = lr.coef_, lr.intercept_
    if len(classes) == 2:  # sklearn returns one row for two classes
        coef = np.vstack([np.zeros_like(coef[0]), coef[0]])
        icpt = np.array([0.0, icpt[0]])
    model["coef"] = {ACTS[k]: dict(zip(names, map(float, coef[i]))) for i, k in enumerate(classes)}
    model["intercept"] = {ACTS[k]: float(icpt[i]) for i, k in enumerate(classes)}
    return model


def fit(kind, X, C, names):
    if kind == "tree1":
        return fit_tree(X, C, 1, 20, names)
    if kind == "tree3":
        return fit_tree(X, C, 3, 15, names)
    return fit_logreg(X, C, names)


def predict_all(model, X, names):
    out = []
    for i in range(len(X)):
        feats = {k: (None if np.isnan(X[i, j]) else float(X[i, j])) for j, k in enumerate(names)}
        out.append(twlib.predict(model, feats))
    return np.array([ACTS.index(a) for a in out])


def folds(fam, k=5):
    sizes = collections.Counter(fam)
    order = sorted(sizes, key=lambda g: (-sizes[g], rkey("fold", g)))
    load, of = [0] * k, {}
    for g in order:
        j = min(range(k), key=lambda j: (load[j], j))
        of[g] = j
        load[j] += sizes[g]
    return np.array([of[g] for g in fam])


def tree_text(node, ind=""):
    if "leaf" in node:
        return [f"{ind}→ {LBL[node['leaf']]}"]
    return ([f"{ind}if {node['feature']} ≤ {node['threshold']:.4g}:"] + tree_text(node["left"], ind + "    ")
            + [f"{ind}else:"] + tree_text(node["right"], ind + "    "))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kappa", type=float, required=True, help="wrapper Python CPU constant (s)")
    ap.add_argument("--profiles", default=os.path.join(ROOT, "results", "three_way", "winner_profiles.csv"))
    ap.add_argument("--export", default=None)
    a = ap.parse_args()
    rows = [r for r in csv.DictReader(open(a.profiles))]
    assert all(r["split"] in ("train", "val") for r in rows)
    D = Data(rows, a.kappa)
    fold = folds(D.fam)
    fixed = {act: D.c[:, j].mean() for j, act in enumerate(ACTS)}
    best_fixed = min(ACTS, key=lambda x: (fixed[x], ACTS.index(x)))
    bf = ACTS.index(best_fixed)
    res, oof_all = [], {}
    for b, m in CANDIDATES:
        names, X = D.features(b)
        C, o, ps = D.sim_costs(b)
        pred = np.zeros(D.n, int)
        for k in range(5):
            tr, te = fold != k, fold == k
            model = fit(m, X[tr], C[tr], names)
            pred[te] = predict_all(model, X[te], names)
        cost = C[np.arange(D.n), pred]
        trn = np.array([s == "train" for s in D.split])
        model_tr = fit(m, X[trn], C[trn], names)
        pv = predict_all(model_tr, X[~trn], names)
        val_cost = C[np.arange(D.n)[~trn], pv]
        oof_all[(b, m)] = (pred, cost)
        res.append({"budget": "static" if b is None else f"{b:g}", "model": m, "cv_par2": cost.mean(),
                    "cv_solved": int((cost < PAR2).sum()), "cv_vs_best_fixed_pct": 100 * (fixed[best_fixed] - cost.mean()) / fixed[best_fixed],
                    "cv_vs_D_pct": 100 * (fixed["D"] - cost.mean()) / fixed["D"],
                    "overhead_mean": o.mean(), "probe_solved": int(ps.sum()),
                    "choices": "/".join(str(int((pred == j).sum())) for j in range(3)),
                    "trainfit_val_par2": val_cost.mean(), "val_best_fixed_par2": D.c[~trn, bf].mean(),
                    "oracle_cv_par2": C.min(1).mean()})
    # choose
    cplx = {"tree1": 0, "tree3": 1, "logreg": 2}
    stat = [r for r in res if r["budget"] == "static"]
    prob = [r for r in res if r["budget"] != "static"]
    pick_s = min(stat, key=lambda r: (round(r["cv_par2"], 9), cplx[r["model"]]))
    pick_p = min(prob, key=lambda r: (round(r["cv_par2"], 9), cplx[r["model"]], float(r["budget"])))
    with open(os.path.join(ROOT, "results", "three_way", "selector_cv.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(res[0]))
        w.writeheader()
        w.writerows(res)

    # per-year / split breakdown of the picks
    def breakdown(key):
        b = None if key["budget"] == "static" else float(key["budget"])
        pred, cost = oof_all[(b, key["model"])]
        out = []
        for lab, sel in [("train", [s == "train" for s in D.split]), ("val", [s == "val" for s in D.split])] + \
                [(y, [r["year"] == y for r in rows]) for y in ("2022", "2023", "2024", "2025", "2026")]:
            sel = np.array(sel)
            out.append((lab, int(sel.sum()), cost[sel].mean(), D.c[sel, bf].mean(), D.c[sel, 0].mean()))
        return out

    L = ["# S2：选择器候选的家族分组交叉验证（dev）", "",
         f"由 `scripts/three_way/twselect.py --kappa {a.kappa}` 生成。dev = train + val（{D.n} 实例），"
         f"按家族组 5 折（seed {SEED}）。cost 为离线模拟的 wrapper 成本（[协议](../../docs/THREE_WAY_PROTOCOL.md) 第 4 节）："
         f"静态特征 CPU + 试跑 CPU + κ = {a.kappa} s，再加所选动作在完整运行中的 CPU（若总和 ≤ 300 s 且该运行解出），否则 600。", "",
         "固定动作（无观察开销）：" + "，".join(f"{LBL[x]} {fixed[x]:.2f}" for x in ACTS) +
         f"；dev 上最佳固定动作 = **{LBL[best_fixed]}**。",
         f"hindsight oracle（无开销）：{D.c.min(1).mean():.2f}。", "",
         "| # | 输入 | 模型 | CV mean PAR2 | CV solved | 相对最佳固定 | 相对 D | 平均开销 s | 试跑解出 | 选择 D/F+/F− | train 拟合 → val PAR2（val 上最佳固定） |",
         "|---:|---|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for i, r in enumerate(res, 1):
        mark = " **(选中)**" if r is pick_s or r is pick_p else ""
        L.append(f"| {i} | {'静态' if r['budget'] == 'static' else '静态 + 试跑 ' + r['budget'] + ' s'} | {r['model']}{mark} | "
                 f"{r['cv_par2']:.2f} | {r['cv_solved']} | {r['cv_vs_best_fixed_pct']:+.1f}% | {r['cv_vs_D_pct']:+.1f}% | "
                 f"{r['overhead_mean']:.3f} | {r['probe_solved']} | {r['choices']} | {r['trainfit_val_par2']:.2f} ({r['val_best_fixed_par2']:.2f}) |")
    L += ["", "相对值为 PAR2 降低百分比（正 = 更好）。“train 拟合 → val”是辅助诊断（只在 train 上拟合，在 val 上评估），不参与选择。", ""]
    for title, pk in (("静态选择器", pick_s), ("试跑选择器", pick_p)):
        L += [f"### 选中的{title}：{pk['model']}（{'静态' if pk['budget'] == 'static' else '试跑 ' + pk['budget'] + ' s'}）", "",
              "| 子集 | n | CV PAR2 | 最佳固定 PAR2 | D PAR2 |", "|---|---:|---:|---:|---:|"]
        for lab, n_, cp, bfp, dp in breakdown(pk):
            L.append(f"| {lab} | {n_} | {cp:.2f} | {bfp:.2f} | {dp:.2f} |")
        L.append("")

    if a.export:
        os.makedirs(a.export, exist_ok=True)
        frozen = {}
        for name, pk in (("static", pick_s), ("probe", pick_p)):
            b = None if pk["budget"] == "static" else float(pk["budget"])
            names, X = D.features(b)
            C, _, _ = D.sim_costs(b)
            model = fit(pk["model"], X, C, names)
            obj = {"name": f"tw_{name}", "kind": "static" if b is None else "probe", "candidate": pk["model"],
                   "budget": b, "features": names, "model": model, "kappa_used_in_cv": a.kappa,
                   "cv_par2": pk["cv_par2"], "trained_on": f"dev (train+val, {D.n} instances)"}
            if b is None:
                obj.pop("budget")
            path = os.path.join(a.export, f"{name}.json")
            json.dump(obj, open(path, "w"), indent=1)
            frozen[name] = (path, model)
            pred = predict_all(model, X, names)
            L += [f"### 冻结的{('静态' if name == 'static' else '试跑')}模型（在全部 dev 上重新拟合）", "",
                  f"- 文件 `{os.path.relpath(path, ROOT)}`；dev 上（in-sample）选择 D/F+/F− = "
                  + "/".join(str(int((pred == j).sum())) for j in range(3)) + "。"]
            if model["type"] == "tree":
                L += ["", "```"] + tree_text(model["root"]) + ["```"]
            elif model["type"] == "logreg":
                top = sorted(((abs(w_), k, c_) for c_ in model["coef"] for k, w_ in model["coef"][c_].items()), reverse=True)[:10]
                L += ["", "绝对值最大的 10 个标准化系数：" + "，".join(f"{LBL[c_]}·{k} {model['coef'][c_][k]:+.2f}" for _, k, c_ in top)]
            else:
                L += ["", f"常数：{model.get('action')}"]
            L.append("")
        json.dump({"action": best_fixed, "dev_par2": fixed}, open(os.path.join(a.export, "best_fixed.json"), "w"), indent=1)
        L += [f"最佳固定动作 `{os.path.relpath(os.path.join(a.export, 'best_fixed.json'), ROOT)}`：{LBL[best_fixed]}。", ""]
    open(os.path.join(ROOT, "reports", "three_way", "SELECTOR_CV.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
