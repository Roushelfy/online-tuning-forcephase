#!/usr/bin/env python3
"""R2 observation analysis on dev 401 (protocol section 3; descriptive, every
pattern is a development hypothesis):

  $FP_PY scripts/stable_selection_v6/r2_observations.py

1. completion and CPU of every input package, by size stratum;
2. local-search start differences: by v4 advantage group (seed 0), and for the
   R1 stable-advantage instances versus size-matched D-advantage instances
   (nearest log #clauses, different family), with size- and family-controlled
   rank correlations (Spearman of rank residuals after regressing on
   p_log_clauses; family-demeaned ranks);
3. SATzilla subset: coverage, reserved values, overlap with S28 / v5 features.
Writes reports/stable_selection_v6/OBSERVATIONS_TABLES.md, figures/ls_differences.png,
results/stable_selection_v6/obs_coverage.csv.
"""

import collections
import csv
import json
import math
import os
import sys

import numpy as np
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "three_way"))
import baseline_profile as BP  # noqa: E402
import v6data as V6D  # noqa: E402
import v6lib  # noqa: E402

ROOT = v6lib.ROOT
RES = os.path.join(ROOT, "results", "stable_selection_v6")
REP = os.path.join(ROOT, "reports", "stable_selection_v6")
GL = {"D-adv": "D 优势", "Fp-adv": "F+ 优势", "Fm-adv": "F− 优势", "close": "接近", "all-timeout": "全部超时"}
KEY_LS = ["l6_dbest_01", "l6_dbest_0r", "l6_dbest_1r", "l6_ddesc_01", "l6_ddens_01", "l6_agree_01",
          "l6_desc_zero", "l6_desc_one", "l6_best_zero", "l6_best_one"]


def rank_resid(x, z):
    """Ranks of x with the linear effect of the ranks of z removed."""
    ok = ~(np.isnan(x) | np.isnan(z))
    out = np.full_like(x, np.nan)
    rx, rz = stats.rankdata(x[ok]), stats.rankdata(z[ok])
    b = np.polyfit(rz, rx, 1)
    out[ok] = rx - np.polyval(b, rz)
    return out


def main():
    os.makedirs(os.path.join(REP, "figures"), exist_ok=True)
    D = V6D.Dev6()
    man = {r["hash"]: r for r in csv.DictReader(open(os.path.join(ROOT, "results", "three_way", "manifest.csv")))}
    strat = np.array([man[h]["stratum"] for h in D.h])
    L = ["# R2 观测表（dev 401；由 `scripts/stable_selection_v6/r2_observations.py` 生成）", ""]
    # 1. completion
    cov = []
    L += ["## 1. 各输入包的观察完成率与 CPU", "",
          "| 包 | 内容 | 完成率 | 小 / 中 / 大 规模完成率 | 观察 CPU 中位 s | p90 | 最大 |", "|---|---|---:|---|---:|---:|---:|"]
    desc = {"P1": "S28", "P2": "S28 + LS6（W = 50,000）", "P3": "S28 + SATzilla（ncnf-constraints, ncnf-rwh, unit）",
            "PLS": "规则 R-LS 的输入（同 P2 观测）", "PSYM": "规则 R-SYM 的输入（resid, bilat, graph）"}
    PK = {}
    for p in ("P1", "P2", "P3", "PLS", "PSYM"):
        P = D.package(p)
        PK[p] = P
        c = P["consulted"]
        by = " / ".join(f"{c[strat == s].mean():.0%}" for s in ("small", "mid", "large"))
        o = P["o"]
        L.append(f"| {p} | {desc[p]} | {c.mean():.0%} | {by} | {np.median(o):.3f} | {np.quantile(o, .9):.3f} | {o.max():.2f} |")
        cov.append({"package": p, "completion": c.mean(), **{f"completion_{s}": c[strat == s].mean() for s in ("small", "mid", "large")},
                    "cpu_median": float(np.median(o)), "cpu_p90": float(np.quantile(o, .9)), "cpu_max": float(o.max())})
    ls_status = collections.Counter((ob["sections"].get("ls") or {}).get("status") for ob in D.obs6)
    sz_status = collections.Counter((s or {}).get("status") for s in D.sz)
    L += ["", f"obsprofile6 局部搜索段状态：{dict(ls_status)}；SATzilla 子集状态：{dict(sz_status)}。"
          "观察不完整的实例不咨询读出器，直接选 D，观察 CPU 照常计费。", ""]
    with open(os.path.join(RES, "obs_coverage.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cov[0]))
        w.writeheader()
        w.writerows(cov)
    # 2. LS differences
    P = PK["P2"]
    col = {n: j for j, n in enumerate(P["names"])}
    X = np.where(P["consulted"][:, None], P["X"], np.nan)
    grp = np.array(D.group)
    c = D.c0
    rFp = np.log2((c[:, 1] + 1) / (c[:, 0] + 1))
    rFm = np.log2((c[:, 2] + 1) / (c[:, 0] + 1))
    size = np.array([float(man[h]["log10_clauses"]) for h in D.h])
    solved_any = D.solved.any(1)
    L += ["## 2. 局部搜索三个起点的差异", "", "### 2.1 按 v4 单 seed 优势组的中位数（dev 401，观察完成的实例）", "",
          "| 特征 | D 优势 | F+ 优势 | F− 优势 | 接近 | 全部超时 |", "|---|---:|---:|---:|---:|---:|"]
    for k in KEY_LS:
        j = col[k]
        L.append(f"| `{k}` | " + " | ".join(f"{np.nanmedian(X[grp == g, j]):.3g}" for g in GL) + " |")
    L += ["", "### 2.2 与 r_F± = log2((C_F± + 1)/(C_D + 1)) 的秩相关（至少一个动作解出的实例）", "",
          "“控制规模”= 两边都对 log10(子句数) 的秩做线性回归后取残差；“家族内”= 家族内去均值的秩。", "",
          "| 特征 | r_F+：总体 / 控制规模 / 家族内 | r_F−：总体 / 控制规模 / 家族内 |", "|---|---|---|"]
    corr_rows = []
    for k in KEY_LS:
        x = X[:, col[k]]
        cells = []
        for y in (rFp, rFm):
            sel = solved_any & ~np.isnan(x)
            r0 = stats.spearmanr(x[sel], y[sel]).correlation
            rx, ry = rank_resid(np.where(sel, x, np.nan), size), rank_resid(np.where(sel, y, np.nan), size)
            ok = ~(np.isnan(rx) | np.isnan(ry))
            r1 = stats.pearsonr(rx[ok], ry[ok])[0]
            wx = BP.within_family(np.where(sel, x, np.nan), D.fam)
            wy = BP.within_family(np.where(sel, y, np.nan), D.fam)
            ok = ~(np.isnan(wx) | np.isnan(wy))
            r2 = stats.pearsonr(wx[ok], wy[ok])[0] if ok.sum() > 10 and np.std(wx[ok]) > 0 else float("nan")
            cells.append(f"{r0:+.2f} / {r1:+.2f} / {r2:+.2f}")
            corr_rows.append((k, r0, r1, r2))
        L.append(f"| `{k}` | {cells[0]} | {cells[1]} |")
    # R1 stable instances vs size-matched D-adv
    stab = json.load(open(os.path.join(RES, "stability.json")))["stable"] if os.path.exists(os.path.join(RES, "stability.json")) else {}
    idx = {h: i for i, h in enumerate(D.h)}
    dadv = [i for i in range(D.n) if grp[i] == "D-adv" and P["consulted"][i]]
    pairs = []
    for h, a in stab.items():
        if a not in ("Fp", "Fm") or h not in idx or not P["consulted"][idx[h]]:
            continue
        i = idx[h]
        cand = [j for j in dadv if D.fam[j] != D.fam[i]]
        j = min(cand, key=lambda j: abs(size[j] - size[i]))
        pairs.append((a, i, j))
    L += ["", "### 2.3 R1 中稳定的 F+/F− 优势题与规模最接近的 D 优势题（不同家族）的配对差", "",
          f"共 {len(pairs)} 对（R1 稳定优势题中观察完成的）。差 = 稳定 F± 题 − 配对 D 优势题。", "",
          "| 动作 | 稳定题（家族） | 配对 D 优势题（家族） | Δlog10 子句数 | " + " | ".join(f"Δ`{k}`" for k in KEY_LS[:6]) + " |",
          "|---|---|---|---:|" + "---:|" * 6]
    for a, i, j in pairs:
        L.append(f"| {'F+' if a == 'Fp' else 'F−'} | {D.h[i][:8]}（{D.fam[i]}） | {D.h[j][:8]}（{D.fam[j]}） | {size[i] - size[j]:+.2f} | "
                 + " | ".join(f"{X[i, col[k]] - X[j, col[k]]:+.3g}" for k in KEY_LS[:6]) + " |")
    if pairs:
        for a in ("Fp", "Fm"):
            pp = [(i, j) for b, i, j in pairs if b == a]
            if len(pp) >= 3:
                L.append("")
                L.append(f"{'F+' if a == 'Fp' else 'F−'}：{len(pp)} 对；各差值同号的比例："
                         + "，".join(f"`{k}` {max(np.mean([X[i, col[k]] > X[j, col[k]] for i, j in pp]), np.mean([X[i, col[k]] < X[j, col[k]] for i, j in pp])):.0%}"
                                    for k in KEY_LS[:6]) + "（小样本，仅描述）。")
    L.append("")
    # figure
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        ks = ["l6_dbest_01", "l6_ddesc_01", "l6_desc_zero", "l6_desc_one"]
        fig, axs = plt.subplots(1, len(ks), figsize=(14, 3.6))
        for ax, k in zip(axs, ks):
            data = [X[grp == g, col[k]][~np.isnan(X[grp == g, col[k]])] for g in GL]
            ax.boxplot(data, tick_labels=["D-adv", "F+-adv", "F--adv", "close", "all-TO"], showfliers=False)
            for t, g in enumerate(GL):
                v = data[t]
                ax.plot(np.full(len(v), t + 1) + np.random.default_rng(0).uniform(-0.15, 0.15, len(v)), v, ".", ms=2, alpha=0.4)
            ax.set_title(k, fontsize=9)
            ax.tick_params(axis="x", labelsize=7)
        fig.suptitle("Local-search start differences by v4 advantage group (dev 401, seed-0 labels)", fontsize=9)
        fig.tight_layout()
        fig.savefig(os.path.join(REP, "figures", "ls_differences.png"), dpi=130)
        L += ["![局部搜索差异](figures/ls_differences.png)", ""]
    except ImportError:
        pass
    # 3. SATzilla registration
    names = sorted({k for s in D.sz if s for k in s["features"]})
    usable = [n for n in names if v6lib.sz_usable(n)]
    reserved = collections.Counter()
    for s in D.sz:
        if s and s.get("status") == "ok":
            for k, v in s["features"].items():
                reserved[k] += v is None
    nok = sum(1 for s in D.sz if s and s.get("status") == "ok")
    always_res = [k for k in usable if reserved[k] == nok]
    L += ["## 3. SATzilla 子集的登记", "",
          f"- 输出 {len(names)} 列，进入模型 {len(usable)} 列（去掉计时类与 `solved`）；在 {nok} 个完成的 dev 实例上全为保留值（未计算）的列：{len(always_res)}。",
          "- 与旧特征的重叠：`unit` 组的 `vars-reduced-depth-*` 与 v5 B07（统一符号贪心路径的赋值覆盖）同类，都是“按深度做单位传播后变量减少的比例”，"
          "但 SATzilla 用随机变量顺序、对正负两侧取平均，不区分方向；`ncnf-constraints` 与 v5 A07（恰一约束）和 C05（门结构，v5 未实施）相关，"
          "统计 AND/OR/XOR 等约束节点的度分布；`ncnf-rwh` 是递归权重启发式（与 A01/A02 的 JW 加权同类思路，但按递归迭代）。"
          "S28 中只有规模与子句长度统计与之直接重复。",
          ""]
    open(os.path.join(REP, "OBSERVATIONS_TABLES.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
