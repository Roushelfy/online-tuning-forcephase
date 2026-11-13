"""Spot check: native_linear42 raw statistics on mirrored CNFs equal the GBD base.db values used for training.
   python3 tools/check_native42_vs_gbd.py TOOLS_DIR DATA_DIR GBD_BASE_DB"""
import json, sqlite3, subprocess, sys, glob, os, random
T, D, GBD = sys.argv[1:4]
files = sorted(glob.glob(D + "/cnf_xz/*.cnf.xz")); random.Random(7).shuffle(files)
db = sqlite3.connect(f"file:{GBD}?mode=ro", uri=True)
cols = [r[1] for r in db.execute("pragma table_info(features)")]
ok = bad = fail = 0; worst = 0; cpu = []
for f in files[:40]:
    k = os.path.basename(f)[:32]
    p = subprocess.run([T + "/native_linear42", f], capture_output=True, text=True)
    if p.returncode: fail += 1; print("fail", k, p.returncode, p.stderr.strip()[:80]); continue
    out = json.loads(p.stdout); feats = out["features"]; cpu.append(out["inner_CPU_s"])
    row = dict(zip(cols, db.execute("select * from features where hash=?", (k,)).fetchone()))
    diffs = [(n, v, row[n]) for n, v in feats.items() if row.get(n) is not None and abs(float(row[n]) - v) > 1e-6 * max(1, abs(v))]
    worst = max([worst] + [abs(float(b) - a) / max(1, abs(a)) for _, a, b in diffs])
    if diffs: bad += 1; print("diff", k, diffs[:3])
    else: ok += 1
print("match", ok, "differ", bad, "extract failures", fail, "max rel diff", worst, "cpu mean", sum(cpu) / max(1, len(cpu)))
