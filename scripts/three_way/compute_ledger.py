#!/usr/bin/env python3
"""Compute ledger of the three-way stage (new CPU only; reused round-1 runs
are listed but not charged). Writes results/three_way/COMPUTE.md.

  python3 scripts/three_way/compute_ledger.py
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import twdata as TD  # noqa: E402
import fprun  # noqa: E402

ROOT = TD.ROOT
FROZEN = os.path.join(ROOT, "configs", "three_way", "frozen")


def vcpu(rec):
    return ((rec or {}).get("verification") or {}).get("cpu") or 0.0


def main():
    rows = []
    for exp in ("tw_dev_fixed", "tw_test_fixed"):
        fx = TD.fixed_records(os.path.join(ROOT, "configs", "three_way", f"{exp}.json"))
        recs = [r for h in fx for r in fx[h].values()]
        new = [r for r in recs if r.get("exp") == exp]
        reused = [r for r in recs if r.get("exp") not in (None, exp) and r.get("status") != "missing"]
        rows.append((f"{exp}：新固定运行", len(new), sum(r["cpu"] for r in new), sum(vcpu(r) for r in new),
                     f"复用第一轮 {len(reused)} 次（不计）"))
    for kind, split, label in (("profile", "dev", "dev 静态特征"), ("probe", "dev", "dev D 试跑（3 个预算）")):
        recs = [r for r in TD.twrun_records(kind, TD.hashes_file(split)).values() if r]
        cpu = sum(r["profile"]["cpu"] if kind == "profile" else r["cpu"] for r in recs)
        rows.append((label, len(recs), cpu, sum(vcpu(r) for r in recs), ""))
    for m in ("static", "probe"):
        recs = [r for r in TD.twrun_records("wrap", TD.hashes_file("test"), model=os.path.join(FROZEN, f"{m}.json")).values() if r]
        rows.append((f"test wrapper：{m}", len(recs), sum(r["total_cpu"] for r in recs), sum(vcpu(r) for r in recs), ""))
    smoke = os.path.join(fprun.DATA, "three_way_smoke")
    s_cpu, s_n = 0.0, 0
    for p in glob.glob(os.path.join(smoke, "out*", "wrap", "*", "*.json")):
        s_cpu += json.load(open(p))["total_cpu"]; s_n += 1
    for p in glob.glob(os.path.join(smoke, "out*", "probe", "*", "*.json")):
        s_cpu += json.load(open(p))["cpu"]; s_n += 1
    for p in glob.glob(os.path.join(smoke, "out*", "profile", "*", "*.json")):
        s_cpu += json.load(open(p))["profile"]["cpu"]; s_n += 1
    fc = 0.0
    for p in glob.glob(os.path.join(smoke, "frozen_check", "*", "result.json")):
        r = json.load(open(p))
        fc += (r.get("overhead_cpu") or 0) + ((r.get("formal") or {}).get("cpu") or 0)
    rows.append(("工程 smoke（6 个 train 实例）与冻结后部署检查（3 个 train 实例，20 s）", s_n, s_cpu + fc, 0.0, ""))
    # incomplete attempts
    inc = 0
    for p in glob.glob(os.path.join(fprun.DATA, "runs", "attempts", "tw_*.jsonl")):
        ev = {}
        for l in open(p):
            x = json.loads(l)
            ev.setdefault(x["run_id"], set()).add(x.get("event"))
        inc += sum(1 for v in ev.values() if "start" in v and "done" not in v)
    errs = 0
    for p in glob.glob(os.path.join(fprun.DATA, "runs", "three_way", "attempts", "*.jsonl")):
        errs += sum('"runner-error"' in l for l in open(p))
    tot_s = sum(r[2] for r in rows)
    tot_c = sum(r[3] for r in rows)
    L = ["# 三选一阶段的算力账本", "", "由 `scripts/three_way/compute_ledger.py` 生成；只计本阶段新产生的 CPU（单核 CPU 时间之和）。"
         "复用的第一轮运行列出但不计入。", "",
         "| 项 | 记录数 | 求解 / 工具 CPU 核时 | 检查器 CPU 核时 | 备注 |", "|---|---:|---:|---:|---|"]
    for name, n, s, c, note in rows:
        L.append(f"| {name} | {n} | {s / 3600:.2f} | {c / 3600:.2f} | {note} |")
    L += [f"| **合计** | | **{tot_s / 3600:.2f}** | **{tot_c / 3600:.2f}** | 总计 {(tot_s + tot_c) / 3600:.2f} 核时（上限 200） |", "",
          f"- 中断 / 未完成的 fprun 尝试：{inc} 次；twrun 运行器错误：{errs} 次。",
          "- 独占节点的墙钟占用（每节点 48 个并发）未计入上表；上表是 CPU 时间。"]
    open(os.path.join(ROOT, "results", "three_way", "COMPUTE.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
