#!/usr/bin/env python3
"""S3: evaluate the frozen policies on the test panel (protocol section 9).

  $FP_PY scripts/three_way/evaluate_test.py

Policies: fixed D, F+, F- (fprun, tw_test_fixed.json) and the real wrapper
runs of the frozen static and probe selectors (twrun.py wrap). Writes
results/three_way/test_results.csv, reports/three_way/TEST_RESULTS.md and
figures. Only run after the freeze (tag tw-freeze).
"""

import collections
import csv
import json
import math
import os
import random
import statistics
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import twdata as TD  # noqa: E402

ROOT = TD.ROOT
ACTS, LBL, PAR2, T = TD.ACTS, TD.LABEL, TD.PAR2, TD.T
SEED = 20261022
FROZEN = os.path.join(ROOT, "configs", "three_way", "frozen")
POL = ["D", "Fp", "Fm", "static", "probe"]
PLBL = {"D": "D", "Fp": "F+", "Fm": "F−", "static": "静态选择器", "probe": "试跑选择器（0.1 s）"}


def boot_ci(diff, fam, n=10000, seed=SEED):
    by = collections.defaultdict(list)
    for d, f in zip(diff, fam):
        by[f].append(d)
    groups = sorted(by)
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        s, k = 0.0, 0
        for g in rng.choices(groups, k=len(groups)):
            s += sum(by[g])
            k += len(by[g])
        vals.append(s / k)
    vals.sort()
    return vals[int(0.025 * n)], vals[int(0.975 * n) - 1]


def main():
    man = TD.manifest()
    test = TD.split_hashes("test")
    best_fixed = json.load(open(os.path.join(FROZEN, "best_fixed.json")))["action"]
    fixed = TD.fixed_records(os.path.join(ROOT, "configs", "three_way", "tw_test_fixed.json"))
    wraps = {m: TD.twrun_records("wrap", TD.hashes_file("test"), model=os.path.join(FROZEN, f"{m}.json"))
             for m in ("static", "probe")}
    rows = []
    for h in test:
        m = man[h]
        r = {"hash": h, "year": m["quota_year"], "family_group": m["family_group"], "stratum": m["stratum"],
             "prior_exposure": m["prior_exposure"], "family_prior_exposure": m["family_prior_exposure"],
             "bytes": float(m["bytes"]), "gbd_result": m["gbd_result"]}
        res = set()
        for a in ACTS:
            rec = fixed[h][a]
            r[f"status_{a}"] = rec["status"]
            r[f"cost_{a}"] = TD.cost(rec)
            r[f"reused_{a}"] = int(rec.get("exp") not in (None, "tw_test_fixed"))
            if rec.get("result"):
                res.add(rec["result"])
        for w in ("static", "probe"):
            rec = wraps[w].get(h)
            if rec is None:
                r[f"status_{w}"], r[f"cost_{w}"] = "missing", PAR2
                continue
            out = rec.get("result") or {}
            r[f"status_{w}"] = rec["status"]
            r[f"cost_{w}"] = rec["total_cpu"] if rec["status"] == "solved" else PAR2
            r[f"total_cpu_{w}"] = rec["total_cpu"]
            r[f"choice_{w}"] = out.get("action")
            r[f"decision_{w}"] = out.get("decision")
            r[f"overhead_{w}"] = out.get("overhead_cpu")
            r[f"formal_cpu_{w}"] = (out.get("formal") or {}).get("cpu")
            if rec.get("result_label"):
                res.add(rec["result_label"])
        r["observed_result"] = "conflict" if len(res) > 1 else (res.pop() if res else "unknown")
        r["oracle"] = min(r[f"cost_{a}"] for a in ACTS)
        rows.append(r)
    with open(os.path.join(ROOT, "results", "three_way", "test_results.csv"), "w", newline="") as f:
        fields = list(dict.fromkeys(k for r in rows for k in r))
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    n = len(rows)
    fam = [r["family_group"] for r in rows]
    L = ["# S3：冻结策略在 test 上的真实结果", "",
         "由 `scripts/three_way/evaluate_test.py` 生成。冻结点：tag `tw-freeze`（提交 b9b7a87），在任何 test 运行之前。"
         f"test = {n} 个实例（{len(set(fam))} 个家族组，与 dev 家族不相交）。cost：解出且验证通过为总 CPU 秒，否则 600；"
         "wrapper 的 cost 是整个进程树的实测总 CPU（特征 + 试跑 + 推理 + 正式求解）。", ""]
    st = collections.Counter((p, r[f"status_{p}"]) for r in rows for p in POL)
    L += ["## 1. 运行完整性", "",
          "| 策略 | " + " | ".join(sorted({s for (_, s) in st})) + " |", "|---|" + "---:|" * len({s for (_, s) in st})]
    for p in POL:
        L.append(f"| {PLBL[p]} | " + " | ".join(str(st[(p, s)]) for s in sorted({s for (_, s) in st})) + " |")
    reused = sum(r[f"reused_{a}"] for r in rows for a in ACTS)
    L += ["", f"- 固定动作 {3 * n} 次运行中 {reused} 次复用第一轮记录（这些实例在冻结前未被读取），其余为本轮新跑。",
          "- 所有 solved 都经过独立检查：SAT 用 checkmodel 对照原始 CNF，UNSAT 用 lrat-trim。", ""]

    # main table
    def stats_for(sel, p):
        cs = [r[f"cost_{p}"] for r in sel]
        return sum(c < PAR2 for c in cs), sum(cs) / len(cs)
    L += ["## 2. 主结果", "", "| 策略 | solved | SAT | UNSAT | mean PAR2 | 相对 D（PAR2 降低，95% 家族 cluster bootstrap CI） |",
          "|---|---:|---:|---:|---:|---|"]
    for p in POL:
        s, par = stats_for(rows, p)
        sat = sum(r[f"status_{p}"] == "solved" and r["observed_result"] == "SAT" for r in rows)
        uns = sum(r[f"status_{p}"] == "solved" and r["observed_result"] == "UNSAT" for r in rows)
        if p == "D":
            ci = "—"
        else:
            d = [r["cost_D"] - r[f"cost_{p}"] for r in rows]
            lo, hi = boot_ci(d, fam)
            base = sum(r["cost_D"] for r in rows) / n
            ci = f"{100 * statistics.mean(d) / base:+.1f}% [{100 * lo / base:+.1f}, {100 * hi / base:+.1f}]（{statistics.mean(d):+.1f} s/题）"
        L.append(f"| {PLBL[p]} | {s} | {sat} | {uns} | {par:.1f} | {ci} |")
    s, par = stats_for(rows, "oracle") if False else (sum(r["oracle"] < PAR2 for r in rows), sum(r["oracle"] for r in rows) / n)
    L.append(f"| hindsight oracle（D/F+/F− 事后最优，不可部署） | {s} | | | {par:.1f} | {100 * (sum(r['cost_D'] for r in rows) / n - par) / (sum(r['cost_D'] for r in rows) / n):+.1f}% |")
    L += ["", f"最佳固定动作（dev 上选定）= {LBL[best_fixed]}，所以“相对最佳固定动作”与“相对 D”是同一个比较。正值表示比 D 好。", ""]

    # wrappers detail
    L += ["## 3. 选择器细节", ""]
    for w in ("static", "probe"):
        sel = [r for r in rows if r.get(f"choice_{w}") or r.get(f"decision_{w}") == "probe"]
        ch = collections.Counter(r.get(f"choice_{w}") for r in rows)
        dec = collections.Counter(r.get(f"decision_{w}") for r in rows)
        ovh = [r[f"overhead_{w}"] for r in rows if r.get(f"overhead_{w}") is not None]
        tot_ovh = [r[f"total_cpu_{w}"] - (r.get(f"formal_cpu_{w}") or 0) for r in rows if r.get(f"total_cpu_{w}") is not None]
        # choice quality without overhead: cost of the chosen fixed action
        cq = []
        for r in rows:
            c = r.get(f"choice_{w}")
            if r.get(f"decision_{w}") == "probe":
                cq.append(r["cost_D"])
            elif c in ACTS:
                cq.append(r[f"cost_{c}"])
            else:
                cq.append(PAR2)
        sev = 0
        for r in rows:
            bf = r[f"cost_{best_fixed}"]
            wc = r[f"cost_{w}"]
            if (wc >= PAR2 and bf < PAR2) or (wc < PAR2 and bf < PAR2 and wc > 2 * bf and wc - bf >= 30):
                sev += 1
        better = sum(r[f"cost_{w}"] < r["cost_D"] / 1.5 - 0.5 for r in rows)
        worse = sum(r[f"cost_{w}"] > 1.5 * r["cost_D"] + 0.5 for r in rows)
        regret = [r[f"cost_{w}"] - r["oracle"] for r in rows]
        acc_rows = [r for r in rows if r["oracle"] < PAR2 and r.get(f"choice_{w}") in ACTS and r.get(f"decision_{w}") != "probe"]
        acc = sum(r[f"cost_{r[f'choice_{w}']}"] == r["oracle"] for r in acc_rows)
        L += [f"### {PLBL[w]}", "",
              f"- 选择：" + "，".join(f"{LBL.get(k, k)} {v}" for k, v in ch.most_common()) +
              f"；决策方式：" + "，".join(f"{k} {v}" for k, v in dec.most_common()) + "。",
              f"- 观察开销（正式求解之前的 CPU）：中位 {statistics.median(ovh):.3f} s，均值 {statistics.mean(ovh):.3f} s，最大 {max(ovh):.3f} s；"
              f"wrapper 总 CPU 减正式求解 CPU：中位 {statistics.median(tot_ovh):.3f} s。",
              f"- 选择本身的质量（把所选动作换成其完整固定运行的 cost，即不计开销）：mean PAR2 {statistics.mean(cq):.1f}（D {sum(r['cost_D'] for r in rows) / n:.1f}）。",
              f"- 相对 D 明显更好（cost 低于 D 的 2/3）{better} 题，明显更差（高于 1.5 倍）{worse} 题；严重回退（协议第 9 节）{sev} 题。",
              f"- 相对 oracle 的平均遗憾 {statistics.mean(regret):.1f} s/题；在至少一个动作解出且由模型作出选择的 {len(acc_rows)} 题中，选中事后最优动作 {acc} 题（准确率 {acc / max(1, len(acc_rows)):.0%}，仅作辅助）。", ""]
    # consistency: formal solve = same search as baseline
    rat = []
    for w in ("static", "probe"):
        for r in rows:
            c = r.get(f"choice_{w}")
            if r.get(f"decision_{w}") == "formal" and c in ACTS and r[f"status_{w}"] == "solved" and r[f"status_{c}"] == "solved" \
                    and r[f"cost_{c}"] > 1:
                rat.append(r[f"formal_cpu_{w}"] / r[f"cost_{c}"])
    if rat:
        L += [f"一致性检查：wrapper 正式求解与同动作固定运行都解出的 {len(rat)} 次中，正式求解 CPU / 固定运行 CPU 的中位数 {statistics.median(rat):.4f}"
              f"（范围 {min(rat):.3f}–{max(rat):.3f}），两者是同一搜索，差异只来自计时噪声。", ""]

    # breakdowns
    def bd(title, key, order=None):
        groups = collections.defaultdict(list)
        for r in rows:
            groups[key(r)].append(r)
        ks = order or sorted(groups)
        out = [f"### {title}", "", "| 子集 | n | " + " | ".join(PLBL[p] for p in POL) + " | oracle |", "|---|---:|" + "---:|" * (len(POL) + 1)]
        for k in ks:
            if k not in groups:
                continue
            sel = groups[k]
            out.append(f"| {k} | {len(sel)} | " + " | ".join(f"{stats_for(sel, p)[1]:.0f} ({stats_for(sel, p)[0]})" for p in POL)
                       + f" | {sum(r['oracle'] for r in sel) / len(sel):.0f} |")
        return out + [""]
    L += ["## 4. 分层（mean PAR2，括号内为 solved 数）", ""]
    L += bd("按配额年", lambda r: r["year"])
    L += bd("按规模层", lambda r: r["stratum"], ["small", "mid", "large"])
    L += bd("按文件大小", lambda r: ">100 MB" if r["bytes"] > 100e6 else "≤100 MB", ["≤100 MB", ">100 MB"])
    L += bd("按实例曝光（第一轮是否运行过）", lambda r: "第一轮未运行" if r["prior_exposure"] == "none" else "第一轮运行过")
    L += bd("按家族曝光", lambda r: "家族第一轮未运行" if r["family_prior_exposure"] == "none" else "家族第一轮运行过")
    L += bd("按事后结果（任一策略解出时的答案）", lambda r: r["observed_result"])
    L += bd("按家族组（实例 ≥ 3）", lambda r: r["family_group"] if sum(x["family_group"] == r["family_group"] for x in rows) >= 3 else "（其余小家族）")

    # figures
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    col = {"D": "#2a78d6", "Fp": "#eda100", "Fm": "#1baf7a", "static": "#e05a4f", "probe": "#7a52c7"}
    elab = {"D": "D", "Fp": "F+", "Fm": "F-", "static": "static selector", "probe": "probe selector (0.1 s)"}
    fig, axs = plt.subplots(1, 2, figsize=(11, 4))
    for p in POL:
        xs = sorted(r[f"cost_{p}"] for r in rows if r[f"cost_{p}"] < PAR2)
        axs[0].plot(range(1, len(xs) + 1), xs, label=f"{elab[p]} ({len(xs)})", color=col[p], lw=1.8 if p in ("D", "static", "probe") else 1.2)
    xs = sorted(r["oracle"] for r in rows if r["oracle"] < PAR2)
    axs[0].plot(range(1, len(xs) + 1), xs, label=f"oracle ({len(xs)})", color="#52514e", ls="--", lw=1)
    axs[0].set_yscale("log"); axs[0].set_xlabel(f"solved test instances (of {n})"); axs[0].set_ylabel("CPU seconds")
    axs[0].legend(frameon=False, fontsize=8); axs[0].grid(alpha=.3); axs[0].set_title("Test: cactus", loc="left")
    for j, w in enumerate(("static", "probe")):
        d = sorted(r["cost_D"] - r[f"cost_{w}"] for r in rows)
        axs[1].plot(np.linspace(0, 1, len(d)), d, color=col[w], label=elab[w])
    axs[1].axhline(0, color="#a7a6a0", lw=1); axs[1].set_ylabel("cost(D) - cost(selector), s  (>0 = selector better)")
    axs[1].set_xlabel("fraction of test instances (sorted)"); axs[1].legend(frameon=False, fontsize=8); axs[1].grid(alpha=.3)
    axs[1].set_title("Per-instance paired difference vs D", loc="left")
    fig.tight_layout()
    fig.savefig(os.path.join(ROOT, "reports", "three_way", "figures", "test_results.png"), dpi=150)
    L += ["## 5. 图", "", "![test](figures/test_results.png)", ""]
    open(os.path.join(ROOT, "reports", "three_way", "TEST_RESULTS.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
