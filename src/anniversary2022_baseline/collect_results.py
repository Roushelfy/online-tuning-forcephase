import argparse
import csv
import gzip
import json
import statistics
from pathlib import Path
from .common import ACTIONS, fingerprint, load_manifest, read, sha, shard_rows, write
from .run_baselines import connect


def collect(root, out):
    return collect_roots([root], out)


def collect_roots(roots, out):
    """One snapshot from one run root, or from all shard roots of a cluster run (2026-11-08). Shards must share the
    frozen spec (apart from shard and the node-local proof_dir and cache_dir) and measurement identity, and partition the cohort."""
    roots, out = [Path(r).resolve() for r in roots], Path(out)
    if out.exists(): raise ValueError("snapshot is immutable; choose a new output")
    specs = [read(r/"metadata/spec.json") for r in roots]; identities = [read(r/"metadata/identity.json") for r in roots]
    common = lambda s: {k: v for k, v in s.items() if k not in ("shard", "proof_dir", "cache_dir")}
    if any(common(s) != common(specs[0]) or i != identities[0] for s, i in zip(specs, identities)):
        raise ValueError("shards differ in frozen spec or measurement identity")
    spec, identity = specs[0], identities[0]
    for r in roots:
        if sha(r/"metadata/manifest.csv") != spec["manifest_sha256"]: raise ValueError("changed frozen cohort")
    rows = load_manifest(roots[0]/"metadata/manifest.csv"); cases = {r["instance_key"]: {"instance_key": r["instance_key"], "outcomes": {}} for r in rows}
    sharded = len(roots) > 1 or "shard" in spec
    if sharded:
        if any("shard" not in s for s in specs): raise ValueError("unsharded root mixed with shards")
        count = specs[0]["shard"]["count"]
        if sorted((s["shard"]["index"], s["shard"]["count"]) for s in specs) != [(i, count) for i in range(count)]:
            raise ValueError("shard roots do not form a complete partition")
    expected = {(r["instance_key"], a, 0) for r in rows for a in ACTIONS}
    jobs = []; records = []; evidence = []
    for root, root_spec in zip(roots, specs):
        db = connect(root); root_jobs = [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY k,action,seed")]; db.close()
        owned = {(r["instance_key"], a, 0) for r in shard_rows(rows, root_spec) for a in ACTIONS}
        if {(r["k"],r["action"],r["seed"]) for r in root_jobs} != owned or len(root_jobs) != len(owned):
            raise ValueError("queue does not cover the complete planned task matrix")
        jobs += root_jobs
        _collect_root(root, root_jobs, spec, identity, cases, records, evidence, root.name + "/" if sharded else "")
    if {(r["k"],r["action"],r["seed"]) for r in jobs} != expected or len(jobs) != len(expected):
        raise ValueError("queue does not cover the complete planned task matrix")
    jobs.sort(key=lambda r: (r["k"], r["action"], r["seed"]))
    complete = [r for r in cases.values() if set(r["outcomes"]) == set(ACTIONS)]
    for c in complete:
        answers = {r["answer_reported"] for r in c["outcomes"].values() if r["resolved"]}
        if len(answers) > 1: raise ValueError("contradictory verified answers")
    costs = {a: statistics.mean(c["outcomes"][a]["par2"] for c in complete) if complete else None for a in ACTIONS}
    vbs = statistics.mean(min(c["outcomes"][a]["par2"] for a in ACTIONS) for c in complete) if complete else None
    totals = {a: sum(c["outcomes"][a]["resolved"] for c in complete) for a in ACTIONS}
    summary = {"scope": spec["status"], "full_cohort": len(rows), "expected_runs": len(expected), "recorded_runs":len(records),
               "valid_runs":sum(r["valid_measurement"] for r in records), "complete_parents":len(complete),
               "status":"COMPLETE_VALID_MATRIX" if len(complete)==len(rows) else "PARTIAL",
               "plot_population":"complete parent triads only, with full planned denominator displayed",
               "mean_par2":costs, "time_vbs_mean_par2":vbs, "solved":totals,
               "solved_union":sum(any(r["resolved"] for r in c["outcomes"].values()) for c in complete),
               "all_censored":sum(not any(r["resolved"] for r in c["outcomes"].values()) for c in complete),
               "cutoff_s":spec["cutoff_s"], "measurement_identity":identity,
               "collector_sha256":sha(Path(__file__)),
               "evidence":evidence, "snapshot_source_progress":read(roots[0]/"progress.json") if not sharded else
                   {r.name: read(r/"progress.json") for r in roots}, "shard_roots":[str(r) for r in roots] if sharded else None}
    out.mkdir(parents=True)
    write(out/"summary.json", summary)
    write(out/"instances.json", list(cases.values()))
    with (out/"runs.csv").open("w",newline="") as f:
        fields=["instance_key","action","seed","run_id","status","resolved","verification_status","cpu_s","wall_s","conflicts","decisions","propagations","restarts","maxrss_kib","stop_reason","par2"]
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(records)
    with (out/"matrix.csv").open("w",newline="") as f:
        fields=["instance_key","complete"]+[a+"_"+q for a in ACTIONS for q in ["status","cpu_s","conflicts","par2"]]
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for c in cases.values():
            row={"instance_key":c["instance_key"],"complete":len(c["outcomes"])==3}
            row.update({a+"_"+q:r[q] for a,r in c["outcomes"].items() for q in ["status","cpu_s","conflicts","par2"]})
            w.writerow(row)
    write(out/"coverage.json",{"jobs":jobs,"full_cohort":len(rows),"complete_parents":len(complete)})
    return summary


def _collect_root(root, jobs, spec, identity, cases, records, evidence, prefix):
    for job in jobs:
        if not job["result"]: continue
        path = Path(job["result"]); r = read(path)
        key = r["measurement_key"]
        if key["identity"] != identity or fingerprint(key) != r["run_id"] or (r["instance_key"],r["action"],r["seed"]) != (job["k"],job["action"],job["seed"]):
            raise ValueError("wrong physical result for a logical task")
        staged = read(root/"input_receipts"/(job["k"]+".json"))
        if r["input_sha256"] != staged["input_sha256"]: raise ValueError("mixed CNF inputs")
        directory = path.parent
        if sha(directory/"solver.log.gz") != r["compressed_log_sha256"] or sha(directory/"last1000.log") != r["tail_log_sha256"]:
            raise ValueError("changed raw solver output")
        import hashlib
        h = hashlib.sha256()
        with gzip.open(directory/"solver.log.gz", "rb") as f:
            for chunk in iter(lambda:f.read(1<<20),b""): h.update(chunk)
        if h.hexdigest() != r["log_sha256"]: raise ValueError("raw log SHA mismatch")
        if r["valid_measurement"]:
            if r["resolved"] and (not r["verification_status"].startswith("VERIFIED_") or r["cpu_s"] > spec["cutoff_s"]):
                raise ValueError("unsupported solved claim")
            cases[job["k"]]["outcomes"][job["action"]] = r
        records.append(r); evidence.append({"path": prefix + str(path.relative_to(root)), "sha256":sha(path)})


def main():
    p=argparse.ArgumentParser();p.add_argument("--root",required=True,nargs="+",help="one run root, or every shard root");p.add_argument("--snapshot",required=True);a=p.parse_args()
    s=collect_roots(a.root,a.snapshot);print(json.dumps({k:s[k] for k in ["status","complete_parents","recorded_runs"]}))


if __name__=="__main__":main()
