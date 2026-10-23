#!/usr/bin/env python3
"""Score complete runtimes on one fixed panel; never impute a timeout."""
import argparse
import json
import math
from pathlib import Path

BOUND_STATUSES = {"censored", "noncompetitive_bound"}
STATUSES = BOUND_STATUSES | {"solved", "running", "error", "missing"}


def seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("cpu_seconds must be numeric")
    if not math.isfinite(value) or value < 0:
        raise ValueError("cpu_seconds must be finite and nonnegative")
    return float(value)


def completed_time(record):
    if record and record["status"] == "solved":
        if record.get("verified") is True and record.get("measurement_valid") is True:
            return seconds(record["cpu_seconds"])
    return None


def lower_bound(record):
    exact = completed_time(record)
    if exact is not None:
        return exact
    if (record and record["status"] in BOUND_STATUSES
            and record.get("measurement_valid") is True):
        return seconds(record["cpu_seconds"])
    return None


def series_summary(panel, values, details):
    complete = all(values[h] is not None for h in panel)
    total = sum(values.values()) if complete else None
    return {
        "status": "complete" if complete else "incomplete",
        "completed": sum(values[h] is not None for h in panel),
        "panel_size": len(panel),
        "total_cpu_seconds": total,
        "mean_cpu_seconds": total / len(panel) if complete else None,
        "unresolved": [details[h] for h in panel if values[h] is None],
    }


def summarize(panel, records, config):
    if not panel or len(set(panel)) != len(panel):
        raise ValueError("panel must be nonempty and contain unique instance IDs")
    if config.get("panel_size", len(panel)) != len(panel):
        raise ValueError("panel size differs from the frozen configuration")
    methods = config["methods"]
    actions = config["oracle_actions"]
    required = config["required_methods"]
    if len(set(methods)) != len(methods):
        raise ValueError("duplicate configured methods")
    if not set(actions).issubset(methods) or not actions:
        raise ValueError("oracle actions must be configured methods")
    if not set(required).issubset(methods):
        raise ValueError("required methods must be configured")
    if config["baseline"] not in methods:
        raise ValueError("baseline must be configured")
    if config.get("metric") != "mean_completed_cpu_seconds":
        raise ValueError("only mean_completed_cpu_seconds is supported")

    index = {}
    for record in records:
        key = (record["instance"], record["method"])
        if key[0] not in panel or key[1] not in methods:
            raise ValueError("run outside the fixed panel or methods: " + str(key))
        if key in index:
            raise ValueError("duplicate measurement; select attempts by protocol: " + str(key))
        if record["status"] not in STATUSES:
            raise ValueError("unknown run status")
        if record.get("cpu_seconds") is not None:
            if record.get("time_kind") != "measured_process_tree_cpu":
                raise ValueError("CPU must come from timing records, not a penalty/cost column")
            if not record.get("source_run_id"):
                raise ValueError("timed measurements require a source_run_id")
            seconds(record["cpu_seconds"])
        if record["status"] in {"solved"} | BOUND_STATUSES:
            if record.get("cpu_seconds") is None:
                raise ValueError("solved/bounded records require cpu_seconds")
        index[key] = record

    summaries = {}
    for method in methods:
        values = {h: completed_time(index.get((h, method))) for h in panel}
        details = {}
        for h in panel:
            record = index.get((h, method))
            details[h] = {
                "instance": h,
                "status": record["status"] if record else "missing",
                "reason": "not a verified, valid completed measurement",
            }
        summaries[method] = series_summary(panel, values, details)

    oracle_values, oracle_details, winners = {}, {}, {}
    for h in panel:
        exact = {a: completed_time(index.get((h, a))) for a in actions}
        solved = {a: t for a, t in exact.items() if t is not None}
        best = min(solved.values()) if solved else None
        unresolved = []
        if best is not None:
            for action in actions:
                bound = lower_bound(index.get((h, action)))
                if bound is None or bound < best:
                    unresolved.append(action)
        else:
            unresolved = list(actions)
        oracle_values[h] = best if best is not None and not unresolved else None
        oracle_details[h] = {"instance": h, "unresolved_actions": unresolved}
        if oracle_values[h] is not None:
            winners[h] = [a for a, t in solved.items() if t == best]
    oracle = series_summary(panel, oracle_values, oracle_details)
    oracle["winners"] = winners
    oracle["interpretation"] = "ideal post-hoc choice, excluding observation cost"

    baseline = summaries[config["baseline"]]["mean_cpu_seconds"]
    gains = {}
    for name, result in {**summaries, "oracle": oracle}.items():
        mean = result["mean_cpu_seconds"]
        gains[name] = (100 * (1 - mean / baseline)
                       if baseline is not None and baseline > 0 and mean is not None
                       else None)
    ready = all(summaries[m]["status"] == "complete"
                for m in set(required) | {config["baseline"]})
    if config.get("require_oracle_complete", True):
        ready = ready and oracle["status"] == "complete"
    return {
        "schema_version": 1,
        "metric": "mean_completed_cpu_seconds",
        "panel_size": len(panel),
        "primary_comparison_complete": ready,
        "methods": summaries,
        "oracle": oracle,
        "gain_percent_vs_baseline": gains,
        "note": "Incomplete means are null. No timeout penalty or solved-only mean is used.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path,
                        help="JSON list of normalized measurements, one per instance/method")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--allow-incomplete", action="store_true",
                        help="write a progress report without requiring complete primary data")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    root = Path(__file__).resolve().parents[2]
    panel = [line.split()[0] for line in (root / config["panel_file"]).read_text().splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    result = summarize(panel, json.loads(args.runs.read_text()), config)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({
        "metric": result["metric"],
        "primary_comparison_complete": result["primary_comparison_complete"],
        "out": str(args.out),
    }))
    if not result["primary_comparison_complete"] and not args.allow_incomplete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
