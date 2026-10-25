#!/usr/bin/env python3
"""3600 CPU-second view of historical records (docs/RUN_TIMEOUT_APPLICATION.md section 4).

  timeout_view.py -> results/online_selection_v9/timeout_3600_view.json, reports/online_selection_v9/TIMEOUT_3600_TABLES.md

Per instance x method: 'solved' if a verified completion used <= 3600 s of process-tree CPU (for D taken from a
P1_M05_long run: its formal-solve CPU); 'timeout' if no such completion exists and some actual run reached
>= 3600 s (finished later, stopped, censored, or answered without verification); 'not_reconstructable' if the
only evidence is a bound below 3600 s (e.g. the v6 300 s stops, oracle bounds below 3600 s). Panels: the v7
55-instance panel, and the v9 held-out (post-hoc sensitivity: the frozen v9 comparison is unchanged),
extrapolation and external panels.
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
RES = os.path.join(ROOT, "results", "online_selection_v9")
REP = os.path.join(ROOT, "reports", "online_selection_v9")
LIMIT = json.load(open(os.path.join(ROOT, "configs", "run_timeout_policy.json")))["per_instance_method_cpu_seconds"]
STOPS = {s["id"] for s in json.load(open(os.path.join(ROOT, "results", "policy_stops.json")))["stops"]}
CORR = {c["id"]: c["status"] for c in json.load(open(os.path.join(ROOT, "results", "verification_corrections.json")))["corrections"]}


def ok(r):
    return r["id"] not in CORR and r["status"] == "solved" and (r.get("verification") or {}).get("ok") is True


def classify(evid):
    """evid: list of (cpu, solved_bool, answer). -> (status, solve time or None, answer)."""
    solved = sorted(c for c, s, _ in evid if s and c <= LIMIT)
    ans = next((a for c, s, a in evid if s and a), None) or next((a for c, s, a in evid if a), None)
    if solved:
        return "solved", solved[0], ans
    if any(c >= LIMIT for c, _, _ in evid):
        return "timeout", None, ans
    return "not_reconstructable", None, ans


def old55():
    P = [l.split()[0] for l in open(os.path.join(ROOT, "configs", "completion_v7", "panel.txt")) if l.strip() and not l.startswith("#")]
    ev = {(h, m): [] for h in P for m in ("D", "Fp", "Fm", "P1_M05_long")}
    for r in json.load(open(os.path.join(ROOT, "results", "completion_v7", "reuse_records.json"))):
        if (r["instance"], r["method"]) in ev and r.get("measurement_valid"):
            ev[(r["instance"], r["method"])].append((r["cpu_seconds"], r["status"] == "solved" and r.get("verified"),
                                                     {"SAT": "SAT", "UNSAT": "UNSAT"}.get(str(r.get("result", "")).upper())))
    for st in ("stage1", "stage2", "old55_r1a", "old55_r1b"):
        for p in glob.glob(os.path.join(DATA, "runs", "completion_v7", st, "*.json")):
            if p.endswith(("progress.json", "effective_plan.json")):
                continue
            r = json.load(open(p))
            if r["instance"] not in P:
                continue
            ans = {10: "SAT", 20: "UNSAT"}.get(r.get("exit_code"))
            good = ok(r)
            if r["status"] == "noncompetitive_bound" or r["status"] in ("censored", "error", "unverified", "wrong") or good:
                ev[(r["instance"], r["method"])].append((r["cpu"], good, ans if good else None))
            if r["method"] == "P1_M05_long" and r.get("formal_cpu") is not None and r.get("action") == "D":
                ev[(r["instance"], "D")].append((r["formal_cpu"], good, ans if good else None))
    return P, ev


def v9(stages, panel_file, wrappers):
    ids = [l.split()[0] for l in open(os.path.join(ROOT, "configs", "online_selection_v9", panel_file)) if l.strip() and not l.startswith("#")]
    methods = ("D", "Fp", "Fm") + tuple(sorted(set(wrappers.values())))
    ev = {(i, m): [] for i in ids for m in methods}
    for st in stages:
        for p in glob.glob(os.path.join(DATA, "runs", "online_selection_v9", st, "*.json")):
            if p.endswith(("progress.json", "effective_plan.json")):
                continue
            r = json.load(open(p))
            m = r["method"] if r["method"] != "W" else wrappers.get(r.get("strategy"))
            if (r["instance"], m) not in ev or r.get("seed", 0):
                continue
            good = ok(r)
            ev[(r["instance"], m)].append((r["cpu"], good, {10: "SAT", 20: "UNSAT"}.get(r.get("exit_code")) if good else None))
    return ids, ev


def summarize(name, ids, ev, methods):
    st = {k: classify(v) for k, v in ev.items()}
    ans = {i: next((st[(i, m)][2] for m in methods if st[(i, m)][2]), None) for i in ids}
    out = {"panel": name, "n": len(ids), "limit": LIMIT, "methods": {}}
    for m in methods:
        rows = [st[(i, m)] for i in ids]
        out["methods"][m] = {
            "solved": sum(1 for r in rows if r[0] == "solved"),
            "timeout": sum(1 for r in rows if r[0] == "timeout"),
            "not_reconstructable": sum(1 for r in rows if r[0] == "not_reconstructable"),
            "solved_by_answer": {a: sum(1 for i in ids if st[(i, m)][0] == "solved" and ans[i] == a) for a in ("SAT", "UNSAT")},
            "solve_times": sorted(r[1] for r in rows if r[0] == "solved"),
            "timeouts": [i for i in ids if st[(i, m)][0] == "timeout"],
            "not_reconstructable_ids": [i for i in ids if st[(i, m)][0] == "not_reconstructable"]}
    fixed = [m for m in methods if m in ("D", "Fp", "Fm")]
    out["oracle_any_solved"] = sum(1 for i in ids if any(st[(i, m)][0] == "solved" for m in fixed))
    common = [i for i in ids if all(st[(i, m)][0] == "solved" for m in methods)]
    out["common_solved"] = {"n": len(common), "means": {m: (sum(st[(i, m)][1] for i in common) / len(common) if common else None)
                                                         for m in methods},
                            "note": "secondary only: instances solved within the limit by every method (selection bias)"}
    out["answers"] = {a: sum(1 for i in ids if ans[i] == a) for a in ("SAT", "UNSAT", None)}
    return out


def main():
    ref = "configs/online_selection_v9/strategies/ref_D2_Fp.json"
    res = {}
    P, ev = old55()
    res["old55"] = summarize("v7 55-instance panel", P, ev, ("D", "Fp", "Fm", "P1_M05_long"))
    for name, stages, pf in (("holdout", ["holdout"], "panel_holdout.txt"), ("extrapolation", ["extrap"], "panel_extrapolation.txt"),
                             ("external", ["external_r2"], "panel_external.txt")):
        ids, ev = v9(stages, pf, {ref: "W_ref"})
        res[name] = summarize(name, ids, ev, ("D", "Fp", "Fm", "W_ref"))
    json.dump(res, open(os.path.join(RES, "timeout_3600_view.json"), "w"), indent=1)
    L = ["# 3600 CPU 秒视图（由 `scripts/online_selection_v9/timeout_view.py` 生成）", "",
         "按 [RUN_TIMEOUT_APPLICATION.md](../../docs/RUN_TIMEOUT_APPLICATION.md) 第 4 节：已解 = 经验证的完成且进程树 CPU ≤ 3600 s；"
         "超时 = 没有这样的完成，且有实际运行到 ≥ 3600 s；不可重建 = 只有低于 3600 s 的下界。不用 3600 s 代替完成时间，不算 PAR2。", ""]
    for name, r in res.items():
        L += [f"## {r['panel']}（{r['n']} 题；答案已知：SAT {r['answers']['SAT']}，UNSAT {r['answers']['UNSAT']}，未知 {r['answers'][None]}）", "",
              "| 方法 | 3600 s 内已解 | 其中 SAT / UNSAT | 超时 | 不可重建 |", "|---|---:|---|---:|---:|"]
        for m, v in r["methods"].items():
            L.append(f"| {m} | {v['solved']}/{r['n']} | {v['solved_by_answer']['SAT']} / {v['solved_by_answer']['UNSAT']} | {v['timeout']} | {v['not_reconstructable']} |")
        c = r["common_solved"]
        L += ["", f"- 至少一个固定动作在 3600 s 内解出：{r['oracle_any_solved']}/{r['n']}。",
              f"- 次要描述（各方法都在 3600 s 内解出的 {c['n']} 题，存在筛选偏差）：平均 CPU " +
              "，".join(f"{m} {v:.1f} s" for m, v in c["means"].items() if v is not None) + "。"]
        tos = {m: v["timeouts"] for m, v in r["methods"].items() if v["timeouts"]}
        if tos:
            L.append("- 超时清单：" + "；".join(f"{m}: {', '.join(i if i.startswith('v9') else i[:12] for i in v)}" for m, v in tos.items()) + "。")
        L.append("")
    open(os.path.join(REP, "TIMEOUT_3600_TABLES.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
