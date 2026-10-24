#!/usr/bin/env python3
"""v7 report: completion status on the fixed 55-instance panel, per-instance
exact times / actual lower bounds, oracle certificates, provable bounds on
the P1_M05_long - D difference, and the v7 CPU ledger.

  python3 scripts/completion_v7/report.py

Reads results/completion_v7/normalized.json (scripts/completion_v7/normalize.py)
and the evaluator output results/completion_v7/summary.json. Means, totals and
gains of incomplete methods stay null; lower bounds are labelled as bounds.
Writes reports/completion_v7/REPORT_TABLES.md, results/completion_v7/per_instance.csv
and results/completion_v7/COMPUTE.md.
"""

import collections
import csv
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import fprun  # noqa: E402

RES = os.path.join(ROOT, "results", "completion_v7")
REP = os.path.join(ROOT, "reports", "completion_v7")
OUT = os.path.join(fprun.DATA, "runs", "completion_v7")
METHODS = ("D", "Fp", "Fm", "P1_M05_long")
LBL = {"D": "D", "Fp": "F+", "Fm": "F−", "P1_M05_long": "P1_M05_long"}
BEFORE = 144.65
ANALYSIS_H = 1.0


def exact(r):
    return r["cpu_seconds"] if r and r["status"] == "solved" and r.get("verified") and r.get("measurement_valid") else None


def lower(r):
    if exact(r) is not None:
        return exact(r)
    if r and r["status"] in ("censored", "noncompetitive_bound") and r.get("measurement_valid"):
        return r["cpu_seconds"]
    return None


def cell(r):
    e = exact(r)
    if e is not None:
        return f"{e:.1f}"
    lb = lower(r)
    return f"≥ {lb:.0f}" if lb is not None else (r["status"] if r else "missing")


def main():
    norm = json.load(open(os.path.join(RES, "normalized.json")))
    summ = json.load(open(os.path.join(RES, "summary.json")))
    man = {r["hash"]: r for r in csv.DictReader(open(os.path.join(ROOT, "results", "stable_selection_v6", "validate_manifest.csv")))}
    idx = {(r["instance"], r["method"]): r for r in norm}
    panel = [l.split()[0] for l in open(os.path.join(ROOT, "configs", "completion_v7", "panel.txt")) if l.strip() and not l.startswith("#")]
    N = len(panel)
    L = ["# v7 完成时间表（由 `scripts/completion_v7/report.py` 生成）", ""]
    L += ["## 1. 固定面板与完成情况", "", f"固定清单 {N} 题（`configs/completion_v7/panel.txt`）。只有全部 {N} 题都有独立验证通过的完成时间，完整均值才可计算。", "",
          "| 方法 | 完成数 | 完整平均 CPU（秒） | 总 CPU | 相对 D | 已执行 CPU 之和（完成时间 + 未完成题的实际下界，秒） |",
          "|---|---:|---|---|---|---:|"]
    for m in METHODS:
        s = summ["methods"][m]
        lbs = [lower(idx.get((h, m))) for h in panel]
        lbsum = sum(x for x in lbs if x is not None)
        g = summ["gain_percent_vs_baseline"].get(m)
        mean_s = "未知（null）" if s["mean_cpu_seconds"] is None else f"{s['mean_cpu_seconds']:.1f}"
        total_s = "未知" if s["total_cpu_seconds"] is None else f"{s['total_cpu_seconds']:.0f}"
        gain_s = "未计算" if g is None else f"{g:+.2f}%"
        L.append(f"| {LBL[m]} | {s['completed']}/{N} | {mean_s} | {total_s} | {gain_s} | {lbsum:.0f}（下界） |")
    o = summ["oracle"]
    L.append(f"| oracle（事后最快，不可部署） | {o['completed']}/{N} 已确定 | {'未知（null）' if o['mean_cpu_seconds'] is None else round(o['mean_cpu_seconds'], 1)} | | | |")
    L += ["", f"主比较是否完整：**{'是' if summ['primary_comparison_complete'] else '否'}**。未完成时，均值、总量与收益都是 null；"
          "最后一列只是“已经实际执行的 CPU”，对总耗时是**下界**，不是完整总耗时。", ""]
    # per-instance
    rows = []
    for h in panel:
        mm = man.get(h, {})
        rec = {"hash": h, "family": mm.get("family_group"), "stratum": mm.get("stratum"), "gbd_result": mm.get("gbd_result")}
        for m in METHODS:
            r = idx.get((h, m))
            rec[f"{m}_status"] = r["status"] if r else "missing"
            rec[f"{m}_cpu"] = r["cpu_seconds"] if r else None
            rec[f"{m}_source"] = (r or {}).get("origin")
        ov = summ["oracle"]
        un = [d for d in ov["unresolved"] if d["instance"] == h]
        rec["oracle"] = None if un else min(exact(idx.get((h, a))) for a in ("D", "Fp", "Fm") if exact(idx.get((h, a))) is not None)
        rec["oracle_unresolved"] = "/".join(un[0]["unresolved_actions"]) if un else ""
        rows.append(rec)
    with open(os.path.join(RES, "per_instance.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    L += ["## 2. 未完成实例（至少一个方法尚无完成时间）", "",
          "数值为经验证的完成 CPU 秒；`≥ x` 为实际执行到 x 秒仍未完成的下界（来源见 `results/completion_v7/per_instance.csv`）。", "",
          "| 实例 | 家族 | 规模 | GBD 已知结果 | D | F+ | F− | P1_M05_long | oracle |", "|---|---|---|---|---:|---:|---:|---:|---:|"]
    for rec in rows:
        if all(exact(idx.get((rec["hash"], m))) is not None for m in METHODS):
            continue
        h = rec["hash"]
        orc = f"{rec['oracle']:.1f}" if rec["oracle"] is not None else f"待定（{rec['oracle_unresolved']}）"
        L.append(f"| {h[:10]} | {rec['family']} | {rec['stratum']} | {rec['gbd_result']} | " +
                 " | ".join(cell(idx.get((h, m))) for m in METHODS) + f" | {orc} |")
    L.append("")
    # provable P1 - D difference
    diffs, lo_total, hi_total, open_hi = [], 0.0, 0.0, []
    for h in panel:
        d, p = idx.get((h, "D")), idx.get((h, "P1_M05_long"))
        ed, ep = exact(d), exact(p)
        shared = (d or {}).get("origin", "").endswith("formal_subprocess")
        if shared:
            # same run: P1 - D = observation + wrapper CPU (exact even when censored)
            diff = p["cpu_seconds"] - d["cpu_seconds"]
            diffs.append((h, "same run", diff, diff))
            lo_total += diff
            hi_total += diff
        elif ed is not None and ep is not None:
            diffs.append((h, "both complete", ep - ed, ep - ed))
            lo_total += ep - ed
            hi_total += ep - ed
        else:
            ld, lp = lower(d), lower(p)
            # P1 - D lies in [lp - (unknown D, so -inf if D incomplete) , (unknown P1) - ld]
            lo = (lp - ed) if ed is not None else float("-inf")
            hi = (ep - ld) if ep is not None and ld is not None else float("inf")
            diffs.append((h, "bound", lo, hi))
            lo_total += lo
            hi_total += hi
            open_hi.append(h)
    L += ["## 3. 补充：P1_M05_long 与 D 总 CPU 之差的可证明区间（不是主指标）", "",
          "在 P1_M05_long 选 D 的题上，D 的测量取自同一次运行的正式求解，所以“P1 − D”恰好等于观察与 wrapper 的 CPU，即使该运行尚未完成也已知。"
          "两个方法都已完成的题上差值精确；其余题只能给出区间。", "",
          f"- 差值精确的题：{sum(1 for x in diffs if x[1] != 'bound')}；只能给出区间的题：{len(open_hi)}"
          f"（{', '.join(h[:10] for h in open_hi) or '无'}）。",
          f"- 总差值 Σ(P1 − D) ∈ [{lo_total:.1f}, {hi_total:.1f}] 秒（负 = P1_M05_long 更省时）。"]
    lb_d = sum(lower(idx.get((h, "D"))) or 0.0 for h in panel)
    if not open_hi:
        # gain = -sum(P1 - D) / total(D) with total(D) >= lb_d: same sign, magnitude at most |diff| / lb_d
        g = -lo_total / lb_d * 100
        L += [f"- D 总 CPU 的实际下界为 {lb_d:.0f} 秒，所以若两方法都在同一次运行中完成，P1_M05_long 相对 D 的收益介于 0 与 {g:+.3f}% 之间"
              "（收益 = −Σ(P1 − D) / D 总 CPU，分母只会更大）。这只是界，不是主指标；主指标仍为 null。"]
    L.append("")
    # ledger
    acc = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for st in sorted(os.listdir(OUT)) if os.path.isdir(OUT) else []:
        for p in glob.glob(os.path.join(OUT, st, "*.json")):
            if p.endswith("progress.json"):
                continue
            r = json.load(open(p))
            acc[st][0] += 1
            acc[st][1] += r["cpu"]
            acc[st][2] += ((r.get("verification") or {}).get("cpu") or 0.0)
    void = json.load(open(os.path.join(RES, "voided_attempts.json")))["voided_attempts"]
    C = ["# Goal v7 的算力账本", "", "由 `scripts/completion_v7/report.py` 生成；只计 v7 新产生的 CPU。", "",
         "| 项 | 记录数 | 求解 / wrapper CPU 核时 | 检查器 CPU 核时 |", "|---|---:|---:|---:|"]
    ts = tc = 0.0
    for st, (n, s, c) in acc.items():
        C.append(f"| {st} | {n} | {s / 3600:.2f} | {c / 3600:.2f} |")
        ts += s
        tc += c
    vh = sum(v["cpu_hours_upper_bound"] for v in void)
    C.append(f"| 作废尝试（上限估计） | {len(void)} | {vh:.2f} | — |")
    C.append(f"| 分析、报告与测试（估计上限） | — | {ANALYSIS_H:.2f} | — |")
    tot = ts / 3600 + tc / 3600 + vh + ANALYSIS_H
    C += [f"| **合计** | | **{ts / 3600 + vh + ANALYSIS_H:.2f}** | **{tc / 3600:.2f}** |", "",
          f"- v7 合计 {tot:.2f} 核时；v7 之前累计 {BEFORE:.2f}，现累计 {BEFORE + tot:.2f}（上限 200）。"]
    open(os.path.join(RES, "COMPUTE.md"), "w").write("\n".join(C) + "\n")
    L += ["## 4. 算力", "", f"见 [COMPUTE.md](../../results/completion_v7/COMPUTE.md)：v7 合计 {tot:.2f} 核时，累计 {BEFORE + tot:.2f} / 200。", ""]
    open(os.path.join(REP, "REPORT_TABLES.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))
    print("\n".join(C))


if __name__ == "__main__":
    main()
