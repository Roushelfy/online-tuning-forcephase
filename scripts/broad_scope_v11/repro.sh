#!/usr/bin/env bash
# Minimal reproduction of v11 (run inside the gs-srun container):
#   1. regenerate one formal instance from its manifest row and compare the SHA-256 (generator venv);
#   2. run the frozen main strategy (fixed D) and the frozen structural control wrapper on it, whole process-tree CPU
#      measured with wait4 as the runner does, answers checked independently (checkmodel / lrat-trim via fprun.verify);
#   3. decode a SAT model and check it against the problem itself (semantic.py).
#   scripts/broad_scope_v11/repro.sh [instance-id]     (default v11-jssp-S-s3000)
set -euo pipefail
cd "$(dirname "$0")/../.."
export FP_DATA="${FP_DATA:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase}"
GENPY=/mnt/data/zhaofeng/venvs/online-tuning-forcephase-v8gen/bin/python
I="${1:-v11-jssp-S-s3000}"; W="$(mktemp -d /tmp/v11repro.XXXX)"
$GENPY - "$I" "$W" <<'PY'
import hashlib, json, os, subprocess, sys
sys.path.insert(0, "scripts"); sys.path.insert(0, "scripts/broad_scope_v11")
import fprun, gen, semantic
import generate as G
iid, wd = sys.argv[1], sys.argv[2]
row = next(r for r in json.load(open("results/broad_scope_v11/formal_manifest.json"))["instances"] if r["id"] == iid)
src = {k: row[k] for k in ("id", "family", "size", "seed") if k in row}
if row.get("params"):
    src["params"] = row["params"]
_, (nv, cl), _, sem = gen.build(src, row["enc"])
text = G.dimacs(nv, cl)
cnf = os.path.join(wd, iid + ".cnf")
open(cnf, "w").write(text)
print("regenerated", iid, "sha256 match", hashlib.sha256(text.encode()).hexdigest() == row["sha256"], "vars", nv, "clauses", len(cl))
fz = json.load(open("configs/broad_scope_v11/frozen/FREEZE.json"))
main = json.load(open(fz["files"]["main"]["path"]))
print("frozen main:", main["kind"], main.get("action"), "| structural:", fz["files"]["structural"]["path"])
args = {"D": ["--phase=1", "--forcephase=0"], "Fp": ["--phase=1", "--forcephase=1"], "Fm": ["--phase=0", "--forcephase=1"]}
runs = [("main (fixed %s)" % main["action"], ["build/fpc/cadical", "--lrat=1"] + args[main["action"]] + ["--fpc=1", cnf,
                                                                                                         os.path.join(wd, "m.lrat")], "m"),
        ("structural wrapper", [sys.executable, "scripts/broad_scope_v11/wrapper.py", "--strategy",
                                fz["files"]["structural"]["path"], "--cnf", cnf, "--workdir", os.path.join(wd, "w")], "w")]
os.makedirs(os.path.join(wd, "w"))
for name, cmd, tag in runs:
    out = os.path.join(wd, "m.out") if tag == "m" else os.path.join(wd, "w", "final.out")
    proof = os.path.join(wd, "m.lrat") if tag == "m" else os.path.join(wd, "w", "final.lrat")
    with open(os.path.join(wd, tag + ".stdout"), "wb") as so:
        p = subprocess.Popen(cmd, stdout=so if tag == "m" else subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _, status, ru = os.wait4(p.pid, 0)
    if tag == "m":
        os.replace(os.path.join(wd, "m.stdout"), out)
    code = os.waitstatus_to_exitcode(status)
    v = fprun.verify(code, cnf, out, proof, 600.0, 16000, wd)
    extra = ""
    if tag == "w":
        d = json.load(open(os.path.join(wd, "w", "decision.json")))
        extra = "path %s action %s static %s %.3f s" % (d["path"], d["action"], d["static"]["status"], d["static"]["cpu"])
    sem_ok = None
    if code == 10:
        lits = [int(t) for line in open(out) if line.startswith("v ") for t in line[2:].split() if t != "0"]
        fam = "col3log" if row["family"] == "col3" and row["enc"] == "log" else row["family"]
        if fam in semantic.CHECK:
            sem_ok = semantic.check(fam, sem, semantic.model_set(lits))
    print(name, "exit", code, "answer", {10: "SAT", 20: "UNSAT"}.get(code), "tree_cpu %.2f" % (ru.ru_utime + ru.ru_stime),
          "verified", v["ok"], v.get("method"), "semantic", sem_ok, extra)
PY
rm -rf "$W"
