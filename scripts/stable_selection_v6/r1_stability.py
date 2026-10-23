#!/usr/bin/env python3
"""R1 of goal v6: stability of the v4 advantage labels over solver seeds 0/1/2
on the 30-instance diagnostic panel (protocol section 2). Diagnostic only.

  $FP_PY scripts/stable_selection_v6/r1_stability.py

seed 0 = v4 dev fixed runs (tw_dev_fixed), seeds 1/2 = v6_seed1/v6_seed2
(runs identical to v5_seed1 are reused by run id; their origin is kept).
q(a,s) = (min_{b != a} c(b,s) + 1) / (c(a,s) + 1); a is a 'stable advantage'
if q >= 1.5 on >= 2 seeds and q >= 1 on the others.
Writes results/stable_selection_v6/stability_long.csv, stability.json,
reports/stable_selection_v6/STABILITY_TABLES.md and figures/stability.png.
"""

import collections
import csv
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "three_way"))
import fprun  # noqa: E402
import twdata as TD  # noqa: E402

RES = os.path.join(ROOT, "results", "stable_selection_v6")
REP = os.path.join(ROOT, "reports", "stable_selection_v6")
ACTS = ("D", "Fp", "Fm")
LBL = {"D": "D", "Fp": "F+", "Fm": "F−"}
GL = {"D-adv": "D 优势", "Fp-adv": "F+ 优势", "Fm-adv": "F− 优势"}
PAR2 = 600.0


def cost(r):
    return r["cpu"] if r and r.get("status") == "solved" else PAR2


def main():
    os.makedirs(RES, exist_ok=True)
    os.makedirs(os.path.join(REP, "figures"), exist_ok=True)
    diag = [l.split() for l in open(os.path.join(ROOT, "configs", "stable_selection_v6", "diag30.txt"))
            if l.strip() and not l.startswith("#")]
    info = {d[0]: {"group": d[1], "year": d[2], "stratum": d[3], "family": d[4]} for d in diag}
    recs = {}
    fx = TD.fixed_records(os.path.join(ROOT, "configs", "three_way", "tw_dev_fixed.json"))
    for h in info:
        for a in ACTS:
            recs[(h, a, 0)] = fx[h][a]
    for s in (1, 2):
        exp = fprun.load_experiment(os.path.join(ROOT, "configs", "stable_selection_v6", f"v6_seed{s}.json"))
        n2a = {"D": "D", "Fplus": "Fp", "Fminus": "Fm"}
        for r in fprun.plan(exp):
            p = fprun.result_path(r["run_id"])
            recs[(r["key"]["instance"], n2a[r["config"]], s)] = json.load(open(p)) if os.path.exists(p) else None
    missing = [k for k, v in recs.items() if v is None or v.get("status") == "missing"]
    long = []
    for (h, a, s), r in sorted(recs.items()):
        long.append({"hash": h, **info[h], "action": LBL[a], "seed": s, "status": (r or {}).get("status"),
                     "cpu": (r or {}).get("cpu"), "cost": cost(r), "host": (r or {}).get("host"),
                     "start_utc": (r or {}).get("start_utc"), "origin_exp": (r or {}).get("exp"),
                     "conflicts": ((r or {}).get("stats") or {}).get("conflicts")})
    with open(os.path.join(RES, "stability_long.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(long[0]))
        w.writeheader()
        w.writerows(long)
    C = {h: {s: {a: cost(recs[(h, a, s)]) for a in ACTS} for s in (0, 1, 2)} for h in info}

    def q(h, a, s):
        c = C[h][s]
        return (min(c[b] for b in ACTS if b != a) + 1) / (c[a] + 1)

    def stable(h):
        for a in ACTS:
            qs = [q(h, a, s) for s in (0, 1, 2)]
            if sum(x >= 1.5 for x in qs) >= 2 and all(x >= 1 for x in qs):
                return a
        return None

    def winner(h, s):
        c = C[h][s]
        if all(c[a] >= PAR2 for a in ACTS):
            return "timeout"
        best = min(ACTS, key=lambda a: (c[a], ACTS.index(a)))
        second = sorted(c.values())[1]
        return best if (second + 1) / (c[best] + 1) >= 1.5 else "close"

    per = {}
    L = ["# R1 稳定性表（由 `scripts/stable_selection_v6/r1_stability.py` 生成）", "",
         f"诊断 30 题 × 3 动作 × seed 0/1/2；缺失运行 {len(missing)}。"
         "复用：seed 1 中与 v5 seed 重复相同的运行直接复用（`origin_exp = v5_seed1`），其余为 v6 新跑。", "",
         "## 1. 按原优势组", "",
         "| 原组 | n | 小面板内稳定、且与原标签同向 | 稳定为其他动作 | 不稳定 | 三个 seed 都赢（margin 1.5） | 原赢家在 seed 1/2 都仍是最快 |",
         "|---|---:|---:|---:|---:|---:|---:|"]
    for g in ("D-adv", "Fp-adv", "Fm-adv"):
        hs = [h for h in info if info[h]["group"] == g]
        a0 = g.split("-")[0]
        st = [stable(h) for h in hs]
        same = sum(x == a0 for x in st)
        other = sum(x not in (None, a0) for x in st)
        allw = sum(all(winner(h, s) == a0 for s in (0, 1, 2)) for h in hs)
        fastest = sum(all(min(ACTS, key=lambda a: (C[h][s][a], ACTS.index(a))) == a0 for s in (1, 2)) for h in hs)
        per[g] = {"n": len(hs), "stable_same": same, "stable_other": other, "unstable": len(hs) - same - other,
                  "won_all_seeds": allw, "fastest_all_seeds": fastest}
        L.append(f"| {GL[g]} | {len(hs)} | {same} | {other} | {len(hs) - same - other} | {allw} | {fastest} |")
    fpm = per["Fp-adv"]["stable_same"] + per["Fm-adv"]["stable_same"]
    share = fpm / (per["Fp-adv"]["n"] + per["Fm-adv"]["n"])
    L += ["", f"原 F+/F− 优势题中稳定保留的合计比例：{fpm}/{per['Fp-adv']['n'] + per['Fm-adv']['n']} = {share:.0%}"
          f"（协议收缩规则阈值 30%：{'触发，R4 至多部署 1 个候选' if share < 0.3 else '未触发'}）。", ""]
    # winner transitions
    tr = collections.Counter()
    tot = collections.Counter()
    for h in info:
        for s in (1, 2):
            tr[(info[h]["group"], winner(h, s))] += 1
            for a in ACTS:
                s0 = C[h][0][a] < PAR2
                ss = C[h][s][a] < PAR2
                if s0 != ss:
                    tot[(a, "solved->timeout" if s0 else "timeout->solved")] += 1
    L += ["## 2. 赢家转换（seed 1 与 seed 2 合计 60 个“题 × seed”）", "",
          "| 原组 \\ 新 seed 下 | D 优势 | F+ 优势 | F− 优势 | 接近 | 全部超时 |", "|---|---:|---:|---:|---:|---:|"]
    for g in ("D-adv", "Fp-adv", "Fm-adv"):
        L.append(f"| {GL[g]} | " + " | ".join(str(tr[(g, w)]) for w in ("D", "Fp", "Fm", "close", "timeout")) + " |")
    L += ["", "超时转换（相对 seed 0）：" + "；".join(f"{LBL[a]} {k} {tot[(a, k)]}" for a in ACTS for k in ("solved->timeout", "timeout->solved")) + "。", ""]
    # continuous costs
    L += ["## 3. 逐题连续成本（秒；600 = 超时）", "",
          "| 原组 | 实例 | 家族 | 规模 | D s0/s1/s2 | F+ s0/s1/s2 | F− s0/s1/s2 | 稳定优势 |", "|---|---|---|---|---|---|---|---|"]
    for g in ("D-adv", "Fp-adv", "Fm-adv"):
        for h in sorted((h for h in info if info[h]["group"] == g), key=lambda h: info[h]["family"]):
            cell = lambda a: "/".join(f"{C[h][s][a]:.0f}" if C[h][s][a] < PAR2 else "TO" for s in (0, 1, 2))
            sa = stable(h)
            L.append(f"| {GL[g]} | {h[:10]} | {info[h]['family']} | {info[h]['stratum']} | {cell('D')} | {cell('Fp')} | {cell('Fm')} | "
                     f"{LBL[sa] if sa else '—'} |")
    L.append("")
    # timing repeats: F+/F- identical searches across seeds
    rat = {a: [] for a in ("Fp", "Fm", "D")}
    ident = collections.Counter()
    for h in info:
        for a in ("Fp", "Fm", "D"):
            r0 = recs[(h, a, 0)]
            for s in (1, 2):
                rs = recs[(h, a, s)]
                if not r0 or not rs or r0.get("status") != "solved" or rs.get("status") != "solved":
                    continue
                c0 = (r0.get("stats") or {}).get("conflicts")
                c1 = (rs.get("stats") or {}).get("conflicts")
                if c0 is not None and c0 == c1:
                    ident[a] += 1
                    if r0["cpu"] >= 1:
                        rat[a].append(rs["cpu"] / r0["cpu"])
    L += ["## 4. 同一搜索的计时重复", "",
          "F± 关闭了 rephase，不同 seed 下多数是同一搜索（冲突数相等）；这些对就是天然的计时重复。", "",
          "| 动作 | 与 seed 0 搜索相同的（题 × seed）对 | 其中 ≥ 1 s 的 CPU 比中位 | 5%–95% |", "|---|---:|---:|---|"]
    for a in ("Fp", "Fm", "D"):
        v = np.array(rat[a])
        L.append(f"| {LBL[a]} | {ident[a]} | {np.median(v):.3f} | {np.quantile(v, .05):.3f}–{np.quantile(v, .95):.3f} |" if len(v)
                 else f"| {LBL[a]} | {ident[a]} | — | — |")
    L.append("")
    json.dump({"per_group": per, "stable_share_FpFm": share, "shrink_rule_triggered": share < 0.3,
               "missing_runs": len(missing), "stable": {h: stable(h) for h in info}},
              open(os.path.join(RES, "stability.json"), "w"), indent=1)
    # figure: log2(c_a / c_D) per seed, by original group
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axs = plt.subplots(1, 3, figsize=(13, 4.2), sharey=True)
        for ax, g in zip(axs, ("D-adv", "Fp-adv", "Fm-adv")):
            hs = sorted((h for h in info if info[h]["group"] == g), key=lambda h: info[h]["family"])
            for k, h in enumerate(hs):
                for a, col, mk in (("Fp", "#1f77b4", "^"), ("Fm", "#d62728", "v")):
                    ys = [np.log2((C[h][s][a] + 1) / (C[h][s]["D"] + 1)) for s in (0, 1, 2)]
                    ax.plot([k - 0.15 + 0.15 * s for s in (0, 1, 2)], ys, color=col, marker=mk, ms=4, lw=0.8,
                            label=(LBL[a] if k == 0 else None))
            ax.axhline(0, color="k", lw=0.6)
            ax.set_xticks(range(len(hs)))
            ax.set_xticklabels([info[h]["family"][:10] for h in hs], rotation=70, fontsize=6)
            ax.set_title(f"originally {g} (seed 0/1/2 left to right)", fontsize=9)
        axs[0].set_ylabel("log2((c_action + 1) / (c_D + 1))   (< 0: better than D)")
        axs[0].legend(fontsize=7)
        fig.tight_layout()
        fig.savefig(os.path.join(REP, "figures", "stability.png"), dpi=130)
        L += ["![稳定性](figures/stability.png)", ""]
    except ImportError:
        pass
    open(os.path.join(REP, "STABILITY_TABLES.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
