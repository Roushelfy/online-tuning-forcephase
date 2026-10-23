#!/usr/bin/env python3
"""Tables and figures of SELECTION_AND_ABLATION.md from v5select.py's state
(protocol sections 6, 7 and 9: comparisons, increments, fallback curves,
OOD split, strategy choice).

  $FP_PY scripts/observations_v5/v5report.py

Writes reports/observations_v5/SELECTION_TABLES.md, figures/*.png,
results/observations_v5/{ablation.csv, fallback.csv, strategies.json}.
"""

import collections
import csv
import json
import math
import os
import pickle
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v5data as VD  # noqa: E402
import v5select as VS  # noqa: E402

ROOT = VD.ROOT
RES, REP = VS.RES, VS.REP
FIG = os.path.join(REP, "figures")
GL = {"D-adv": "D 优势", "Fp-adv": "F+ 优势", "Fm-adv": "F− 优势", "close": "接近", "all-timeout": "全部超时"}
PKG_DESC = {"S28": "v4 静态 28 项（对照）", "R00": "v4 静态 + D 0.1 s 试跑（v4 输入）", "R01": "加权极性 + 根传播残余式",
            "R02": "双边传播 + 贪心路径", "R03": "蕴含图 / 组件 / 等价", "R04": "社区 / 符号配对 / WL",
            "R05": "D 2 s 相位轨迹", "R06": "三动作各 0.2 s", "R07": "三动作各 0.5 s", "R08": "三动作各 512 冲突",
            "R09": "局部搜索", "R10": "R01 + R02 + R06", "R11": "R10 静态 + 有条件 R06"}


def fmt_pct(r):
    return f"{r['gain_pct']:+.1f}% [{r['gain_pct_lo']:+.1f}, {r['gain_pct_hi']:+.1f}]"


def main():
    st = pickle.load(open(os.path.join(RES, "selection_state.pkl"), "rb"))
    rows, oof, meta = st["rows"], st["oof"], st["meta"]
    R = {r["name"]: r for r in rows}
    D = VD.Dev(kappa=meta["kappa"])
    boot = VS.Boot(D.fam)
    c0 = D.c0[:, 0]
    os.makedirs(FIG, exist_ok=True)
    L = ["# 选择与消融表（由 `scripts/observations_v5/v5report.py` 生成）", ""]

    # ------------------------------------------------ 1. registered comparisons
    reg = [r for r in rows if r["reader"] in ("RG", "TG", "RF") and r["package"] not in ("S28",)]
    L += ["## 1. 登记的比较（外层 5 折 OOF，dev 401）", "",
          f"始终 D（不观察）PAR2 = {R['always-D']['par2']:.2f}；事后最优 {R['oracle']['par2']:.2f}（{fmt_pct(R['oracle'])}）。"
          "净收益 = 始终 D 的成本 − 策略成本（含全部观察 CPU），正 = 更好；区间为家族 cluster bootstrap 95%（10,000 次）。"
          "精度 = 偏离 D 的题中、比同一观察后选 D 更好的比例；错误偏离 = 这些题多付的秒数 / 401；严重回退 = D 在截止前解出而策略超时，或单题多付 ≥ 100 s。", "",
          "| 包 | 内容 | 读出器 | PAR2 | 净收益（相对 D） | 偏离 F+/F− | 精度 | 正确偏离 s/题 | 错误偏离 s/题 | 严重回退 | 前 10 题占正收益 | 平均观察 CPU s |",
          "|---|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in sorted(reg, key=lambda r: (["R00"] + VD.PKGS).index(r["package"]) * 10 + ["RG", "TG", "RF"].index(r["reader"])):
        L.append(f"| {r['package']} | {PKG_DESC[r['package']]} | {r['reader']} | {r['par2']:.2f} | {fmt_pct(r)} | {r['dev_Fp']}/{r['dev_Fm']} | "
                 f"{r['precision']:.2f} | {r['right_gain']:.2f} | {r['wrong_loss']:.2f} | {r['severe']} | "
                 f"{r['top10_share']:.0%} | {r['obs_cpu']:.2f} |")
    n_reg = len([r for r in reg if r["package"] != "R00"])
    L += ["", f"登记比较 {n_reg} 个（R01–R11 × RG/TG = 22，加上 R00 × RG/TG = 2，以及晋级包上的 RF {len([r for r in reg if r['reader'] == 'RF'])} 个）。"
          f"晋级（按 RG/TG 较好者的 OOF 净收益）：{', '.join(meta['promoted'])}。", ""]
    # ------------------------------------------------ 2. controls
    ctl = [r for r in rows if r.get("control") or r["name"] in ("always-D", "oracle")]
    L += ["## 2. 对照", "", "| 名称 | PAR2 | 净收益 | 偏离 F+/F− | 精度 | 严重回退 |", "|---|---:|---|---|---:|---:|"]
    for r in ctl:
        prec = "" if math.isnan(r["precision"]) else f"{r['precision']:.2f}"
        L.append(f"| {r['name']} | {r['par2']:.2f} | {fmt_pct(r)} | {r['dev_Fp']}/{r['dev_Fm']} | {prec} | {r['severe']} |")
    L += ["", "`v4static|v4-logreg` 与 `R00|v4-logreg` 应与 v4 的 [SELECTOR_CV](../three_way/SELECTOR_CV.md) 完全相同（392.95 与 387.28）。", ""]

    # ------------------------------------------------ 3. ablations
    ab = []
    L += ["## 3. 消融", "", "### 3.1 新观测是否有增量：同一读出器下，包 P 相对“只有 S28”", "",
          "差值 = S28 成本 − 包 P 成本（秒/题，正 = 包 P 更好），配对家族 cluster bootstrap 95% 区间。", "",
          "| 包 | RG：差值 [区间] | TG：差值 [区间] |", "|---|---|---|"]
    for p in ["R00"] + VD.PKGS:
        cells = []
        for rd in ("RG", "TG"):
            a, b = oof.get(f"{p}|{rd}"), oof.get(f"S28|{rd}")
            if not a or not b:
                cells.append("—")
                continue
            m, lo, hi = VS.paired(a[0]["cost"], b[0]["cost"], boot)
            cells.append(f"{m:+.2f} [{lo:+.2f}, {hi:+.2f}]{' *' if lo > 0 or hi < 0 else ''}")
            ab.append({"test": "observation_increment", "package": p, "reader": rd, "diff": m, "lo": lo, "hi": hi})
        L.append(f"| {p} | {cells[0]} | {cells[1]} |")
    L += ["", "`*` = 区间不含 0。", "", "### 3.2 决策方式是否改善：同一输入上，新读出器相对 v4 旧读出器", "",
          "差值 = 旧读出器成本 − 新读出器成本（正 = 新读出器更好）。RG 对 v4 logistic（都是线性），TG 对 v4 深度 3 成本树（都是树）。", "",
          "| 包 | RG − v4-logreg | TG − v4-tree3 | TG − v4-tree1 |", "|---|---|---|---|"]
    for p in ["S28"] + VD.PKGS:
        if p == "R11":
            continue
        cells = []
        for new, old in (("RG", "v4-logreg"), ("TG", "v4-tree3"), ("TG", "v4-tree1")):
            a, b = oof.get(f"{p}|{new}"), oof.get(f"{p}|{old}")
            if not a or not b:
                cells.append("—")
                continue
            m, lo, hi = VS.paired(a[0]["cost"], b[0]["cost"], boot)
            cells.append(f"{m:+.2f} [{lo:+.2f}, {hi:+.2f}]{' *' if lo > 0 or hi < 0 else ''}")
            ab.append({"test": "reader_vs_old", "package": p, "reader": f"{new}-vs-{old}", "diff": m, "lo": lo, "hi": hi})
        L.append(f"| {p} | " + " | ".join(cells) + " |")
    L.append("")
    with open(os.path.join(RES, "ablation.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ab[0]))
        w.writeheader()
        w.writerows(ab)

    # ------------------------------------------------ 4. strategy choice (protocol section 9)
    cand = [r for r in reg if r["package"] in VD.PKGS]
    s1 = max(cand, key=lambda r: (round(r["gain"], 9), -r["obs_cpu"]))
    other = VS.PROBE_PKGS if s1["package"] in VS.STATIC_PKGS else VS.STATIC_PKGS
    s2 = max((r for r in cand if r["package"] in other), key=lambda r: (round(r["gain"], 9), -r["obs_cpu"]))
    strategies = {"S1": s1["name"], "S2": s2["name"]}
    json.dump(strategies, open(os.path.join(RES, "strategies.json"), "w"), indent=1)
    L += ["## 4. 主要策略（协议第 9 节规则）", "",
          f"- **S1** = 全部登记比较中 OOF 净收益最高者：`{s1['name']}`，{fmt_pct(s1)}，PAR2 {s1['par2']:.2f}。",
          f"- **S2** = 观察类型与 S1 相反（{'含试跑' if s1['package'] in VS.STATIC_PKGS else '纯静态'}）的组合中最好者：`{s2['name']}`，{fmt_pct(s2)}，PAR2 {s2['par2']:.2f}。",
          "- 两者的净收益" + ("都不显著大于 0（区间含 0 或为负）" if s1["gain_lo"] <= 0 and s2["gain_lo"] <= 0 else "中有区间不含 0 的") +
          "；按协议仍部署两者，以检验真实开销与回退行为。", ""]

    # ------------------------------------------------ 5. fallback curves
    fb = []
    L += ["## 5. 默认回退曲线（各折的其他超参数固定，统一扫描 θ）", "",
          "| 策略 | θ | 净收益 % | 偏离率 | 严重回退 |", "|---|---:|---:|---:|---:|"]
    fig_data = {}
    for key in (s1["name"], s2["name"]) + tuple(f"{p}|RG" for p in ("R01", "R07", "R10")):
        if key not in oof or "G" not in oof[key][0] or key.startswith("R11"):
            continue
        res, P = oof[key]
        G = res["G"]
        cons = P["consulted"]
        pts = []
        for th in VS.THETAS:
            ch = np.zeros(D.n, int)
            ch[cons] = VS.gate(G[cons], th)
            cost = P["C"][np.arange(D.n), ch]
            gain = 100 * (c0 - cost).mean() / c0.mean()
            dev = (ch != 0).mean()
            sev = int(((D.solved[:, 0] & (cost >= 600)) | (cost - c0 >= 100)).sum())
            pts.append((th, gain, dev, sev))
            fb.append({"strategy": key, "theta": "inf" if th is None else th, "gain_pct": gain, "dev_rate": dev, "severe": sev})
            if key in (s1["name"], s2["name"]):
                L.append(f"| {key} | {'∞' if th is None else f'{th:g}'} | {gain:+.1f}% | {dev:.1%} | {sev} |")
        fig_data[key] = pts
    with open(os.path.join(RES, "fallback.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fb[0]))
        w.writeheader()
        w.writerows(fb)
    L.append("")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 2, figsize=(10, 3.8))
        for key, pts in fig_data.items():
            ax[0].plot([p[2] for p in pts], [p[1] for p in pts], "o-", label=key, ms=3)
            ax[1].plot([p[2] for p in pts], [p[3] for p in pts], "o-", label=key, ms=3)
        ax[0].axhline(0, color="k", lw=0.8)
        ax[0].set_xlabel("deviation rate (share of dev instances)")
        ax[0].set_ylabel("net gain vs always-D (% PAR2)")
        ax[1].set_xlabel("deviation rate")
        ax[1].set_ylabel("severe regressions (count)")
        ax[0].legend(fontsize=7)
        fig.suptitle("Default-fallback curves (theta sweep, outer OOF, dev 401)")
        fig.tight_layout()
        fig.savefig(os.path.join(FIG, "fallback_curves.png"), dpi=130)
        # gains by comparison
        fig, ax = plt.subplots(figsize=(10, 4.5))
        rr = sorted(reg, key=lambda r: r["gain_pct"])
        y = np.arange(len(rr))
        ax.errorbar([r["gain_pct"] for r in rr], y, xerr=[[r["gain_pct"] - r["gain_pct_lo"] for r in rr],
                                                         [r["gain_pct_hi"] - r["gain_pct"] for r in rr]], fmt="o", ms=3)
        ax.axvline(0, color="k", lw=0.8)
        ax.axvline(R["oracle"]["gain_pct"], color="g", lw=0.8, ls="--", label="oracle (not deployable)")
        ax.set_yticks(y)
        ax.set_yticklabels([r["name"] for r in rr], fontsize=6)
        ax.set_xlabel("net gain vs always-D (% PAR2, 95% family cluster bootstrap)")
        ax.legend(fontsize=7)
        fig.tight_layout()
        fig.savefig(os.path.join(FIG, "comparisons.png"), dpi=130)
        L += ["![回退曲线](figures/fallback_curves.png)", "", "![全部比较](figures/comparisons.png)", ""]
    except ImportError:
        pass

    # ------------------------------------------------ 6. OOD (H04) and by group
    S = D.s28_package()
    dist = np.zeros(D.n)
    for k in range(5):
        tr, te = D.outer != k, D.outer == k
        pre = VS.make_pre(S["X"], S["names"], tr, True)
        Ztr = VS.apply_pre(pre, S["X"][tr], S["names"])
        Zte = VS.apply_pre(pre, S["X"][te], S["names"])
        dd = np.sqrt(((Zte[:, None, :] - Ztr[None, :, :]) ** 2).sum(2))
        dist[te] = np.sort(dd, 1)[:, :5].mean(1)
    t1, t2 = np.quantile(dist, [1 / 3, 2 / 3])
    terc = np.where(dist <= t1, 0, np.where(dist <= t2, 1, 2))
    L += ["## 6. 按训练分布距离（H04）与优势组分解", "",
          "OOD 距离 = 外层训练折 S28 标准化空间中到 5 个最近训练实例的平均距离，按三分位分成近/中/远。", "",
          "| 策略 | 近：净收益 s/题 | 中 | 远 |", "|---|---:|---:|---:|"]
    for key in (s1["name"], s2["name"]):
        cost = oof[key][0]["cost"]
        L.append(f"| {key} | " + " | ".join(f"{(c0 - cost)[terc == t].mean():+.2f}" for t in range(3)) + " |")
    L += ["", "| 策略 | 组 | n | 偏离到 F+ | 偏离到 F− | 净收益 s/题 |", "|---|---|---:|---:|---:|---:|"]
    for key in (s1["name"], s2["name"]):
        res, P = oof[key]
        for g in GL:
            sel = np.array([x == g for x in D.group])
            L.append(f"| {key} | {GL[g]} | {sel.sum()} | {int(((res['choice'] == 1) & sel).sum())} | {int(((res['choice'] == 2) & sel).sum())} | "
                     f"{(c0 - res['cost'])[sel].mean():+.2f} |")
    L.append("")
    open(os.path.join(REP, "SELECTION_TABLES.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
