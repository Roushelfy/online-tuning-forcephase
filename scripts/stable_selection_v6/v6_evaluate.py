#!/usr/bin/env python3
"""Real-run evaluation of goal v6: the R3 wrapper check on check30 (fold models)
and, with --validate, the frozen R4 validation (protocol sections 4-5).

  $FP_PY scripts/stable_selection_v6/v6_evaluate.py [--validate]

Real cost = whole wrapper process tree CPU if the verified answer is within
T, else 600. Writes results/stable_selection_v6/{check30.csv, validate.csv},
reports/stable_selection_v6/{CHECK_TABLES.md, VALIDATION_TABLES.md},
figures/validation.png.
"""

import argparse
import csv
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "observations_v5"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "three_way"))
import twdata as TD  # noqa: E402
import v5select as VS  # noqa: E402
import v6run  # noqa: E402

ROOT = v6run.fprun.ROOT
RES = os.path.join(ROOT, "results", "stable_selection_v6")
REP = os.path.join(ROOT, "reports", "stable_selection_v6")
CFG = os.path.join(ROOT, "configs", "stable_selection_v6")
PAR2 = 600.0
LBL = {"D": "D", "Fp": "F+", "Fm": "F−"}


def wraps(hashes_file, strategy=None, strategy_map=None):
    argv = ["wrap", "--hashes", hashes_file] + (["--strategy", strategy] if strategy else ["--strategy-map", strategy_map])
    a = v6run.parser().parse_args(argv)
    out = {}
    for k, key, rid in v6run.plan(a):
        p = v6run.rec_path(k, rid)
        out[(key["instance"], key["strategy"])] = json.load(open(p)) if os.path.exists(p) else None
    return out


def real_cost(r):
    return r["total_cpu"] if r and r["status"] == "solved" else PAR2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()
    promoted = json.load(open(os.path.join(RES, "promoted.json")))["promoted"]
    # ---------------- R3 check30
    chk = os.path.join(CFG, "check30.txt")
    hs = [l.split()[0] for l in open(chk) if l.strip() and not l.startswith("#")]
    oof = {}
    for r in csv.DictReader(open(os.path.join(RES, "oof.csv"))):
        oof[(r["name"], r["hash"])] = r
    W = wraps(chk, strategy_map=os.path.join(CFG, "frozen", "strategy_map_dev.json"))
    rows = []
    for (h, s), rec in sorted(W.items()):
        name = [n for n in promoted if os.path.basename(s).startswith(n.replace("|", "_"))][0]
        o = oof[(name, h)]
        res = (rec or {}).get("result") or {}
        rows.append({"candidate": name, "hash": h, "group": o["group"], "sim_choice": o["choice"], "sim_cost": float(o["cost"]),
                     "real_status": (rec or {}).get("status"), "real_cost": real_cost(rec) if rec else None,
                     "real_action": res.get("action"), "path": res.get("path"), "static_cpu": res.get("static_cpu"),
                     "overhead_cpu": res.get("overhead_cpu"), "remaining": res.get("remaining"),
                     "wrapper_extra": (rec["total_cpu"] - (res.get("static_cpu") or 0) - ((res.get("formal") or {}).get("cpu") or 0)) if rec else None,
                     "cost_D_noobs": float(o["cost_D_noobs"])})
    with open(os.path.join(RES, "check30.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    done = [r for r in rows if r["real_cost"] is not None]
    L = ["# R3 真实 wrapper 检查（检查 30 题，折模型；由 `scripts/stable_selection_v6/v6_evaluate.py` 生成）", ""]
    if done:
        d = np.array([r["real_cost"] - r["sim_cost"] for r in done])
        agree = sum(r["real_action"] == r["sim_choice"] for r in done)
        L += [f"| 候选 | 完成 | 动作与离线一致 | 真实成本 − 模拟成本：中位 / 最大绝对差 | 观察 CPU 中位 / 最大 | wrapper 额外 CPU 中位 | 观察不完整 | 真实 PAR2（同题始终 D） |",
              "|---|---:|---:|---|---|---:|---:|---|",
              f"| {promoted[0]} | {len(done)}/{len(rows)} | {agree}/{len(done)} | {np.median(d):+.3f} / {np.max(np.abs(d)):.1f} | "
              f"{np.median([r['static_cpu'] for r in done]):.3f} / {max(r['static_cpu'] for r in done):.2f} | "
              f"{np.median([r['wrapper_extra'] for r in done]):.3f} | {sum(r['path'] != 'reader' for r in done)} | "
              f"{np.mean([r['real_cost'] for r in done]):.2f}（{np.mean([r['cost_D_noobs'] for r in done]):.2f}） |", ""]
        big = sorted(done, key=lambda r: -abs(r["real_cost"] - r["sim_cost"]))[:5]
        L += ["差别最大的实例：", "", "| 实例 | 组 | 模拟动作 | 真实动作 / 路径 | 模拟成本 | 真实成本 |", "|---|---|---|---|---:|---:|"]
        for r in big:
            L.append(f"| {r['hash'][:12]} | {r['group']} | {r['sim_choice']} | {r['real_action']} / {r['path']} | {r['sim_cost']:.1f} | {r['real_cost']:.1f} |")
        L.append("")
    open(os.path.join(REP, "CHECK_TABLES.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))
    if not a.validate:
        return
    # ---------------- R4 validation
    vf = os.path.join(CFG, "validate_hashes.txt")
    vl = [l.split() for l in open(vf) if l.strip() and not l.startswith("#")]
    info = {x[0]: {"year": x[1], "stratum": x[2], "family": x[3], "family_in_dev": int(x[4])} for x in vl}
    fx = TD.fixed_records(os.path.join(CFG, "v6_validate_fixed.json"))
    finals = [os.path.join(CFG, "frozen", n.replace("|", "_") + "_final.json") for n in promoted]
    WV = wraps(vf, strategy=",".join(finals))
    vrows = []
    for h in sorted(info):
        r = {"hash": h, **info[h]}
        for act in ("D", "Fp", "Fm"):
            rec = fx[h][act]
            r[f"status_{act}"] = rec.get("status")
            r[f"cost_{act}"] = TD.cost(rec) if rec.get("status") != "missing" else None
            r[f"host_{act}"] = rec.get("host")
        for n, fpath in zip(promoted, finals):
            rec = WV.get((h, os.path.relpath(fpath, ROOT)))
            res = (rec or {}).get("result") or {}
            r[f"cost_{n}"] = real_cost(rec) if rec else None
            r[f"status_{n}"] = (rec or {}).get("status")
            r[f"action_{n}"] = res.get("action")
            r[f"path_{n}"] = res.get("path")
            r[f"static_{n}"] = res.get("static_cpu")
            r[f"host_{n}"] = (rec or {}).get("host")
        vrows.append(r)
    with open(os.path.join(RES, "validate.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(vrows[0]))
        w.writeheader()
        w.writerows(vrows)
    miss = sum(v is None for r in vrows for k, v in r.items() if k.startswith("cost_"))
    L = ["# R4 验证（冻结后；由 `scripts/stable_selection_v6/v6_evaluate.py --validate` 生成）", "",
         f"{len(vrows)} 题、{len({r['family'] for r in vrows})} 个家族组；缺失运行 {miss}。", ""]
    if miss == 0:
        for subset, sel in (("全部", lambda r: True), ("非 dev 家族", lambda r: r["family_in_dev"] == 0)):
            rs = [r for r in vrows if sel(r)]
            boot = VS.Boot([r["family"] for r in rs])
            cD = np.array([r["cost_D"] for r in rs])
            L += [f"## {subset}（{len(rs)} 题，{len({r['family'] for r in rs})} 个家族组）", "",
                  "| 策略 | 解出 | PAR2 | 相对 D 的净收益 [95% 家族 cluster 区间] | 偏离 F+/F− | 观察不完整 |", "|---|---:|---:|---|---|---:|"]
            series = [("D", "cost_D", None), ("F+", "cost_Fp", None), ("F−", "cost_Fm", None)] + \
                [(f"{n}（冻结）", f"cost_{n}", n) for n in promoted]
            orc = np.array([min(r["cost_D"], r["cost_Fp"], r["cost_Fm"]) for r in rs])
            for lab, col, n in series:
                x = np.array([r[col] for r in rs])
                g, lo, hi = boot.mean_ci(cD - x)
                dev = inc = ""
                if n:
                    dev = f"{sum(r[f'action_{n}'] == 'Fp' for r in rs)}/{sum(r[f'action_{n}'] == 'Fm' for r in rs)}"
                    inc = str(sum(r[f"path_{n}"] != "reader" for r in rs))
                L.append(f"| {lab} | {int((x < PAR2).sum())} | {x.mean():.2f} | {100 * g / cD.mean():+.1f}% [{100 * lo / cD.mean():+.1f}, {100 * hi / cD.mean():+.1f}] | {dev} | {inc} |")
            g, lo, hi = boot.mean_ci(cD - orc)
            L += [f"| 事后最优（不可部署） | {int((orc < PAR2).sum())} | {orc.mean():.2f} | {100 * g / cD.mean():+.1f}% [{100 * lo / cD.mean():+.1f}, {100 * hi / cD.mean():+.1f}] | | |", ""]
        n = promoted[0]
        L += ["## 逐题：策略与 D 成本不同（差 > 1 s）的实例", "", "| 实例 | 家族 | 规模 | 路径 | 动作 | D | F+ | F− | 策略 |", "|---|---|---|---|---|---:|---:|---:|---:|"]
        for r in vrows:
            if abs(r[f"cost_{n}"] - r["cost_D"]) > 1:
                L.append(f"| {r['hash'][:10]} | {r['family']} | {r['stratum']} | {r[f'path_{n}']} | {LBL.get(r[f'action_{n}'], r[f'action_{n}'])} | "
                         f"{r['cost_D']:.1f} | {r['cost_Fp']:.1f} | {r['cost_Fm']:.1f} | {r[f'cost_{n}']:.1f} |")
        L.append("")
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            boot = VS.Boot([r["family"] for r in vrows])
            names = ["D", "F+", "F−"] + [f"{p} (frozen)" for p in promoted] + ["oracle"]
            vals = [np.array([r["cost_D"] for r in vrows]), np.array([r["cost_Fp"] for r in vrows]),
                    np.array([r["cost_Fm"] for r in vrows])] + [np.array([r[f"cost_{p}"] for r in vrows]) for p in promoted] + \
                [np.array([min(r["cost_D"], r["cost_Fp"], r["cost_Fm"]) for r in vrows])]
            ci = [boot.mean_ci(v) for v in vals]
            fig, ax = plt.subplots(figsize=(7, 3.6))
            ax.bar(range(len(names)), [c[0] for c in ci], yerr=[[c[0] - c[1] for c in ci], [c[2] - c[0] for c in ci]], capsize=3)
            ax.set_xticks(range(len(names)))
            ax.set_xticklabels(names, fontsize=8)
            ax.set_ylabel("mean PAR2 (s), 95% family cluster bootstrap")
            ax.set_title(f"v6 validation ({len(vrows)} new problems, frozen before the runs)", fontsize=9)
            fig.tight_layout()
            fig.savefig(os.path.join(REP, "figures", "validation.png"), dpi=130)
            L += ["![验证](figures/validation.png)", ""]
        except ImportError:
            pass
    open(os.path.join(REP, "VALIDATION_TABLES.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
