#!/usr/bin/env python3
"""CPU ledger of goal v6 (new CPU only; reused runs listed, not charged).

  python3 scripts/stable_selection_v6/compute_ledger.py

Writes results/stable_selection_v6/COMPUTE.md.
"""

import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import fprun  # noqa: E402

ROOT = fprun.ROOT
OUT = os.path.join(fprun.DATA, "runs", "stable_selection_v6")
BEFORE = 122.28
CAP_V6, CAP = 60.0, 200.0
ANALYSIS_ESTIMATE_H = 2.0  # SATzilla build/tests, host smoke, model fitting and reports (upper bound)


def vcpu(r):
    return ((r or {}).get("verification") or {}).get("cpu") or 0.0


def main():
    tool_now = fprun.sha256_file(os.path.join(ROOT, "build", "tools", "obsprofile6"))
    acc = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for kind in ("obs6", "obs5ls", "sz", "wrap"):
        for p in glob.glob(os.path.join(OUT, kind, "*", "*.json")):
            r = json.load(open(p))
            k = r["key"]
            if kind == "wrap":
                lab = "wrapper (validation)" if "final" in k["strategy"] else "wrapper (R3 check30)"
                cpu = r["total_cpu"]
            elif kind == "obs6":
                lab = "obsprofile6" + ("" if k["tool_sha256"] == tool_now else " (before the cap-check fix, superseded)")
                cpu = r["cpu"]
            else:
                lab = {"obs5ls": "v5 local-search control (eng12)", "sz": "SATzilla 2024 subset"}[kind]
                cpu = r["cpu"]
            acc[lab][0] += 1
            acc[lab][1] += cpu
            acc[lab][2] += vcpu(r)
    rows = sorted(acc.items())
    fx = []
    for exp in ("v6_seed1", "v6_seed2", "v6_validate_fixed"):
        e = fprun.load_experiment(os.path.join(ROOT, "configs", "stable_selection_v6", f"{exp}.json"))
        n = s = c = reused = 0
        for run in fprun.plan(e):
            p = fprun.result_path(run["run_id"])
            if not os.path.exists(p):
                continue
            r = json.load(open(p))
            if r.get("exp") == exp:
                n += 1
                s += r.get("cpu") or 0.0
                c += vcpu(r)
            else:
                reused += 1
        fx.append((exp, n, s, c, reused))
    L = ["# Goal v6 的算力账本", "", "由 `scripts/stable_selection_v6/compute_ledger.py` 生成；只计 v6 新产生的 CPU，复用的运行列出但不计。", "",
         "| 项 | 记录数 | 求解 / 工具 CPU 核时 | 检查器 CPU 核时 | 备注 |", "|---|---:|---:|---:|---|"]
    ts = tc = 0.0
    for exp, n, s, c, reused in fx:
        L.append(f"| fprun 固定运行 {exp} | {n} | {s / 3600:.2f} | {c / 3600:.2f} | 复用 {reused} 次（不计） |")
        ts += s
        tc += c
    for lab, (n, s, c) in rows:
        L.append(f"| {lab} | {n} | {s / 3600:.2f} | {c / 3600:.2f} | |")
        ts += s
        tc += c
    L.append(f"| SATzilla 构建与测试、主机 smoke、建模与报告（估计上限） | — | {ANALYSIS_ESTIMATE_H:.2f} | — | |")
    ts += ANALYSIS_ESTIMATE_H * 3600
    v6 = (ts + tc) / 3600
    L += [f"| **合计** | | **{ts / 3600:.2f}** | **{tc / 3600:.2f}** | |", "",
          f"- v6 合计 {v6:.2f} 核时（v6 上限 {CAP_V6:.0f}）；v6 之前累计 {BEFORE:.2f}，现累计 {BEFORE + v6:.2f}（上限 {CAP:.0f}）。",
          "- 独占节点的墙钟占用未计入；上表是 CPU 时间。"]
    open(os.path.join(ROOT, "results", "stable_selection_v6", "COMPUTE.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
