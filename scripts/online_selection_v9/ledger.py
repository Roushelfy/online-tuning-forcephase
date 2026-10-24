#!/usr/bin/env python3
"""v9 CPU ledger (no CPU-hour limit; accounting only, configs/resource_policy.json).

  ledger.py  -> results/online_selection_v9/COMPUTE.md
Counts every v9 stage record (solver / wrapper process-tree CPU and checker CPU), generation CPU from the
manifests, the R5 old-55 stages (finished records + running jobs from their heartbeat), voided attempts and an
upper estimate for analysis.
"""
import glob
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RES = os.path.join(ROOT, "results", "online_selection_v9")
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
BEFORE = 197.74
VOID = {"external": "deviation 3: SATLIB parse error, all 240 runs voided"}


def stage(path):
    n, s, c, running = 0, 0.0, 0.0, 0.0
    for p in glob.glob(os.path.join(path, "*.json")):
        if p.endswith(("progress.json", "effective_plan.json")):
            continue
        r = json.load(open(p))
        n += 1
        s += r.get("cpu") or 0.0
        c += ((r.get("verification") or {}).get("cpu") or 0.0)
    hb = os.path.join(path, "progress.json")
    if os.path.exists(hb):
        running = sum(j["cpu"] for j in json.load(open(hb)).get("jobs", []) if j.get("state", "running") != "finished")
    return n, s / 3600, c / 3600, running / 3600


def main():
    rows = []
    for d in sorted(glob.glob(os.path.join(DATA, "runs", "online_selection_v9", "*"))):
        if os.path.isdir(d):
            n, s, c, r = stage(d)
            rows.append((os.path.basename(d), n, s, c, r))
    for st in ("old55_r1a", "old55_r1b"):
        n, s, c, r = stage(os.path.join(DATA, "runs", "completion_v7", st))
        rows.append(("R5 " + st, n, s, c, r))
    gen = 0.0
    for mp in glob.glob(os.path.join(RES, "*manifest.json")):
        gen += json.load(open(mp)).get("gen_cpu_total") or 0.0
    L = ["# Goal v9 算力账本（只计量，没有上限）", "",
         f"由 `scripts/online_selection_v9/ledger.py` 生成，{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}。"
         "运行中的作业按心跳中的实际 CPU 计入（“运行中”列）。", "",
         "| 阶段 | 记录数 | 求解 / wrapper CPU 核时 | 检查器核时 | 运行中核时 | 备注 |", "|---|---:|---:|---:|---:|---|"]
    tot = 0.0
    for name, n, s, c, r in rows:
        L.append(f"| {name} | {n} | {s:.3f} | {c:.3f} | {r:.3f} | {VOID.get(name, '')} |")
        tot += s + c + r
    L.append(f"| 实例生成（全部 v9 清单） | | {gen / 3600:.3f} | | | |")
    L.append("| 分析、建模、报告、图、测试与环境（估计上限） | | 0.300 | | | |")
    tot += gen / 3600 + 0.3
    L += ["", f"- v9 合计 {tot:.2f} 核时（含运行中的 R5 作业到此刻为止的 CPU）；截至 v8 的历史累计为 {BEFORE}，现累计 {BEFORE + tot:.2f} 核时。",
          "- 按用户的资源政策，这些数字只用于记账，不是停止阈值。"]
    open(os.path.join(RES, "COMPUTE.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
