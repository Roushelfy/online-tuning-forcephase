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
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import run_timeout_policy  # noqa: E402

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
            s = r["status"]
            if s == "error" and run_timeout_policy.is_timeout(r["cpu"], r["key"], r.get("exit_code")):
                s = "policy_timeout*"  # SIGXCPU at the cap stored as 'error' (results/cross_scale_v10/status_corrections.json)
            st[s] += 1
        prog = os.path.join(d, "progress.json")
        pj = json.load(open(prog)) if os.path.exists(prog) else {}
        live = sum(j["cpu"] for j in pj.get("jobs", [])) if pj.get("running") else 0.0
        job = str(pj.get("slurm_job") or "")
        alive = bool(job) and bool(subprocess.run(["squeue", "-h", "-j", job], capture_output=True, text=True).stdout.strip())
        rows.append((os.path.basename(d), n, cpu, chk, dict(st), live if alive else 0.0, 0.0 if alive else live))
    gen = 0.0
    for m in ("pilot_manifest.json", "formal_manifest.json"):
        p = os.path.join(RES, m)
        if os.path.exists(p):
            gen += json.load(open(p))["gen_cpu_total"]
    lines = ["# v10 算力账本", "",
             "只记账，不设额度（[resource_policy.json](../../configs/resource_policy.json)）。每个运行单次上限 3600 CPU s（整棵进程树）。",
             "由 `scripts/cross_scale_v10/ledger.py` 从全部 v10 记录生成，包括冒烟测试、失败与重跑。", "",
             "| 阶段 | 记录数 | 求解 / wrapper CPU（核时） | 检查器 CPU（核时） | 状态 | 仍在运行（核时） | 平台中断损失，无记录（核时，上限估计） |",
             "|---|---:|---:|---:|---|---:|---:|"]
    tot = tot_chk = tot_live = tot_lost = 0.0
    for name, n, cpu, chk, st, live, lost in rows:
        lines.append(f"| `{name}` | {n} | {cpu / 3600:.3f} | {chk / 3600:.4f} | "
                     f"{', '.join(f'{k} {v}' for k, v in sorted(st.items()))} | {live / 3600:.3f} | {lost / 3600:.3f} |")
        tot, tot_chk, tot_live, tot_lost = tot + cpu, tot_chk + chk, tot_live + live, tot_lost + lost
    lines += [f"| **合计** | | **{tot / 3600:.3f}** | **{tot_chk / 3600:.4f}** | | {tot_live / 3600:.3f} | {tot_lost / 3600:.3f} |", "",
              "- `policy_timeout*`：被内核 CPU 上限（SIGXCPU）在 3600 s 处停止、原记为 `error` 的运行，见 `status_corrections.json` 与协议第 12 节。",
              "- 平台中断损失：作业被 Slurm 抢占时正在运行、没有写出记录的部分，按最后一次心跳计；`robust_dev` 的 2 个运行已在 `robust_dev_r2` 补跑。",
              f"- 实例生成 CPU：{gen / 3600:.4f} 核时（试采样与正式清单）。",
              f"- v10 合计（求解 + 检查 + 生成 + 平台中断损失）：**{(tot + tot_chk + gen + tot_lost) / 3600:.3f} 核时**。"]
    os.makedirs(RES, exist_ok=True)
    open(os.path.join(RES, "COMPUTE.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
