"""Variable-permuted, clause- and literal-shuffled copies (signs kept; cnfscramble mode 'perm', seed 1) of the
robustness sample, as plain CNFs with SHA-256 manifest.
  python3 tools/anni2022_make_perm.py --sample S.json --cnf-dir CNF_XZ --scramble BIN --out DIR [--workers 8]
"""
import argparse, hashlib, json, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
p = argparse.ArgumentParser(); [p.add_argument(x, required=True) for x in ("--sample", "--cnf-dir", "--scramble", "--out")]
p.add_argument("--workers", type=int, default=8); p.add_argument("--mode", default="perm"); a = p.parse_args()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
keys = [r["instance_key"] for r in json.load(open(a.sample))["instances"]]
def one(k):
    dst = out / f"{k}.{a.mode}1.cnf"
    subprocess.run([a.scramble, str(Path(a.cnf_dir) / f"{k}.cnf.xz"), str(dst), a.mode, "1"], check=True, capture_output=True)
    h = hashlib.sha256()
    with dst.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return k, {"path": str(dst), "sha256": h.hexdigest(), "mode": a.mode, "seed": 1}
with ThreadPoolExecutor(a.workers) as ex: man = dict(ex.map(one, keys))
json.dump(man, open(out / "manifest.json", "w"), indent=1); print(len(man), "permuted copies")
