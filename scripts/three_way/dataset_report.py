#!/usr/bin/env python3
"""Write reports/three_way/DATASET.md from the frozen sampling outputs.

  scripts/three_way/dataset_report.py   # reads results/three_way/{candidates,manifest,checksums}.csv
"""

import collections
import csv
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
R = os.path.join(ROOT, "results", "three_way")
YEARS = ["2022", "2023", "2024", "2025", "2026"]
SPLITS = ("train", "val", "test")


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" if i == 0 else "---:" for i in range(len(head))) + "|"]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return out


def main():
    cand = list(csv.DictReader(open(os.path.join(R, "candidates.csv"))))
    man = list(csv.DictReader(open(os.path.join(R, "manifest.csv"))))
    summ = json.load(open(os.path.join(R, "sampling_summary.json")))
    chk = {r["hash"]: r for r in csv.DictReader(open(os.path.join(R, "checksums.csv")))} \
        if os.path.exists(os.path.join(R, "checksums.csv")) else {}
    L = ["# 三选一研究的五年面板（2022–2026）", "",
         "由 `scripts/three_way/dataset_report.py` 从冻结的抽样输出生成。规则见 "
         "[THREE_WAY_PROTOCOL.md](../../docs/THREE_WAY_PROTOCOL.md) 第 2 节与 "
         "[FIVE_YEAR_SAMPLE_PLAN.md](../../docs/FIVE_YEAR_SAMPLE_PLAN.md)；只用元数据，未使用任何求解结果。", ""]
    L += ["## 1. 来源与重建", "",
          f"- GBD 快照 2026-10-18：meta.db `{summ['gbd']['meta.db']}`，base.db `{summ['gbd']['base.db']}`。",
          "- 官方名单（2026-10-22 下载，存于 `$FP_DATA/benchmarks/official/`），与 GBD 快照逐题一致："]
    for y, o in summ["official_lists"].items():
        L.append(f"  - {y}：`{o['file']}`，{o['n']} 题，sha256 `{o['sha256']}`")
    L += [f"- 抽样 seed {summ['seed']}；年度配额 {summ['quota']}；单家族组上限 {summ['cap']}；资源条件：GBD 未压缩字节 ≤ {summ['max_bytes']:.0e}。",
          f"- `results/three_way/manifest.csv` sha256 `{summ['manifest_sha256']}`；`candidates.csv` sha256 `{summ['candidates_sha256']}`。",
          "", "重建（只读元数据，确定性）：", "", "```bash",
          "export FP_DATA=/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase",
          "mkdir -p $FP_DATA/benchmarks/official && cd $FP_DATA/benchmarks/official",
          "for y in 2022 2023 2024 2025; do curl -sL -o gbd_getinstances_main_$y.txt \"https://benchmark-database.de/getinstances?track=main_$y\"; done",
          "curl -sL -o track_main_2026.uri https://satcompetition.github.io/2026/downloads/track_main_2026.uri",
          "cd - && scripts/three_way/sample_panel.py --gbd $FP_DATA/benchmarks/gbd --official $FP_DATA/benchmarks/official",
          "sha256sum results/three_way/manifest.csv   # 应为上面的值",
          "scripts/fetch_benchmarks.py --manifest results/three_way/manifest.csv --checksums results/three_way/checksums.csv --splits train,val,test",
          "```", "",
          "GBD 会持续更新；若重新下载的 meta/base 与上面的 sha256 不同，抽样结果可能不同。冻结面板以提交的 manifest 为准。", ""]

    # 2. per-year
    rows = []
    for y in YEARS:
        s = summ["years"][y]
        sel = [r for r in man if r["quota_year"] == y]
        rows.append([y, s["problems"], s["excluded_bytes"], s["eligible"], s["groups"], len(sel),
                     len({r["family_group"] for r in sel}), s["unused_quota"],
                     sum(r["replacement_rank"] != "" for r in cand if r["quota_year"] == y and r["eligible"] == "1"
                         and r["selected"] == "0")])
    L += ["## 2. 逐年候选、排除、入选与替补", ""]
    L += table(["配额年", "独立问题", "排除（>1 GB）", "合格", "家族组", "入选", "入选覆盖的组", "未用配额", "预排替补"], rows)
    multi = [r for r in cand if "+" in r["years"]]
    L += ["", f"- 五年主赛道共 2,000 个（hash，年份）条目，{len({h for r in cand for h in r['members'].split('+')})} 个不同 hash，"
          f"按 isohash 合并为 {len(cand)} 个独立问题；跨年出现的问题 {len(multi)} 个（只计一次，配额年取最早年份）。",
          f"- 面板中跨年出现的问题 {sum('+' in r['years'] for r in man)} 个；isohash 类有多个 hash 的 "
          f"{sum('+' in r['members'] for r in man)} 个。",
          f"- 下载：{sum(r['hash'] in chk for r in man)}/{len(man)} 个入选 CNF 已下载并记录校验（`results/three_way/checksums.csv`）；未发生替换。", ""]

    # 3. size
    L += ["## 3. 规模分布", "", "规模层按各配额年合格问题的 log10(1+子句数) 三分位：", ""]
    b = summ["strata_bounds_log10_clauses"]
    L += table(["配额年", "small / mid 界", "mid / large 界"], [[y, f"{b[y][0]:.2f}", f"{b[y][1]:.2f}"] for y in YEARS])
    L += [""]
    L += table(["split"] + list(("small", "mid", "large", ">100 MB", "≤10 MB")),
               [[s] + [sum(r["split"] == s and r["stratum"] == t for r in man) for t in ("small", "mid", "large")]
                + [sum(r["split"] == s and float(r["bytes"]) > 100e6 for r in man),
                   sum(r["split"] == s and float(r["bytes"]) <= 10e6 for r in man)] for s in SPLITS])
    # 4. splits x year
    L += ["", "## 4. 划分（按家族组）", ""]
    L += table(["split", "实例", "家族组"] + YEARS + ["第一轮运行过", "家族第一轮运行过", "GBD sat / unsat / unknown"],
               [[s, sum(r["split"] == s for r in man), len({r["family_group"] for r in man if r["split"] == s})]
                + [sum(r["split"] == s and r["quota_year"] == y for r in man) for y in YEARS]
                + [sum(r["split"] == s and r["prior_exposure"] != "none" for r in man),
                   sum(r["split"] == s and r["family_prior_exposure"] != "none" for r in man),
                   " / ".join(str(sum(r["split"] == s and r["gbd_result"] == x for r in man)) for x in ("sat", "unsat", "unknown"))]
                for s in SPLITS])
    exp = collections.Counter((r["split"], r["prior_exposure"]) for r in man)
    L += ["", "第一轮曝光明细（实例曾在哪个第一轮 split 中被运行）：", ""]
    L += table(["split"] + ["none", "train", "val", "test", "t2026"],
               [[s] + [sum(v for (sp, e), v in exp.items() if sp == s and (e == k or (k != "none" and k in e.split("+"))))
                       for k in ("none", "train", "val", "test", "t2026")] for s in SPLITS])
    L += ["", "注：GBD sat/unsat 只用于事后分层，不参与抽样、划分或选择器。", "",
          "## 5. 家族组覆盖", "", "每个家族组在面板中的实例数（按 split）：", ""]
    g = collections.defaultdict(lambda: collections.Counter())
    for r in man:
        g[r["family_group"]][r["split"]] += 1
        g[r["family_group"]]["years"] = 0
    yrs = collections.defaultdict(set)
    for r in man:
        yrs[r["family_group"]].add(r["quota_year"])
    rows = []
    for k in sorted(g, key=lambda k: (-sum(g[k][s] for s in SPLITS), k)):
        s = next(x for x in SPLITS if g[k][x])
        rows.append([k, s, sum(g[k][x] for x in SPLITS), ",".join(sorted(yrs[k])),
                     "yes" if any(r["family_prior_exposure"] != "none" for r in man if r["family_group"] == k) else "no"])
    L += table(["家族组", "split", "实例", "配额年", "第一轮运行过该家族"], rows)
    L += ["", "## 6. 局限", "",
          "- 代表性指“在可获取、≤1 GB 的主赛道问题中覆盖家族与规模”，不是对全部 SAT 应用或全部比赛题的无偏样本；pooled 结果是设计性抽样的结果，不能直接当作竞赛总体均值。",
          "- test 以第一轮未运行的实例为优先，因而偏向 2022 年与大规模层；只有 44 个 test 实例的家族在第一轮从未被运行，其余 55 个所在家族第一轮出现过（20 个实例本身有第一轮结果）。test 不是完全独立的新盲测。",
          "- 超过 1 GB 的 68 个问题被排除（多为 2022–2024 年的大实例），结论不适用于这一规模层。"]
    os.makedirs(os.path.join(ROOT, "reports", "three_way"), exist_ok=True)
    open(os.path.join(ROOT, "reports", "three_way", "DATASET.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L[:60]))


if __name__ == "__main__":
    main()
