#!/usr/bin/env python3
"""V2 feature screen of goal v5 (protocol section 7, OBSERVATION_SCREEN.md).

  $FP_PY scripts/observations_v5/v5screen.py

For every new feature of R01-R10 (S28 excluded): missing rate on the
instances where the reader is consulted, the package's observation CPU,
medians by advantage group, Spearman rho with r_Fp = log2((C_F+ + 1)/(C_D + 1))
and r_Fm (instances with at least one solve, fixed runs without observation),
family-demeaned (within-family) rho, family cluster bootstrap CI (1,000),
Kruskal-Wallis across the three advantage groups, Benjamini-Hochberg q over
all tests. Descriptive only: no selection rule depends on it.
Writes results/observations_v5/screen.csv and reports/observations_v5/SCREEN_TABLES.md.
"""

import collections
import csv
import math
import os
import sys

import numpy as np
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "three_way"))
import baseline_profile as BP  # noqa: E402
import obsfeat  # noqa: E402
import v5data as VD  # noqa: E402

ROOT = VD.ROOT
RES = os.path.join(ROOT, "results", "observations_v5")
REP = os.path.join(ROOT, "reports", "observations_v5")
SEED = 20261023
GROUPS = ("D-adv", "Fp-adv", "Fm-adv", "close", "all-timeout")
PK_ITEMS = {"R01": "A01–A05 A07 A09–A11 C01 C02", "R02": "B01–B05 B07 B10", "R03": "D01–D03 D07 C04",
            "R04": "D04 D05 D10 A12", "R05": "F01 F03 F04 F08 F10–F12", "R06": "E01 E05–E07 E09 E11 C08 (0.2 s)",
            "R07": "E02 E05–E07 E09 E11 C08 (0.5 s)", "R08": "E03 E04 E05 E09 (512 冲突)", "R09": "G01–G04 G06"}


def bh(p):
    p = np.asarray(p, float)
    ok = ~np.isnan(p)
    q = np.full_like(p, np.nan)
    idx = np.nonzero(ok)[0]
    order = idx[np.argsort(p[idx])]
    m = len(order)
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, p[i] * m / rank)
        q[i] = prev
    return q


_RESAMPLES = None


def resamples(fam, n=1000):
    global _RESAMPLES
    if _RESAMPLES is None:
        fams = sorted(set(fam))
        by = collections.defaultdict(list)
        for i, f in enumerate(fam):
            by[f].append(i)
        rng = np.random.default_rng(SEED)
        _RESAMPLES = [np.array([i for k in rng.integers(0, len(fams), len(fams)) for i in by[fams[k]]]) for _ in range(n)]
    return _RESAMPLES


def boot_ci(x, y, fam, n=1000):
    vals = []
    for idx in resamples(fam, n):
        xx, yy = x[idx], y[idx]
        ok = ~(np.isnan(xx) | np.isnan(yy))
        if ok.sum() >= 8 and np.std(xx[ok]) > 0:
            vals.append(stats.spearmanr(xx[ok], yy[ok]).correlation)
    if len(vals) < 50:
        return float("nan"), float("nan")
    return float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))


def main():
    D = VD.Dev()
    c = D.c0
    rFp = np.log2((c[:, 1] + 1) / (c[:, 0] + 1))
    rFm = np.log2((c[:, 2] + 1) / (c[:, 0] + 1))
    solved_any = D.solved.any(1)
    grp = np.array(D.group)
    fam = np.array(D.fam)
    rows = []
    seen = set()
    for pkg in ["R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09"]:
        P = D.package(pkg)
        cpu = float(np.median(P["o"]))
        for j, name in enumerate(P["names"]):
            if name in obsfeat.S28 or name in seen:
                continue
            seen.add(name)
            x = np.where(P["consulted"], P["X"][:, j], np.nan)
            miss = float(np.isnan(x[P["consulted"]]).mean())
            r = {"package": pkg, "feature": name, "missing": miss, "pkg_obs_cpu_median": cpu}
            for g in GROUPS:
                v = x[(grp == g) & ~np.isnan(x)]
                r[f"med_{g}"] = float(np.median(v)) if len(v) else float("nan")
            adv = [x[(grp == g) & ~np.isnan(x)] for g in GROUPS[:3]]
            try:
                r["kw_p"] = float(stats.kruskal(*adv).pvalue) if all(len(v) >= 5 for v in adv) and \
                    np.std(np.concatenate(adv)) > 0 else float("nan")
            except ValueError:
                r["kw_p"] = float("nan")
            sel = solved_any & ~np.isnan(x)
            for tag, y in (("Fp", rFp), ("Fm", rFm)):
                if sel.sum() >= 20 and np.std(x[sel]) > 0:
                    sr = stats.spearmanr(x[sel], y[sel])
                    r[f"rho_{tag}"], r[f"p_{tag}"] = float(sr.correlation), float(sr.pvalue)
                    wx = BP.within_family(np.where(sel, x, np.nan), list(fam))
                    wy = BP.within_family(np.where(sel, y, np.nan), list(fam))
                    ok = ~(np.isnan(wx) | np.isnan(wy))
                    r[f"rho_{tag}_within"] = float(stats.pearsonr(wx[ok], wy[ok])[0]) if ok.sum() >= 20 and np.std(wx[ok]) > 0 else float("nan")
                    lo, hi = boot_ci(np.where(sel, x, np.nan), np.where(sel, y, np.nan), list(fam))
                    r[f"ci_{tag}_lo"], r[f"ci_{tag}_hi"] = lo, hi
                else:
                    for k in ("rho_", "p_", "ci_"):
                        pass
                    r[f"rho_{tag}"] = r[f"p_{tag}"] = r[f"rho_{tag}_within"] = float("nan")
                    r[f"ci_{tag}_lo"] = r[f"ci_{tag}_hi"] = float("nan")
            rows.append(r)
    pall = [r[f"p_{t}"] for r in rows for t in ("Fp", "Fm")]
    qall = bh(pall)
    for k, r in enumerate(rows):
        r["q_Fp"], r["q_Fm"] = float(qall[2 * k]), float(qall[2 * k + 1])
        for t in ("Fp", "Fm"):
            rho, w, lo, hi, qq = r[f"rho_{t}"], r[f"rho_{t}_within"], r[f"ci_{t}_lo"], r[f"ci_{t}_hi"], r[f"q_{t}"]
            r[f"consistent_{t}"] = int(not math.isnan(rho) and abs(rho) >= 0.1 and not math.isnan(w) and
                                       np.sign(w) == np.sign(rho) and not math.isnan(lo) and (lo > 0 or hi < 0) and qq < 0.1)
    with open(os.path.join(RES, "screen.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    ntests = sum(not math.isnan(p) for p in pall)
    L = ["# 特征筛查表（由 `scripts/observations_v5/v5screen.py` 生成）", "",
         f"新特征 {len(rows)} 个（R01–R09，S28 除外；R10/R11 的特征与 R01/R02/R06 相同）。相关检验共 {ntests} 个"
         f"（每个特征 × {{r_F+, r_F−}}），在至少一个动作解出的 {int(solved_any.sum())} 个 dev 实例上计算；"
         "q 为对全部检验的 Benjamini–Hochberg 校正。“一致”= |ρ| ≥ 0.1、家族内同号、家族 cluster bootstrap 区间不含 0、q < 0.1，仅为描述。", ""]
    L += ["## 1. 各观察包概况", "",
          "| 包 | 候选库项目 | 新特征 | 中位观察 CPU s | 缺失率中位 | |ρ| 最大（r_F+ / r_F−） | 一致的特征（F+ / F−） | KW p < 0.01 的特征 |",
          "|---|---|---:|---:|---:|---|---|---:|"]
    for pkg in PK_ITEMS:
        rs = [r for r in rows if r["package"] == pkg]
        if not rs:
            continue
        mp = max((abs(r["rho_Fp"]) for r in rs if not math.isnan(r["rho_Fp"])), default=float("nan"))
        mm = max((abs(r["rho_Fm"]) for r in rs if not math.isnan(r["rho_Fm"])), default=float("nan"))
        L.append(f"| {pkg} | {PK_ITEMS[pkg]} | {len(rs)} | {rs[0]['pkg_obs_cpu_median']:.3f} | "
                 f"{np.median([r['missing'] for r in rs]):.1%} | {mp:.2f} / {mm:.2f} | "
                 f"{sum(r['consistent_Fp'] for r in rs)} / {sum(r['consistent_Fm'] for r in rs)} | "
                 f"{sum(1 for r in rs if not math.isnan(r['kw_p']) and r['kw_p'] < 0.01)} |")
    L.append("")
    for t, lab in (("Fp", "r_F+（正 = F+ 比 D 慢）"), ("Fm", "r_F−（正 = F− 比 D 慢）")):
        top = sorted((r for r in rows if not math.isnan(r[f"rho_{t}"])), key=lambda r: -abs(r[f"rho_{t}"]))[:15]
        L += [f"## 2{'a' if t == 'Fp' else 'b'}. 与 {lab} 相关最强的 15 个新特征", "",
              "| 特征 | 包 | ρ | 95% 区间 | 家族内 ρ | q | 一致 | 中位：D 优势 / F+ 优势 / F− 优势 / 接近 / 全超时 | 缺失 |",
              "|---|---|---:|---|---:|---:|:-:|---|---:|"]
        for r in top:
            L.append(f"| `{r['feature']}` | {r['package']} | {r[f'rho_{t}']:+.2f} | [{r[f'ci_{t}_lo']:+.2f}, {r[f'ci_{t}_hi']:+.2f}] | "
                     f"{r[f'rho_{t}_within']:+.2f} | {r[f'q_{t}']:.3f} | {'✓' if r[f'consistent_{t}'] else ''} | "
                     + " / ".join(f"{r['med_' + g]:.3g}" for g in GROUPS) + f" | {r['missing']:.0%} |")
        L.append("")
    dead = [r["feature"] for r in rows if r["missing"] > 0.95]
    const = [r["feature"] for r in rows if math.isnan(r["rho_Fp"]) and r["missing"] <= 0.95]
    L += ["## 3. 无效或几乎无信息的特征", "",
          f"- 缺失率 > 95%：{', '.join('`' + x + '`' for x in dead) or '无'}。",
          f"- 在有解实例上为常数或样本不足、无法计算相关：{', '.join('`' + x + '`' for x in const) or '无'}。", ""]
    open(os.path.join(REP, "SCREEN_TABLES.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
