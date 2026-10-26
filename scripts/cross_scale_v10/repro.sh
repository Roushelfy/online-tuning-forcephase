#!/usr/bin/env bash
# Minimal reproduction (run inside the gs-srun container): the frozen v10 main wrapper on one confirmation instance,
# whole process-tree CPU measured with wait4 (as the runner does), the answer checked independently as the runner does
# (checkmodel for SAT, lrat-trim for UNSAT; scripts/fprun.py verify).
#   scripts/cross_scale_v10/repro.sh [instance-id]     (default v10-col3-L-53)
set -euo pipefail
cd "$(dirname "$0")/../.."
FP_DATA="${FP_DATA:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase}"
I="${1:-v10-col3-L-53}"; C="$FP_DATA/cross_scale_v10/cnf/$I.cnf"; W="$(mktemp -d /tmp/v10repro.XXXX)"
python3 - "$C" "$W" <<'PY'
import json, os, subprocess, sys
sys.path.insert(0, "scripts")
import fprun
cnf, wd = sys.argv[1], sys.argv[2]
p = subprocess.Popen([sys.executable, "scripts/cross_scale_v10/wrapper.py", "--strategy", "configs/cross_scale_v10/frozen/main.json",
                      "--cnf", cnf, "--workdir", wd])
_, status, ru = os.wait4(p.pid, 0)
d = json.load(open(os.path.join(wd, "decision.json")))
print("exit", os.waitstatus_to_exitcode(status), "tree_cpu %.2f" % (ru.ru_utime + ru.ru_stime), "path", d["path"], "action", d["action"],
      "static", d["static"]["status"], "%.4f" % d["static"]["cpu"],
      "probes", [(q["arm"], q["tau"], q["exit_code"], round(q["cpu"], 3)) for q in d["probes"]], "cpu_at_exec %.3f" % d["cpu_at_exec"])
code = os.waitstatus_to_exitcode(status)
v = fprun.verify(code, cnf, os.path.join(wd, "final.out"), os.path.join(wd, "final.lrat"), 600.0, 16000, wd)
print("answer", {10: "SAT", 20: "UNSAT"}.get(code), "verified", v["ok"], "checker", v.get("method"), "checker_cpu %.2f" % (v.get("cpu") or 0))
PY
rm -rf "$W"
