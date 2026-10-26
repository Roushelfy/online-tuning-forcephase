#!/usr/bin/env python3
"""Goal v10 compute ledger (docs/CROSS_SCALE_PROTOCOL_V10.md section 10): actual CPU of every v10 stage --
solver / wrapper process trees, independent checkers, generation -- including failures and re-runs.
Accounting only: there is no CPU-hour limit (configs/resource_policy.json).

  python3 scripts/cross_scale_v10/ledger.py   -> results/cross_scale_v10/COMPUTE.md
"""
import collections
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
RUNS = os.path.join(DATA, "runs", "cross_scale_v10")
RES = os.path.join(ROOT, "results", "cross_scale_v10")


def main():
    rows = []
    for d in sorted(glob.glob(os.path.join(RUNS, "*"))):
        if not os.path.isdir(d):
            continue
        n, cpu, chk, st = 0, 0.0, 0.0, collections.Counter()
        for p in glob.glob(os.path.join(d, "*.json")):
            if p.endswith(("progress.json", "effective_plan.json")):
                continue
            r = json.load(open(p))
            n += 1
            cpu += r["cpu"]
            chk += (r.get("verification") or {}).get("cpu") or 0.0
            st[r["status"]] += 1
        prog = os.path.join(d, "progress.json")
        running = json.load(open(prog)).get("jobs", []) if os.path.exists(prog) else []
        live = sum(j["cpu"] for j in running) if running and json.load(open(prog)).get("running") else 0.0
        rows.append((os.path.basename(d), n, cpu, chk, dict(st), live))
    gen = 0.0
    for m in ("pilot_manifest.json", "formal_manifest.json"):
        p = os.path.join(RES, m)
        if os.path.exists(p):
            gen += json.load(open(p))["gen_cpu_total"]
    lines = ["# v10 算力账本", "",
             "只记账，不设额度（[resource_policy.json](../../configs/resource_policy.json)）。每个运行单次上限 3600 CPU s（整棵进程树）。",
             "由 `scripts/cross_scale_v10/ledger.py` 从全部 v10 记录生成，包括冒烟测试、失败与重跑。", "",
             "| 阶段 | 记录数 | 求解 / wrapper CPU（核时） | 检查器 CPU（核时） | 状态 | 仍在运行的部分（核时） |",
             "|---|---:|---:|---:|---|---:|"]
    tot = tot_chk = tot_live = 0.0
    for name, n, cpu, chk, st, live in rows:
        lines.append(f"| `{name}` | {n} | {cpu / 3600:.3f} | {chk / 3600:.4f} | "
                     f"{', '.join(f'{k} {v}' for k, v in sorted(st.items()))} | {live / 3600:.3f} |")
        tot, tot_chk, tot_live = tot + cpu, tot_chk + chk, tot_live + live
    lines += [f"| **合计** | | **{tot / 3600:.3f}** | **{tot_chk / 3600:.4f}** | | {tot_live / 3600:.3f} |", "",
              f"- 实例生成 CPU：{gen / 3600:.4f} 核时（试采样与正式清单）。",
              f"- v10 合计（求解 + 检查 + 生成）：**{(tot + tot_chk + gen) / 3600:.3f} 核时**。"]
    os.makedirs(RES, exist_ok=True)
    open(os.path.join(RES, "COMPUTE.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
