"""Current user resource policy; old experiment budgets are historical only."""
import copy
import json
import math
from pathlib import Path


def load_policy(root):
    path = Path(root) / "configs" / "resource_policy.json"
    policy = json.loads(path.read_text())
    if policy.get("mode") != "unlimited_cpu_hours":
        raise ValueError("current user instruction requires unlimited_cpu_hours policy")
    for field in ("project_cpu_hours_cap", "stage_cpu_hours_cap",
                  "completion_cpu_seconds_cap"):
        if policy.get(field) is not None:
            raise ValueError("withdrawn CPU limit must be null: " + field)
    return policy


def prepare_plan(plan, policy):
    """Return a copy with ordinary legacy run caps disabled.

    Oracle certificates and bounded observation windows must be explicitly
    typed. Ordinary pilot/formal completion caps disappear.
    """
    effective = copy.deepcopy(plan)
    effective["resource_policy_id"] = policy["policy_id"]
    effective["budget_cpu_hours"] = None
    for job in effective["jobs"]:
        job["resource_policy_id"] = policy["policy_id"]
        cap = job.get("cap_cpu")
        if job.get("cap_kind") in {"oracle_noncompetitive_bound", "observation_window"}:
            if (isinstance(cap, bool) or not isinstance(cap, (int, float))
                    or not math.isfinite(cap) or cap <= 0):
                raise ValueError("algorithmic bound/window must be positive and finite")
        else:
            if cap is not None:
                job["historical_cap_cpu_ignored"] = cap
            job["cap_cpu"] = None
    return effective
