#!/usr/bin/env python3
"""v9 PRE_SOLVE tables from development data (results/online_selection_v9/dev_table.json, selection.py data).

  pre_solve.py  -> results/online_selection_v9/pre_solve.json and reports/online_selection_v9/PRE_SOLVE_TABLES.md

Per tau: probe-solved fraction, stop overshoot (probe CPU - tau for stopped probes), wrapper overhead
(q - probe CPU), answer reuse; development totals of all 14 time gates (no fitting: in-sample), always-D
and fixed actions; real REF ('D 2 s -> F+') vs the cost model (q(2) + t_Fp).
"""
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RES = os.path.join(ROOT, "results", "online_selection_v9")
REP = os.path.join(ROOT, "reports", "online_selection_v9")
P = json.load(open(os.path.join(ROOT, "configs", "online_selection_v9", "protocol.json")))
TAUS = P["selection"]["tau_grid"]
ACTS = ("D", "Fp", "Fm")


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))] if v else None


def main():
    tab = json.load(open(os.path.join(RES, "dev_table.json")))
    main_ids = sorted(i for i, v in tab.items() if v["role"] == "main")
    ctl = sorted(i for i, v in tab.items() if v["role"] == "control")
    out = {"per_tau": {}, "gates": {}, "fixed": {}, "ref": {}}
    for tau in TAUS:
        k = repr(float(tau))
        rows = [tab[i]["probe"][k] for i in main_ids + ctl]
        stopped = [r for r in rows if not r["solved"]]
        over = [r["overshoot"] for r in stopped if r.get("overshoot") is not None]
        ovh = [r["q"] - r["probe_cpu"] for r in rows if r.get("probe_cpu") is not None]
        feats = sum(1 for r in stopped if r.get("features"))
        out["per_tau"][k] = {
            "solved_main": sum(1 for i in main_ids if tab[i]["probe"][k]["solved"]),
            "solved_controls": sum(1 for i in ctl if tab[i]["probe"][k]["solved"]),
            "overshoot_median": pct(over, 0.5), "overshoot_p95": pct(over, 0.95), "overshoot_max": max(over) if over else None,
            "wrapper_overhead_median": pct(ovh, 0.5), "wrapper_overhead_p95": pct(ovh, 0.95),
            "stopped_with_checkpoint": feats, "stopped": len(stopped),
            "killed": sum(1 for r in stopped if (r.get("terminated_by") or "").endswith("+kill"))}
    n = len(main_ids)
    for a in ACTS:
        out["fixed"][a] = sum(tab[i]["t"][a] for i in main_ids) / n
    out["fixed"]["oracle"] = sum(min(tab[i]["t"][a] for a in ACTS) for i in main_ids) / n
    for tau in TAUS:
        k = repr(float(tau))
        for a in ("Fp", "Fm"):
            tot = sum(tab[i]["probe"][k]["q"] + (0 if tab[i]["probe"][k]["solved"] else tab[i]["t"][a]) for i in main_ids)
            out["gates"][f"P({tau},{a})"] = {"mean": tot / n, "gain_vs_D": 100 * (1 - tot / n / out["fixed"]["D"])}
    diffs, rel = [], []
    paths = {}
    for i in main_ids + ctl:
        r = tab[i]["ref"]
        if not r or r["status"] != "solved":
            continue
        p = tab[i]["probe"][repr(2.0)]
        sim = p["q"] + (0 if p["solved"] else tab[i]["t"]["Fp"])
        diffs.append(r["cpu"] - sim)
        rel.append((r["cpu"] - sim) / sim)
        paths[r["path"]] = paths.get(r["path"], 0) + 1
        if bool(p["solved"]) != (r["path"] == "probe_solved"):
            out["ref"].setdefault("probe_outcome_mismatch", []).append(i)
    real = {i: tab[i]["ref"]["cpu"] for i in main_ids if tab[i]["ref"] and tab[i]["ref"]["status"] == "solved"}
    out["ref"].update(n=len(diffs), paths=paths, diff_median=pct(diffs, 0.5), diff_p05=pct(diffs, 0.05),
                      diff_p95=pct(diffs, 0.95), rel_median=pct(rel, 0.5), total_diff=sum(diffs),
                      real_mean_main=(sum(real.values()) / len(real)) if len(real) == n else None,
                      simulated_mean_main=out["gates"]["P(2,Fp)"]["mean"])
    json.dump(out, open(os.path.join(RES, "pre_solve.json"), "w"), indent=1)
    os.makedirs(REP, exist_ok=True)
    L = ["# v9 预求解测量表（由 `scripts/online_selection_v9/pre_solve.py` 生成；开发集）", "",
         f"主开发集 {n} 题、对照 {len(ctl)} 题。q = PROBE 运行的完整 wrapper 进程树 CPU（Python + probe + 读遥测）。", "",
         "| τ（s） | probe 解出（主 / 对照） | 停止超调 中位 / p95 / 最大（s） | wrapper 开销 中位 / p95（s） | 停止时有 checkpoint | SIGKILL |",
         "|---:|---|---|---|---|---:|"]
    for tau in TAUS:
        v = out["per_tau"][repr(float(tau))]
        L.append(f"| {tau} | {v['solved_main']}/{n} / {v['solved_controls']}/{len(ctl)} | "
                 f"{v['overshoot_median']:.3f} / {v['overshoot_p95']:.3f} / {v['overshoot_max']:.3f} | "
                 f"{v['wrapper_overhead_median']:.3f} / {v['wrapper_overhead_p95']:.3f} | {v['stopped_with_checkpoint']}/{v['stopped']} | {v['killed']} |")
    L += ["", "## 时间门与固定动作（开发集，成本模型；没有拟合，均为样本内）", "",
          "| 策略 | 平均 CPU（s） | 相对 D |", "|---|---:|---:|"]
    for a in ACTS:
        L.append(f"| 始终 {a} | {out['fixed'][a]:.2f} | {100 * (1 - out['fixed'][a] / out['fixed']['D']):+.1f}% |")
    L.append(f"| oracle（不可部署） | {out['fixed']['oracle']:.2f} | {100 * (1 - out['fixed']['oracle'] / out['fixed']['D']):+.1f}% |")
    for k, v in out["gates"].items():
        L.append(f"| {k} | {v['mean']:.2f} | {v['gain_vs_D']:+.1f}% |")
    r = out["ref"]
    L += ["", "## 参照“D 2 s → F+”：真实 wrapper 与成本模型", "",
          f"- 完成 {r['n']} 题；路径 {r['paths']}；probe 结果与 PROBE 测量不一致：{len(r.get('probe_outcome_mismatch', []))} 题。",
          f"- 真实 − 模拟：中位 {r['diff_median']:+.3f} s（5–95% 分位 {r['diff_p05']:+.3f} / {r['diff_p95']:+.3f} s），"
          f"相对中位 {100 * r['rel_median']:+.2f}%，总差 {r['total_diff']:+.1f} s。",
          f"- 主开发集平均：真实 {r['real_mean_main']:.2f} s，模拟 {r['simulated_mean_main']:.2f} s。" if r.get("real_mean_main") else ""]
    open(os.path.join(REP, "PRE_SOLVE_TABLES.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
