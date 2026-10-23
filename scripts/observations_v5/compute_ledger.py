#!/usr/bin/env python3
"""CPU ledger of goal v5 (new CPU only; v4 runs reused, not charged).

  python3 scripts/observations_v5/compute_ledger.py

Sums the process CPU of every v5 record (obsprofile, probe arms, equivalence
gate, observe-only and real wrappers -- superseded first collection
included), the fixed fprun experiments of v5 (seed-1 repeat, confirmation),
checker CPU, the smoke runs, and an upper-bound estimate of the analysis CPU.
Writes results/observations_v5/COMPUTE.md.
"""

import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "three_way"))
import fprun  # noqa: E402

ROOT = fprun.ROOT
OUT = os.path.join(fprun.DATA, "runs", "observations_v5")
V4_TOTAL = 39.90
CAP = 200.0
ANALYSIS_ESTIMATE_H = 3.0  # upper bound for model fitting / screening on the analysis node


def vcpu(rec):
    return ((rec or {}).get("verification") or {}).get("cpu") or 0.0


def main():
    vers = json.load(open(os.path.join(ROOT, "results", "observations_v5", "record_versions.json")))
    name = {v: k for k, v in vers.items() if isinstance(v, str) and len(v) == 64}
    acc = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for kind in ("obs", "arm", "eqv", "wrap"):
        for p in glob.glob(os.path.join(OUT, kind, "*", "*.json")):
            r = json.load(open(p))
            k = r["key"]
            batch = name.get(k["code_sha256"], "first_gate_runner_version")
            if kind == "obs":
                cpu = r["cpu"]
            elif kind == "arm":
                cpu = r["cpu"]
            elif kind == "eqv":
                cpu = r["formal"]["cpu"] + r["probe"]["cpu"]
            else:
                cpu = r["total_cpu"]
                kind_l = "wrap (observe-only, kappa)" if k.get("observe_only") else "wrap (real)"
            lab = (kind if kind != "wrap" else kind_l, batch)
            acc[lab][0] += 1
            acc[lab][1] += cpu
            acc[lab][2] += vcpu(r)
    smoke = 0.0
    sn = 0
    for p in glob.glob(os.path.join(fprun.DATA, "v5_smoke", "out", "*", "*", "*.json")):
        r = json.load(open(p))
        smoke += r.get("cpu") or r.get("total_cpu") or (r.get("formal", {}).get("cpu", 0) + r.get("probe", {}).get("cpu", 0))
        sn += 1
    fx = []
    for exp in ("v5_seed1", "v5_confirm_fixed"):
        e = fprun.load_experiment(os.path.join(ROOT, "configs", "observations_v5", f"{exp}.json"))
        n = s = c = 0
        for run in fprun.plan(e):
            p = fprun.result_path(run["run_id"])
            if os.path.exists(p):
                r = json.load(open(p))
                if r.get("exp") == exp:
                    n += 1
                    s += r.get("cpu") or 0.0
                    c += vcpu(r)
        fx.append((exp, n, s, c))
    L = ["# Goal v5 的算力账本", "",
         "由 `scripts/observations_v5/compute_ledger.py` 生成；只计 v5 新产生的 CPU（单核 CPU 时间之和），复用的 v4/第一轮运行不计。", "",
         "| 项 | 批次 | 记录数 | 求解 / 工具 CPU 核时 | 检查器 CPU 核时 |", "|---|---|---:|---:|---:|"]
    tot_s = tot_c = 0.0
    for (kind, batch), (n, s, c) in sorted(acc.items()):
        L.append(f"| {kind} | {batch} | {n} | {s / 3600:.2f} | {c / 3600:.2f} |")
        tot_s += s
        tot_c += c
    for exp, n, s, c in fx:
        L.append(f"| fprun 固定运行 | {exp} | {n} | {s / 3600:.2f} | {c / 3600:.2f} |")
        tot_s += s
        tot_c += c
    L.append(f"| 工程 smoke（2 个 dev 实例，容器内） | v5_smoke | {sn} | {smoke / 3600:.2f} | 0.00 |")
    tot_s += smoke
    L.append(f"| 建模、筛查与报告（分析节点，估计上限） | — | — | {ANALYSIS_ESTIMATE_H:.2f} | — |")
    tot_s += ANALYSIS_ESTIMATE_H * 3600
    v5 = (tot_s + tot_c) / 3600
    L += [f"| **合计** | | | **{tot_s / 3600:.2f}** | **{tot_c / 3600:.2f}** | ",
          "", f"- v5 合计 {v5:.2f} 核时；加上 v4 的 {V4_TOTAL:.2f}，v4 之后累计 {V4_TOTAL + v5:.2f} 核时（上限 {CAP:.0f}）。",
          "- `superseded_first_collection` 是协议偏离 1–2 之前的第一次采集，已作废但照常计费。",
          "- 主机上的工具 smoke（11 个实例的 obsprofile 和 2 万冲突等价检查，几分钟）未逐项计量，包含在分析估计上限中。",
          "- 独占节点的墙钟占用（每节点 48 个并发）未计入；上表是 CPU 时间。"]
    open(os.path.join(ROOT, "results", "observations_v5", "COMPUTE.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
