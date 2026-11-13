"""Task lists for tools/anni2022_week_runner.py.

  python3 tools/anni2022_make_tasks.py identity --matrix M --cnf-dir D --binary B --checker C --n 60 > tasks.jsonl
  python3 tools/anni2022_make_tasks.py probe    --matrix M --binary B --checker C --cutoff 5 --interval-ms 50 > tasks.jsonl
  python3 tools/anni2022_make_tasks.py flargest --matrix M --binary B --checker C --cutoff 600 > tasks.jsonl
"""
import argparse, csv, hashlib, json, random, sys
from pathlib import Path

MODES = {"D": ["--phase=1", "--forcephase=0"], "Fplus": ["--phase=1", "--forcephase=1"], "Fminus": ["--phase=0", "--forcephase=1"]}


def sha(p):
    h = hashlib.sha256(); h.update(Path(p).read_bytes()); return h.hexdigest()


def main():
    p = argparse.ArgumentParser(); p.add_argument("kind", choices=["identity", "probe", "flargest"])
    for x in ("--matrix", "--binary", "--checker"): p.add_argument(x, required=True)
    p.add_argument("--cnf-dir"); p.add_argument("--n", type=int, default=60); p.add_argument("--cutoff", type=float, default=600)
    p.add_argument("--interval-ms", type=int, default=50); a = p.parse_args()
    rows = list(csv.DictReader(open(a.matrix)))
    base = {"binary": a.binary, "binary_sha256": sha(a.binary), "checker": a.checker, "checker_sha256": sha(a.checker)}
    out = []
    if a.kind == "identity":
        ok = lambda r: all(r[m + "_status"] in ("SAT", "UNSAT") and 0.5 <= float(r[m + "_cpu_s"]) <= 60 for m in MODES)
        pool = [r for r in rows if ok(r) and (Path(a.cnf_dir) / f"{r['instance_key']}.cnf.xz").exists()]
        random.Random(20261116).shuffle(pool)
        for r in pool[:a.n]:
            for m, args in MODES.items():
                out.append({**base, "task": f"identity-{m}-{r['instance_key']}", "instance_key": r["instance_key"], "config": m,
                            "args": args + [f"--anniprobe={a.interval_ms}"], "cutoff_s": 600})
    elif a.kind == "probe":
        for r in rows:
            for m, args in MODES.items():
                out.append({**base, "task": f"probe-{m}-{r['instance_key']}", "instance_key": r["instance_key"], "config": "probe_" + m,
                            "args": args + [f"--anniprobe={a.interval_ms}"], "cutoff_s": a.cutoff})
    else:
        for r in rows:
            out.append({**base, "task": f"flargest-{r['instance_key']}", "instance_key": r["instance_key"], "config": "Flargest",
                        "args": ["--phase=1", "--forcephase=0", "--flargest=1"], "cutoff_s": a.cutoff})
    for t in out: print(json.dumps(t))
    print(len(out), "tasks", file=sys.stderr)


if __name__ == "__main__":
    main()
