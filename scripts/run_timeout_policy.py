"""Per-run CPU timeout (configs/run_timeout_policy.json; docs/RESOURCE_POLICY.md, docs/RUN_TIMEOUT_APPLICATION.md).

Aggregate compute stays unlimited (scripts/resource_policy.py); every ordinary job -- a fixed arm or an online
strategy's whole process tree (observation, selection, restart and final solve combined) -- gets
cap_cpu = per_instance_method_cpu_seconds with cap_kind 'policy_timeout'. A shorter explicit oracle bound
(oracle_noncompetitive_bound) keeps its value. Jobs carry run_policy_id so their run ids differ from records
made under earlier policies (no skipping, no overwriting).

FP_RUN_TIMEOUT_POLICY may point to another policy file (tests only).
"""
import copy
import json
import math
import os
from pathlib import Path


def load(root):
    path = os.environ.get("FP_RUN_TIMEOUT_POLICY") or str(Path(root) / "configs" / "run_timeout_policy.json")
    pol = json.loads(Path(path).read_text())
    lim = pol.get("per_instance_method_cpu_seconds")
    if isinstance(lim, bool) or not isinstance(lim, (int, float)) or not math.isfinite(lim) or lim <= 0:
        raise ValueError("per_instance_method_cpu_seconds must be a positive finite number")
    if pol.get("project_cpu_hours_cap") is not None or pol.get("stage_cpu_hours_cap") is not None:
        raise ValueError("aggregate CPU must stay unlimited")
    return pol


def apply(plan, pol):
    """Return a copy of an (already resource-policy prepared) plan with the per-run timeout applied."""
    lim = float(pol["per_instance_method_cpu_seconds"])
    eff = copy.deepcopy(plan)
    eff["run_policy_id"] = pol["policy_id"]
    eff["per_run_cpu_seconds"] = lim
    for job in eff["jobs"]:
        job["run_policy_id"] = pol["policy_id"]
        cap = job.get("cap_cpu")
        if job.get("cap_kind") == "oracle_noncompetitive_bound" and isinstance(cap, (int, float)) and 0 < cap < lim:
            continue
        if job.get("cap_kind") not in (None, "policy_timeout") and cap is not None and cap > lim:
            job["historical_cap_cpu_ignored"] = cap
        job["cap_cpu"] = lim
        job["cap_kind"] = "policy_timeout"
    return eff


ENV_LIMIT = "FP_RUN_CPU_LIMIT"  # set by the controllers for wrapper jobs: the job's per-run cap (process tree)


def set_cpu_rlimit(limit, include_waited_children=True):
    """Make the kernel enforce `limit` CPU s for this process and what it execs (RLIMIT_CPU; SIGXCPU at the soft
    limit, SIGKILL 60 s later). RLIMIT_CPU counts the process's own CPU, which persists across exec; CPU of
    children already waited for (a wrapper's probe) is subtracted so that the whole tree stops at `limit`."""
    import resource
    used = 0.0
    if include_waited_children:
        c = resource.getrusage(resource.RUSAGE_CHILDREN)
        used = c.ru_utime + c.ru_stime
    soft = max(1, int(math.ceil(limit - used)))
    resource.setrlimit(resource.RLIMIT_CPU, (soft, soft + 60))
    return soft


def wrapper_limit():
    """Per-run cap handed to a wrapper by its controller (None outside policy-timeout jobs)."""
    v = os.environ.get(ENV_LIMIT)
    return float(v) if v else None


def is_timeout(job_cpu, spec):
    """A run that ended without a verified answer at/after its policy cap (controller stop or SIGXCPU)."""
    return spec.get("cap_kind") == "policy_timeout" and spec.get("cap_cpu") is not None and job_cpu >= spec["cap_cpu"] - 0.5


def classify_after_cap(answered, cpu, spec, verified_status):
    """Status of a run under the timeout: an answer counts only if it came within the limit."""
    if spec.get("cap_kind") == "policy_timeout" and cpu > spec["cap_cpu"]:
        return "policy_timeout"
    return verified_status
