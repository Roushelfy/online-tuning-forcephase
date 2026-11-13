"""Re-download the 4719 cohort CNFs (GBD .xz as served) and check each against the baseline staging receipt
(compressed SHA-256 recorded when the T600 baseline staged it). Resumable; a few parallel connections.

  python3 tools/anni2022_fetch_cnf.py --run-root RUN_ROOT --out CNF_DIR [--workers 6]
Writes CNF_DIR/<hash>.cnf.xz and CNF_DIR/fetch_log.jsonl.
"""
import argparse
import glob
import hashlib
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def fetch(rec, out):
    k = rec["instance_key"]; dst = out / f"{k}.cnf.xz"
    if dst.exists() and sha(dst) == rec["compressed_sha256"]:
        return {"k": k, "status": "present", "bytes": dst.stat().st_size}
    tmp = dst.with_suffix(".part"); err = None
    for attempt in range(4):
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(rec["url"], timeout=60) as src, tmp.open("wb") as f:
                for b in iter(lambda: src.read(1 << 20), b""): f.write(b)
            if sha(tmp) != rec["compressed_sha256"]:
                raise ValueError("compressed SHA differs from baseline receipt")
            tmp.replace(dst)
            return {"k": k, "status": "ok", "bytes": dst.stat().st_size, "attempt": attempt + 1, "wall_s": time.monotonic() - t0}
        except Exception as e:
            err = repr(e); time.sleep(5 * (attempt + 1))
    tmp.unlink(missing_ok=True)
    return {"k": k, "status": "failed", "error": err}


def main():
    p = argparse.ArgumentParser(); p.add_argument("--run-root", required=True); p.add_argument("--out", required=True)
    p.add_argument("--workers", type=int, default=6); a = p.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    recs = [json.load(open(p)) for p in sorted(glob.glob(os.path.join(a.run_root, "shard-*/input_receipts/*.json")))]
    assert len(recs) == 4719 and len({r["instance_key"] for r in recs}) == 4719, len(recs)
    done = {"ok": 0, "present": 0, "failed": 0}; total = 0
    with ThreadPoolExecutor(a.workers) as ex, (out / "fetch_log.jsonl").open("a") as log:
        for i, r in enumerate(ex.map(lambda rec: fetch(rec, out), recs)):
            done[r["status"]] += 1; total += r.get("bytes", 0)
            log.write(json.dumps(r) + "\n"); log.flush()
            if i % 200 == 0: print(i, done, f"{total / 2**30:.1f} GiB", flush=True)
    print("final", done, f"{total / 2**30:.1f} GiB")
    raise SystemExit(0 if done["failed"] == 0 else 2)


if __name__ == "__main__":
    main()
