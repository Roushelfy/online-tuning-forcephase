"""Short-probe features and replay of 'probe, then choose a mode' policies (shared by the analysis scripts).

Protocol (defaults agreed for the week of 2026-11-16):
  * probes run the full original formula independently in the fixed order D -> F+ -> F-, w CPU seconds each
    (w in {0.5, 2, 5}); a probe that solves (verified) ends the instance with cost = CPU of all probes run so far;
  * otherwise a mode is chosen from the early statistics and the formal run either
      - continues the chosen probe (its w seconds are reused; implemented by SIGSTOP/SIGCONT, no solver change):
        cost = w * (number of other probes) + T600 time of the chosen mode, or
      - restarts the chosen mode from scratch: cost = 3w + T600 time of the chosen mode;
  * every method gets 600 CPU s in total including probes; solved iff cost <= 600, PAR2 = cost or 1200;
  * CaDiCaL is deterministic, so the chosen mode's full-run time is taken from the T600 baseline (replay).
"""
import json
from pathlib import Path

import numpy as np

MODES = ("D", "Fplus", "Fminus")
WINDOWS = (0.5, 2.0, 5.0)
BUDGET = 600.0
# telemetry fields kept as features (per mode), plus derived means and rates
FIELDS = ("conflicts", "decisions", "propagations", "restarts", "reductions", "rephased", "chrono", "stable",
          "stabphases", "fixed", "learned_lits", "learned_cls", "irredundant", "redundant", "active", "level_ema",
          "jump_ema", "trail_fast", "trail_slow", "glue_fast", "glue_slow", "size_ema", "decision_rate_ema")


def state_at(telemetry, w):
    """Last telemetry line with t <= w (None if the solver had produced none yet)."""
    best = None
    for row in telemetry:
        if row["t"] <= w + 1e-9 and (best is None or row["t"] >= best["t"]):
            best = row
    return best


def derived(row, w):
    if row is None: return None
    t = max(row["t"], 1e-3); s = max(row["samples"], 1)
    out = {k: float(row[k]) for k in FIELDS}
    out.update({"t": row["t"], "conflict_level_mean": row["sum_conflict_level"] / s,
                "backtrack_level_mean": row["sum_backtrack_level"] / s, "jump_mean": row["sum_jump"] / s,
                "conflicts_per_s": row["conflicts"] / t, "decisions_per_s": row["decisions"] / t,
                "propagations_per_s": row["propagations"] / t, "decisions_per_conflict": row["decisions"] / max(row["conflicts"], 1),
                "propagations_per_decision": row["propagations"] / max(row["decisions"], 1),
                "fixed_per_s": row["fixed"] / t, "learned_lits_per_cls": row["learned_lits"] / max(row["learned_cls"], 1)})
    return out


def load_probes(root, keys):
    """probe[k][mode] = {'solved', 'cpu_s', 'answer', 'telemetry'} from RUN_ROOT/results/probe-<mode>-<k>.json."""
    probes = {}
    for k in keys:
        probes[k] = {}
        for m in MODES:
            p = Path(root) / "results" / f"probe-{m}-{k}.json"
            if not p.exists(): continue
            r = json.loads(p.read_text())
            probes[k][m] = {"solved": r["solved"], "cpu_s": r["cpu_s"], "status": r["status"], "answer": r["answer"],
                            "telemetry": r["telemetry"]}
    return probes


def probe_phase(probe_k, w):
    """Sequential probes D -> F+ -> F- of w s each. Returns (solved_in_probe, cost_so_far, solving_mode)."""
    cost = 0.0
    for m in MODES:
        p = probe_k[m]
        if p["solved"] and p["cpu_s"] <= w:
            return True, cost + p["cpu_s"], m
        cost += w
    return False, cost, None


def compose(costs_time, solved, w, choice, semantics="continue"):
    """Total cost (PAR2) for one instance given the T600 time/solved of the chosen mode after unsolved probes."""
    t, ok = costs_time[choice], solved[choice]
    probe_paid = (len(MODES) - 1) * w if semantics == "continue" else len(MODES) * w
    total = probe_paid + t
    return total if ok and total <= BUDGET else 2 * BUDGET


def features(probe_k, w):
    """Per-mode derived state at w (dict mode -> dict or None)."""
    return {m: derived(state_at(probe_k[m]["telemetry"], w), w) for m in MODES}
