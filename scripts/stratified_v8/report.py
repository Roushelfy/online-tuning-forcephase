#!/usr/bin/env python3
"""v8 report tables (docs/STRATIFIED_PROTOCOL_V8.md sections 6-8). Standard library only.

  report.py [--holdout]      (--holdout only after the rule freeze and S3)

Writes reports/stratified_v8/{BASELINES_TABLES.md, VALIDATION_TABLES.md}, results/stratified_v8/
{per_instance.csv, figdata.json, COMPUTE.md}. Figures: scripts/stratified_v8/figures.py.
"""

import argparse
import collections
import csv
import glob
import json
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
CFG = os.path.join(ROOT, "configs", "stratified_v8")
RES = os.path.join(ROOT, "results", "stratified_v8")
REP = os.path.join(ROOT, "reports", "stratified_v8")
ACTS = ("D", "Fp", "Fm")
LBL = {"D": "D", "Fp": "F+", "Fm": "F−", "SBS": "SBS (F−)", "W": "选择器 W", "oracle": "oracle"}
TYPES, SCALES = ("rand3", "col3", "assign"), ("S", "M", "L")
SC = json.load(open(os.path.join(CFG, "scales.json")))
TAU_ABS, TAU_REL = SC["tau_abs"], SC["tau_rel"]


def records(stage):
    out = {}
    for p in glob.glob(os.path.join(DATA, "runs", "stratified_v8", stage, "*.json")):
        if p.endswith("progress.json"):
            continue
        r = json.load(open(p))
        if r.get("rep", 0) == 0:
            out[(r["instance"], r["method"])] = r
    return out


def ok(r):
    return r is not None and r["status"] == "solved" and (r.get("verification") or {}).get("ok") is True


def instance_rows(part, stage, split):
    recs = records(stage)
    rows = []
    for i in sorted(k for k, v in split.items() if v["split"] == part):
        row = {"instance": i, "split": part, "type": split[i]["type"], "scale": split[i]["scale"],
               "param": SC["params"][split[i]["type"]][split[i]["scale"]]}
        for m in ACTS + ("W",):
            r = recs.get((i, m))
            row[m] = r["cpu"] if ok(r) else None
            row[m + "_status"] = r["status"] if r else "missing"
            if m == "D" and r:
                row["answer"] = {10: "SAT", 20: "UNSAT"}.get(r.get("exit_code"))
                row["conflicts_D"] = (r.get("stats") or {}).get("conflicts")
            if m == "W" and r:
                row.update(W_action=r.get("action"), W_obs=r.get("observation_cpu"), W_formal=r.get("formal_cpu"),
                           W_path=(r.get("decision") or {}).get("path"))
        if all(row[m] is not None for m in ACTS):
            best = min(ACTS, key=lambda m: (row[m], ACTS.index(m)))
            second = sorted(row[m] for m in ACTS)[1]
            row["oracle"] = row[best]
            row["winner"] = best
            row["clear"] = second - row[best] >= max(TAU_ABS, TAU_REL * second)
            row["d_clear_loss"] = {m: row["D"] - row[m] >= max(TAU_ABS, TAU_REL * row["D"]) for m in ("Fp", "Fm")}
        rows.append(row)
    return rows


def fmt(x, nd=2):
    return "—" if x is None else f"{x:.{nd}f}"


def cell_table(rows, title):
    L = [f"### {title}", "", "| 类型 | 规模（参数） | 题数 | SAT/UNSAT | D | F+ | F− | oracle | 赢家（明确 / 接近） |",
         "|---|---|---:|---|---:|---:|---:|---:|---|"]
    for t in TYPES:
        for s in SCALES:
            rs = [r for r in rows if r["type"] == t and r["scale"] == s]
            if not rs:
                continue
            done = all(r.get("oracle") is not None for r in rs)
            mean = {m: (sum(r[m] for r in rs) / len(rs) if all(r[m] is not None for r in rs) else None) for m in ACTS}
            orc = sum(r["oracle"] for r in rs) / len(rs) if done else None
            sat = collections.Counter(r.get("answer") for r in rs)
            w = collections.Counter((r["winner"], r["clear"]) for r in rs if r.get("winner"))
            ws = ", ".join(f"{LBL[a]} {w[(a, True)]}/{w[(a, False)]}" for a in ACTS if w[(a, True)] + w[(a, False)])
            L.append(f"| {t} | {s} ({rs[0]['param']}) | {len(rs)} | {sat.get('SAT', 0)}/{sat.get('UNSAT', 0)} | "
                     + " | ".join(fmt(mean[m]) for m in ACTS) + f" | {fmt(orc)} | {ws} |")
    tot = {m: (sum(r[m] for r in rows) if all(r[m] is not None for r in rows) else None) for m in ACTS}
    orc = sum(r["oracle"] for r in rows) if all(r.get("oracle") is not None for r in rows) else None
    n = len(rows)
    L += ["", f"全部 {n} 题的完整平均（秒）：" + "，".join(f"{LBL[m]} {fmt(tot[m] / n if tot[m] is not None else None)}" for m in ACTS)
          + f"，oracle {fmt(orc / n if orc is not None else None)}。", ""]
    return L


def concentration(rows, base="D"):
    gains = sorted((r[base] - r["oracle"] for r in rows if r.get("oracle") is not None), reverse=True)
    tot = sum(gains)
    if tot <= 0:
        return None
    return {"total_saving": tot, "top1": gains[0] / tot, "top3": sum(gains[:3]) / tot,
            "top10pct": sum(gains[:max(1, len(gains) // 10)]) / tot}


def by_answer(rows):
    out = {}
    for t in TYPES:
        for ans in ("SAT", "UNSAT"):
            rs = [r for r in rows if r["type"] == t and r.get("answer") == ans and r.get("oracle") is not None]
            if not rs:
                continue
            out[f"{t}-{ans}"] = {"n": len(rs), **{m: sum(r[m] for r in rs) for m in ACTS},
                                 "winners": dict(collections.Counter(r["winner"] for r in rs)),
                                 "median_log2_Fp_D": med([math.log2(r["Fp"] / r["D"]) for r in rs]),
                                 "median_log2_Fm_D": med([math.log2(r["Fm"] / r["D"]) for r in rs])}
    return out


def med(v):
    v = sorted(v)
    return None if not v else (v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2)


def bootstrap(rows, num, den, B=10000, seed=0):
    """Paired bootstrap of 1 - sum(num)/sum(den), instances resampled within cells."""
    rng = random.Random(seed)
    cells = collections.defaultdict(list)
    for r in rows:
        cells[(r["type"], r["scale"])].append(r)
    vals = []
    for _ in range(B):
        sn = sd = 0.0
        for c in cells.values():
            for _ in range(len(c)):
                r = c[rng.randrange(len(c))]
                sn += num(r)
                sd += den(r)
        vals.append(100 * (1 - sn / sd))
    vals.sort()
    return vals[int(0.025 * B)], vals[int(0.975 * B) - 1]


def ledger(holdout):
    items = []

    def stage_sum(stage):
        n, s, c = 0, 0.0, 0.0
        for p in glob.glob(os.path.join(DATA, "runs", "stratified_v8", stage, "*.json")):
            if p.endswith("progress.json"):
                continue
            r = json.load(open(p))
            n += 1
            s += r.get("cpu") or 0.0
            c += ((r.get("verification") or {}).get("cpu") or 0.0)
        return n, s / 3600, c / 3600
    gen = 0.0
    for m in ("smoke_manifest", "smoke_b_manifest", "pilot_r1_manifest", "pilot_r2_manifest", "formal_manifest"):
        p = os.path.join(RES, m + ".json")
        if os.path.exists(p):
            gen += json.load(open(p))["gen_cpu_total"]
    items.append(("环境准备（容器检查、生成器 venv，上限估计）", None, 0.02, 0.0))
    items.append(("实例生成（烟雾、试采样、正式）", None, gen / 3600, 0.0))
    for st, name in (("smoke_v8", "烟雾测试"), ("smoke_v8b", "烟雾测试（停止路径）"), ("pilot_r1", "试采样第 1 轮"),
                     ("pilot_r2", "试采样第 2 轮"), ("s1_dev", "S1 开发集三动作"), ("s3_holdout", "S3 留出集（三动作 + W）"),
                     ("mech_dev", "机制检查（flipall / perm）")):
        n, s, c = stage_sum(st)
        if n:
            items.append((name, n, s, c))
    fe = json.load(open(os.path.join(RES, "features_dev.json")))["cpu_total"] if os.path.exists(os.path.join(RES, "features_dev.json")) else 0
    ck = json.load(open(os.path.join(RES, "wrapper_check_dev.json")))["wrapper_cpu_total"] if os.path.exists(os.path.join(RES, "wrapper_check_dev.json")) else 0
    items.append(("开发集特征与 wrapper 一致性检查", None, (fe + ck) / 3600, 0.0))
    p = os.path.join(RES, "features_holdout.json")
    if os.path.exists(p):
        items.append(("留出集特征（离线分析）", None, json.load(open(p))["cpu_total"] / 3600, 0.0))
    items.append(("分析、建模、报告、图（上限估计）", None, 0.05, 0.0))
    tot = sum(s + c for _, _, s, c in items)
    C = ["# Goal v8 的算力账本", "", "由 `scripts/stratified_v8/report.py` 生成；只计 v8 新产生的 CPU。", "",
         "| 项 | 记录数 | 求解 / 生成 / 观察 CPU 核时 | 检查器 CPU 核时 |", "|---|---:|---:|---:|"]
    for name, n, s, c in items:
        C.append(f"| {name} | {'' if n is None else n} | {s:.4f} | {c:.4f} |")
    C += [f"| **合计** | | **{sum(s for _, _, s, _ in items):.4f}** | **{sum(c for _, _, _, c in items):.4f}** |", "",
          f"- v8 合计 {tot:.3f} 核时；v8 之前累计 195.89，现累计 {195.89 + tot:.3f} / 200。"]
    open(os.path.join(RES, "COMPUTE.md"), "w").write("\n".join(C) + "\n")
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", action="store_true")
    a = ap.parse_args()
    split = json.load(open(os.path.join(CFG, "split.json")))
    os.makedirs(REP, exist_ok=True)
    dev = instance_rows("dev", "s1_dev", split)
    rows = list(dev)
    L = ["# v8 三模式基线表（由 `scripts/stratified_v8/report.py` 生成）", "",
         f"明确优势：最快者比第二快者至少快 max({TAU_ABS} s, {TAU_REL:.0%} × 第二快)；否则记为“接近”。时间为经独立验证的完成 CPU 秒（含 LRAT 证明输出）。", ""]
    L += cell_table(dev, "开发集（36 题）")
    hold = []
    if a.holdout:
        hold = instance_rows("holdout", "s3_holdout", split)
        rows += hold
        L += cell_table(hold, "留出集（18 题，规则冻结后解封）")
        L += cell_table(dev + hold, "全部 54 题")
    figdata = {"rows": rows, "concentration": {"dev": concentration(dev), "all": concentration(rows) if a.holdout else None},
               "by_answer": {"dev": by_answer(dev), "all": by_answer(rows) if a.holdout else None}}
    pre = [r for r in rows if r.get("conflicts_D") == 0]
    L += ["### 其他统计", "",
          f"- D 运行冲突数为 0（预处理或单元传播直接结束）的题：{len(pre)} / {len(rows)}。",
          f"- oracle 相对 D 的节省集中度（{'全部' if a.holdout else '开发集'}）：" + json.dumps(
              {k: round(v, 3) for k, v in (figdata['concentration']['all' if a.holdout else 'dev'] or {}).items()}), ""]
    L += ["### 按真实答案分组（离线分析用；答案不作部署输入）", "", "| 组 | 题数 | D 总量 | F+ 总量 | F− 总量 | 赢家 | 中位 log2(F+/D) | 中位 log2(F−/D) |",
          "|---|---:|---:|---:|---:|---|---:|---:|"]
    for k, v in figdata["by_answer"]["all" if a.holdout else "dev"].items():
        L.append(f"| {k} | {v['n']} | {v['D']:.1f} | {v['Fp']:.1f} | {v['Fm']:.1f} | {v['winners']} | "
                 f"{v['median_log2_Fp_D']:+.2f} | {v['median_log2_Fm_D']:+.2f} |")
    open(os.path.join(REP, "BASELINES_TABLES.md"), "w").write("\n".join(L) + "\n")
    with open(os.path.join(RES, "per_instance.csv"), "w", newline="") as f:
        keys = sorted({k for r in rows for k in r if k != "d_clear_loss"})
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    if a.holdout:
        summ = json.load(open(os.path.join(RES, "summary_holdout.json")))
        V = ["# v8 留出验证表（由 `scripts/stratified_v8/report.py` 生成）", "",
             f"留出 18 题；主比较完整：**{'是' if summ['primary_comparison_complete'] else '否'}**。", "",
             "| 方法 | 完成数 | 完整平均 CPU（秒） | 总 CPU（秒） | 相对 D | 相对 SBS |", "|---|---:|---:|---:|---:|---:|"]
        ms = summ["methods"]
        sbs_mean = ms["SBS"]["mean_cpu_seconds"]
        for m in ("D", "Fp", "Fm", "SBS", "W"):
            v = ms[m]
            g = summ["gain_percent_vs_baseline"].get(m)
            gs = (100 * (1 - v["mean_cpu_seconds"] / sbs_mean)) if v["mean_cpu_seconds"] is not None and sbs_mean else None
            V.append(f"| {LBL[m]} | {v['completed']}/18 | {fmt(v['mean_cpu_seconds'], 3)} | {fmt(v['total_cpu_seconds'], 1)} | "
                     f"{'—' if g is None else f'{g:+.1f}%'} | {'—' if gs is None else f'{gs:+.1f}%'} |")
        o = summ["oracle"]
        V.append(f"| oracle（不可部署） | {o['completed']}/18 | {fmt(o['mean_cpu_seconds'], 3)} | {fmt(o['total_cpu_seconds'], 1)} | "
                 f"{summ['gain_percent_vs_baseline']['oracle']:+.1f}% | "
                 f"{(100 * (1 - o['mean_cpu_seconds'] / sbs_mean)) if o['mean_cpu_seconds'] and sbs_mean else float('nan'):+.1f}% |")
        if summ["primary_comparison_complete"]:
            ci_d = bootstrap(hold, lambda r: r["W"], lambda r: r["D"])
            ci_s = bootstrap(hold, lambda r: r["W"], lambda r: r["Fm"])
            ci_sd = bootstrap(hold, lambda r: r["Fm"], lambda r: r["D"])
            figdata["bootstrap"] = {"W_vs_D": ci_d, "W_vs_SBS": ci_s, "SBS_vs_D": ci_sd}
            V += ["", f"格内配对 bootstrap 95% 区间（10000 次，seed 0；只有 3 个生成类型、每格 2 题）：W 相对 D [{ci_d[0]:+.1f}%, {ci_d[1]:+.1f}%]；"
                  f"W 相对 SBS [{ci_s[0]:+.1f}%, {ci_s[1]:+.1f}%]；SBS 相对 D [{ci_sd[0]:+.1f}%, {ci_sd[1]:+.1f}%]。"]
        V += ["", "### 逐题", "", "| 实例 | 答案 | D | F+ | F− | oracle | W 动作 | W 观察 CPU | W 正式 CPU | W 总 CPU | W − D | W − SBS |",
              "|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|"]
        for r in hold:
            dd = None if r["W"] is None or r["D"] is None else r["W"] - r["D"]
            ds = None if r["W"] is None or r["Fm"] is None else r["W"] - r["Fm"]
            V.append(f"| {r['instance']} | {r.get('answer')} | {fmt(r['D'])} | {fmt(r['Fp'])} | {fmt(r['Fm'])} | {fmt(r.get('oracle'))} | "
                     f"{r.get('W_action')} | {fmt(r.get('W_obs'), 3)} | {fmt(r.get('W_formal'))} | {fmt(r['W'])} | "
                     f"{'—' if dd is None else f'{dd:+.2f}'} | {'—' if ds is None else f'{ds:+.2f}'} |")
        acts = collections.Counter(r.get("W_action") for r in hold)
        wrong_d = [r["instance"] for r in hold if r.get("W_action") not in (None, "D") and r[r["W_action"]] > r["D"]]
        V += ["", f"- W 的动作：{dict(acts)}；偏离 D 的题中比 D 慢的（错误偏离）：{len(wrong_d)}（{', '.join(wrong_d) or '无'}）。",
              f"- W 的观察 CPU 合计 {sum((r.get('W_obs') or 0) for r in hold):.3f} s。"]
        same = [(r["W_formal"], r[r["W_action"]]) for r in hold if r.get("W_formal") and r.get("W_action") and r[r["W_action"]]]
        if same:
            V.append(f"- W 的正式求解与同动作固定运行是同一命令：|差| 中位 {med([abs(x - y) for x, y in same]):.3f} s，"
                     f"最大 {max(abs(x - y) for x, y in same):.3f} s（同批计时噪声）。")
        open(os.path.join(REP, "VALIDATION_TABLES.md"), "w").write("\n".join(V) + "\n")
    tot = ledger(a.holdout)
    figdata["ledger_v8_cpu_hours"] = tot
    json.dump(figdata, open(os.path.join(RES, "figdata.json"), "w"), indent=1)
    print("\n".join(L))
    if a.holdout:
        print(open(os.path.join(REP, "VALIDATION_TABLES.md")).read())
    print(open(os.path.join(RES, "COMPUTE.md")).read())


if __name__ == "__main__":
    main()
