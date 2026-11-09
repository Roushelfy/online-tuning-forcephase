"""Tables for a collected Anniversary 2022 snapshot (standard library only).

  python3 tools/anni2022_report.py --snapshot SNAPSHOT_DIR      -> SNAPSHOT_DIR/report.json and printed Markdown
"""
import argparse
import itertools
import json
import statistics
from pathlib import Path

ACTIONS = ["D", "Fplus", "Fminus"]
THRESHOLDS = [1, 10, 60, 300, 600]


def main():
    p = argparse.ArgumentParser(); p.add_argument("--snapshot", required=True); a = p.parse_args()
    snap = Path(a.snapshot)
    summary = json.loads((snap / "summary.json").read_text())
    cases = [c for c in json.loads((snap / "instances.json").read_text()) if set(c["outcomes"]) == set(ACTIONS)]
    T = summary["cutoff_s"]
    solved = lambda c, x: c["outcomes"][x]["resolved"]
    cpu = lambda c, x: c["outcomes"][x]["cpu_s"]
    rep = {"full_cohort": summary["full_cohort"], "complete_parents": len(cases), "status": summary["status"],
           "recorded_runs": summary["recorded_runs"], "valid_runs": summary["valid_runs"], "cutoff_s": T, "actions": {}}
    answer = {}
    for c in cases:
        ans = {c["outcomes"][x]["answer_reported"] for x in ACTIONS if solved(c, x)}
        answer[c["instance_key"]] = ans.pop() if ans else None
    for x in ACTIONS:
        s = [c for c in cases if solved(c, x)]
        rep["actions"][x] = {
            "solved": len(s), "sat": sum(answer[c["instance_key"]] == "SAT" for c in s),
            "unsat": sum(answer[c["instance_key"]] == "UNSAT" for c in s),
            "timeouts": sum(c["outcomes"][x]["status"] == "CPU_TIMEOUT" for c in cases),
            "unknown": sum(c["outcomes"][x]["status"] == "UNKNOWN" for c in cases),
            "mean_par2_s": statistics.mean(c["outcomes"][x]["par2"] for c in cases),
            "solved_cpu_s_total": sum(cpu(c, x) for c in s),
            "solved_within": {t: sum(cpu(c, x) <= t for c in s) for t in THRESHOLDS},
            "unique_solves": sum(solved(c, x) and not any(solved(c, y) for y in ACTIONS if y != x) for c in cases)}
    vbs = [min((cpu(c, x) for x in ACTIONS if solved(c, x)), default=None) for c in cases]
    rep["vbs_time"] = {"solved": sum(v is not None for v in vbs),
                       "sat": sum(answer[c["instance_key"]] == "SAT" for c in cases),
                       "unsat": sum(answer[c["instance_key"]] == "UNSAT" for c in cases),
                       "mean_par2_s": statistics.mean(v if v is not None else 2 * T for v in vbs),
                       "solved_within": {t: sum(v is not None and v <= t for v in vbs) for t in THRESHOLDS}}
    rep["all_three_solved"] = sum(all(solved(c, x) for x in ACTIONS) for c in cases)
    rep["none_solved"] = sum(not any(solved(c, x) for x in ACTIONS) for c in cases)
    best_single = min(ACTIONS, key=lambda x: (-rep["actions"][x]["solved"], rep["actions"][x]["mean_par2_s"]))
    rep["best_single_by_solved"] = best_single
    # Fastest action per instance among those solved by at least one action (ties within 1% or 0.1 s counted as ties).
    winners = {x: 0 for x in ACTIONS}; ties = 0
    for c in cases:
        s = {x: cpu(c, x) for x in ACTIONS if solved(c, x)}
        if not s: continue
        m = min(s.values()); best = [x for x, v in s.items() if v <= max(m * 1.01, m + 0.1)]
        if len(best) > 1: ties += 1
        else: winners[best[0]] += 1
    rep["fastest_counts"] = {**winners, "ties": ties}
    pairs = {}
    for x, y in itertools.combinations(ACTIONS, 2):
        both = [c for c in cases if solved(c, x) and solved(c, y)]
        pairs[f"{x}_vs_{y}"] = {"both_solved": len(both), "only_" + x: sum(solved(c, x) and not solved(c, y) for c in cases),
                                "only_" + y: sum(solved(c, y) and not solved(c, x) for c in cases),
                                x + "_2x_faster": sum(cpu(c, x) * 2 <= cpu(c, y) and cpu(c, y) >= 1 for c in both),
                                y + "_2x_faster": sum(cpu(c, y) * 2 <= cpu(c, x) and cpu(c, x) >= 1 for c in both)}
    rep["pairs"] = pairs
    (snap / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
    n = len(cases)
    print(f"Complete parents {n}/{rep['full_cohort']}; valid runs {rep['valid_runs']}/{rep['recorded_runs']}; status {rep['status']}\n")
    print("| | solved | SAT | UNSAT | timeouts | ≤10 s | ≤60 s | ≤300 s | unique | mean PAR2 (s) |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for x in ACTIONS:
        r = rep["actions"][x]
        print(f"| {x} | {r['solved']} | {r['sat']} | {r['unsat']} | {r['timeouts']} | {r['solved_within'][10]} | {r['solved_within'][60]} | "
              f"{r['solved_within'][300]} | {r['unique_solves']} | {r['mean_par2_s']:.1f} |")
    v = rep["vbs_time"]
    print(f"| VBS | {v['solved']} | {v['sat']} | {v['unsat']} | {n - v['solved']} | {v['solved_within'][10]} | {v['solved_within'][60]} | "
          f"{v['solved_within'][300]} | | {v['mean_par2_s']:.1f} |")
    print(f"\nall three solved {rep['all_three_solved']}, none solved {rep['none_solved']}, fastest {rep['fastest_counts']}")
    for k, v in pairs.items(): print(k, v)


if __name__ == "__main__":
    main()
