#!/usr/bin/env python3
"""R2 engineering on the 12-instance panel (protocol section 3): v5 local
search non-reproducibility, obsprofile6 reproducibility and cost for
W in {10000, 50000}, SATzilla group coverage and cost; applies the
pre-registered choice rules (no solver outcome is read).

  python3 scripts/stable_selection_v6/r2_engineering.py

Writes results/stable_selection_v6/r2_choices.json and
reports/stable_selection_v6/R2_ENGINEERING_TABLES.md.
"""

import collections
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v6run  # noqa: E402
import szlib  # noqa: E402

ROOT = v6run.fprun.ROOT
ENG = os.path.join(ROOT, "configs", "stable_selection_v6", "eng12.txt")
RES = os.path.join(ROOT, "results", "stable_selection_v6")
REP = os.path.join(ROOT, "reports", "stable_selection_v6")


def load(argv):
    a = v6run.parser().parse_args(argv)
    out = collections.defaultdict(list)
    for k, key, rid in v6run.plan(a):
        p = v6run.rec_path(k, rid)
        out[(key["instance"], key.get("flips"), tuple(key.get("groups") or []))].append(
            json.load(open(p)) if os.path.exists(p) else None)
    return out


def differing(recs, prefix=None):
    fs = [r["features"] for r in recs if r]
    if len(fs) < 2:
        return None
    keys = set().union(*fs)
    return sorted(k for k in keys if (prefix is None or k.startswith(prefix)) and len({json.dumps(f.get(k)) for f in fs}) > 1)


def main():
    os.makedirs(RES, exist_ok=True)
    os.makedirs(REP, exist_ok=True)
    eng = [l.split()[0] for l in open(ENG) if l.strip() and not l.startswith("#")]
    L = ["# R2 工程表（工程 12 题；由 `scripts/stable_selection_v6/r2_engineering.py` 生成）", ""]
    # v5 local search control
    v5 = load(["obs5ls", "--hashes", ENG, "--reps", "3"])
    rows = []
    nd = 0
    for h in eng:
        rs = v5[(h, None, ())]
        d = differing(rs, "g")
        st = [r["sections"].get("ls", {}).get("status") for r in rs if r]
        nd += bool(d)
        rows.append(f"| {h[:10]} | {'/'.join(st)} | {len(d) if d is not None else '—'} |")
    L += ["## 1. v5 局部搜索（每起点 0.2 s CPU 截断）重复 3 次", "",
          f"12 题中 {nd} 题的局部搜索特征在 3 次重复之间不同（v5 的不可复现现象）。", "",
          "| 实例 | ls 状态（3 次） | 3 次之间不同的 g 特征数 |", "|---|---|---:|"] + rows + [""]
    # obs6
    o6 = load(["obs6", "--hashes", ENG, "--flips", "10000,50000", "--sections", "s28,resid,bilat,graph,ls", "--reps", "3"])
    choice = {}
    L += ["## 2. obsprofile6：固定翻转次数，重复 3 次", "",
          "| W | ls 正常完成 | ls 中位 CPU s | ls 最大 CPU s | 全部段正常 | 3 次之间任一非计时特征不同的题 |", "|---:|---:|---:|---:|---:|---:|"]
    for w in (10000, 50000):
        ok = cpu = 0
        cpus, allok, ndiff = [], 0, 0
        for h in eng:
            rs = [r for r in o6[(h, w, ())] if r]
            st = [r["sections"].get("ls", {}).get("status") for r in rs]
            ok += all(s == "ok" for s in st) and len(st) == 3
            cpus += [r["sections"]["ls"]["cpu"] for r in rs if "ls" in r["sections"]]
            allok += all(all(v.get("status") in ("ok", "off") for v in r["sections"].values()) for r in rs)
            d = differing(rs)
            ndiff += bool(d)
        med = statistics.median(cpus) if cpus else float("nan")
        choice[w] = {"ls_ok": ok, "ls_cpu_median": med, "ls_cpu_max": max(cpus) if cpus else None, "all_ok": allok,
                     "instances_with_differing_features": ndiff}
        L.append(f"| {w} | {ok}/12 | {med:.3f} | {max(cpus):.3f} | {allok}/12 | {ndiff} |")
    W = 50000 if choice[50000]["ls_ok"] >= 10 and choice[50000]["ls_cpu_median"] <= 0.3 else 10000
    L += ["", f"按预先固定的规则（W = 50,000 若 ≥ 10/12 正常完成且中位 CPU ≤ 0.3 s，否则 10,000）：**W = {W}**。", ""]
    # satzilla
    sz = load(["sz", "--hashes", ENG, "--per-group", "--cap", "3"])
    groups = []
    L += ["## 3. SATzilla 2024 各特征组（单独运行，3 s CPU 硬上限）", "",
          "| 组 | 正常完成 | 中位 CPU s | 最大 CPU s | 特征数（含保留值） | 保留值比例中位 | 入选 |", "|---|---:|---:|---:|---:|---:|:-:|"]
    sz_done = all(all(x is not None for x in v) for v in sz.values())
    for g in szlib.CANDIDATE_GROUPS:
        rs = [sz[(h, None, (g,))][0] for h in eng]
        rs = [r for r in rs if r]
        okn = sum(r["status"] == "ok" for r in rs)
        cpus = [r["cpu"] for r in rs]
        nf = [len(r["features"]) for r in rs if r["status"] == "ok"]
        rr = [r.get("n_reserved", 0) / max(1, len(r["features"])) for r in rs if r["status"] == "ok"]
        med = statistics.median(cpus) if cpus else float("nan")
        keep = okn >= 9 and med <= 0.5
        if keep:
            groups.append(g)
        L.append(f"| {g} | {okn}/{len(rs)} | {med:.3f} | {max(cpus) if cpus else float('nan'):.2f} | {max(nf) if nf else 0} | "
                 f"{statistics.median(rr) if rr else float('nan'):.0%} | {'✓' if keep else ''} |")
    L += ["", f"按预先固定的规则（≥ 9/12 正常完成且中位 CPU ≤ 0.5 s）：入选组 **{', '.join(groups) or '无'}**。"
          + ("" if sz_done else "（SATzilla 运行尚未全部完成）"), ""]
    json.dump({"ls_flips": W, "ls": choice, "satzilla_groups": groups, "satzilla_complete": sz_done,
               "v5_nonreproducible_instances": nd}, open(os.path.join(RES, "r2_choices.json"), "w"), indent=1)
    open(os.path.join(REP, "R2_ENGINEERING_TABLES.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
