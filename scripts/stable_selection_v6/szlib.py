"""SATzilla 2024 feature extractor wrapper for goal v6 (protocol section 3.2).

The extractor is the official tool (https://github.com/hadarshavit/satzilla,
commit 6209d485108381ecb403c5af8aa7134645bae7fb), built from source in the
gs-srun container; its location is $FP_DATA/v6_tools/satzilla/src/features
(not vendored: the repository has no licence file). Groups 'ls' and 'cl'
(which spawn bundled prebuilt solvers) are never used, and the external
preprocessor is skipped with --preprocess-timeout 0. Standard library only.
"""

import csv
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts", "three_way"))
import twlib  # noqa: E402

DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
SZ_BIN = os.path.join(DATA, "v6_tools", "satzilla", "src", "features")
CANDIDATE_GROUPS = ["base", "structure", "ncnf-graphs", "ncnf-constraints", "ncnf-rwh", "unit", "dia", "sp", "lp", "lobjois"]


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    # the tool writes reserved negative codes (e.g. -512) for features it did not compute
    return None if not math.isfinite(v) or v in (-512.0, -1024.0) else v


def run_satzilla(cnf, groups, cap, workdir, mem_mb=16000):
    """Run the extractor for `groups` under a CPU hard cap (seconds).
    Returns {status: ok|cap|error, cpu, exit_code, features: {sz_<name>: value}}."""
    os.makedirs(workdir, exist_ok=True)
    out = os.path.join(workdir, "sz.csv")
    if os.path.exists(out):
        os.unlink(out)
    t = max(1, int(math.ceil(cap)))
    cmd = [SZ_BIN, "--timeout", str(t), "--group-timeout", str(t), "--preprocess-timeout", "0"] + \
        [f"-{g}" for g in groups] + [cnf, out]
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "TMPDIR": workdir}
    so, se = os.path.join(workdir, "sz.out"), os.path.join(workdir, "sz.err")
    r = twlib.run_budget(cmd, env, cap, mem_mb, so, se)
    rec = {"cpu": r["cpu"], "exit_code": r["exit_code"], "terminated_by": r["terminated_by"], "groups": list(groups)}
    feats = {}
    if r["terminated_by"]:
        rec["status"] = "cap"
    elif r["exit_code"] != 0 or not os.path.exists(out):
        rec["status"] = "error"
        rec["error"] = open(se, "rb").read()[-400:].decode("utf-8", "replace")
    else:
        try:
            rows = list(csv.reader(open(out)))
            names, vals = rows[0], rows[1]
            feats = {f"sz_{n.strip()}": _num(v) for n, v in zip(names, vals)}
            rec["status"] = "ok"
            rec["n_reserved"] = sum(v is None for v in feats.values())
        except (IndexError, OSError, ValueError) as e:
            rec["status"] = "error"
            rec["error"] = repr(e)
    rec["features"] = feats
    return rec
