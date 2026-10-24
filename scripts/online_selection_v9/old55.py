#!/usr/bin/env python3
"""v9 R5: status of the original 55-instance v7 panel with the unrestricted recovery stages
(docs/OLD55_RECOVERY_V9.md). Leaves results/completion_v7 untouched; writes results/online_selection_v9/old55/
{normalized.json, attempts.csv, summary.json} and reports/online_selection_v9/OLD55_PROGRESS_TABLES.md.

  old55.py
"""
import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
OUT = os.path.join(ROOT, "results", "online_selection_v9", "old55")
REP = os.path.join(ROOT, "reports", "online_selection_v9")
STAGES = "stage1,stage2,old55_r1a,old55_r1b"
METHODS = ("D", "Fp", "Fm", "P1_M05_long")


def main():
    os.makedirs(OUT, exist_ok=True)
    py = sys.executable
    subprocess.run([py, os.path.join(ROOT, "scripts", "completion_v7", "normalize.py"), "--stages", STAGES,
                    "--res-dir", OUT, "--data-copy", os.path.join(DATA, "runs", "online_selection_v9", "old55_normalized.json")],
                   check=True, stdout=subprocess.DEVNULL)
    subprocess.run([py, os.path.join(ROOT, "scripts", "completion_v7", "evaluate.py"), "--config",
                    os.path.join(ROOT, "configs", "completion_v7", "protocol.json"), "--runs", os.path.join(OUT, "normalized.json"),
                    "--out", os.path.join(OUT, "summary.json"), "--allow-incomplete"], check=True, stdout=subprocess.DEVNULL)
    s = json.load(open(os.path.join(OUT, "summary.json")))
    norm = {(r["instance"], r["method"]): r for r in json.load(open(os.path.join(OUT, "normalized.json")))}
    running = {}
    for st in ("old55_r1a", "old55_r1b"):
        p = os.path.join(DATA, "runs", "completion_v7", st, "progress.json")
        if os.path.exists(p):
            for j in json.load(open(p))["jobs"]:
                if j["state"] != "finished":
                    running[(j["instance"], j["method"])] = j["cpu"]
    v7 = json.load(open(os.path.join(ROOT, "results", "completion_v7", "summary.json")))
    L = ["# 原 55 题恢复进度（由 `scripts/online_selection_v9/old55.py` 生成）", "",
         f"更新：{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}。阶段：{STAGES}（docs/OLD55_RECOVERY_V9.md）。", "",
         "| 方法 | v7 结束时完成数 | 现在完成数 | 完整平均 CPU |", "|---|---:|---:|---|"]
    for m in METHODS:
        v = s["methods"][m]
        L.append(f"| {m} | {v7['methods'][m]['completed']}/55 | {v['completed']}/55 | "
                 f"{'null（未全部完成）' if v['mean_cpu_seconds'] is None else round(v['mean_cpu_seconds'], 2)} |")
    L.append(f"| oracle（已确定） | {v7['oracle']['completed']}/55 | {s['oracle']['completed']}/55 | "
             f"{'null' if s['oracle']['mean_cpu_seconds'] is None else round(s['oracle']['mean_cpu_seconds'], 2)} |")
    L += ["", "## 未完成或 oracle 待定的题", "", "| 实例 | D | F+ | F− | P1_M05_long | oracle 待定动作 |", "|---|---|---|---|---|---|"]
    unres = {u["instance"]: u["unresolved_actions"] for u in s["oracle"]["unresolved"]}
    insts = sorted({h for (h, m), r in norm.items() if r["status"] != "solved"} | set(unres))
    for h in insts:
        cells = []
        for m in METHODS:
            r = norm.get((h, m))
            run = running.get((h, m)) or (running.get((h, "P1_M05_long")) if m == "D" else None)
            if r and r["status"] == "solved":
                cells.append(f"{r['cpu_seconds']:.0f} s")
            elif run is not None:
                cells.append(f"运行中 ≥ {run:.0f} s")
            elif r and r.get("cpu_seconds") is not None:
                cells.append(f"≥ {r['cpu_seconds']:.0f} s（{r['status']}）")
            else:
                cells.append("—")
        L.append(f"| {h[:10]} | " + " | ".join(cells) + f" | {'/'.join(unres.get(h, [])) or '已确定'} |")
    open(os.path.join(REP, "OLD55_PROGRESS_TABLES.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
