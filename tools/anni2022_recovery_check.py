"""Functional check of the cluster additions with real solver runs (run inside the container, repository root as cwd):
two shards, node-local cache/proof directories, an owner killed mid-run together with its solver, a plain resume
that must keep the interrupted attempts BLOCKED, resume --recover-incomplete, and the merged two-shard snapshot.

  python3 tools/anni2022_recovery_check.py --base NEW_DIR --solver CADICAL --checker LRAT_TRIM
"""
import argparse
import csv
import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.anniversary2022_baseline.common import ACTIONS, read, sha, write  # noqa: E402
from src.anniversary2022_baseline.qualification import pigeonhole  # noqa: E402


def module(name, *args):
    return [sys.executable, "-m", "src.anniversary2022_baseline." + name, *map(str, args)]


def main():
    p = argparse.ArgumentParser(); p.add_argument("--base", required=True); p.add_argument("--solver", required=True)
    p.add_argument("--checker", required=True); a = p.parse_args()
    base = Path(a.base).resolve()
    if base.exists(): raise SystemExit("base must be new")
    # Become the subreaper so the killed owner's orphaned solvers are reaped here, as a torn-down Slurm job would leave none.
    ctypes.CDLL(None).prctl(36, 1, 0, 0, 0)
    fixtures = base / "fixtures"; fixtures.mkdir(parents=True)
    # Position 0 (shard 0/2): a 10 s CPU timeout, killed mid-run. Position 1 (shard 1/2): a small UNSAT instance.
    (fixtures / "timeout.cnf").write_text(pigeonhole(24, 23)); (fixtures / "unsat.cnf").write_text(pigeonhole(5, 4))
    manifest = base / "manifest.csv"
    with manifest.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["instance_key", "url", "role", "expected_sha256_cnf"]); w.writeheader()
        for name in ["timeout", "unsat"]:
            w.writerow({"instance_key": name, "url": (fixtures / (name + ".cnf")).as_uri(), "role": "qualification",
                        "expected_sha256_cnf": sha(fixtures / (name + ".cnf"))})
    local = base / "node_local"
    spec = {"status": "QUALIFICATION", "expected_inputs": 2, "manifest_sha256": sha(manifest), "actions": ACTIONS,
            "seeds": [0], "solver_path": a.solver, "solver_sha256": sha(a.solver), "checker_path": a.checker,
            "checker_sha256": sha(a.checker), "solver_commit": "c60730422e758ef1cebe7aeddf2dda31c996bf04",
            "cutoff_s": 10, "wall_watchdog_s": 30, "termination_grace_s": 2, "checker_cpu_s": 20, "checker_wall_s": 30,
            "workers": 2, "memory_bytes": 1 << 30, "memory_reserve_bytes": 1 << 30, "proof_limit_bytes": 1 << 30,
            "disk_reserve_bytes": 1 << 30, "root_reserve_bytes": 1 << 30, "download_workers": 1, "download_wall_s": 30,
            "prefetch_parents": 2, "max_physical_cpu_hours": 0.05, "evict_completed_inputs": True,
            "proof_dir": str(local / "proofs"), "cache_dir": str(local / "cache")}
    write(base / "spec.json", spec)
    r0, r1 = base / "shard-000", base / "shard-001"
    checks = {}
    # 1. start shard 0 and kill owner + solvers once two attempts are running (as a Slurm cancel would)
    owner = subprocess.Popen(module("run_baselines", "start", "--root", r0, "--spec", base / "spec.json", "--manifest",
                                    manifest, "--shard", "0/2"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 60
    while len(list(r0.glob("runs/*/active.json"))) < 2 and time.monotonic() < deadline: time.sleep(0.1)
    time.sleep(2)
    actives = [read(x) for x in r0.glob("runs/*/active.json")]
    owner.send_signal(signal.SIGKILL); owner.wait()
    for x in actives:
        try: os.killpg(x["pid"], signal.SIGKILL)
        except ProcessLookupError: pass
    time.sleep(1)
    while True:
        try:
            if os.waitpid(-1, os.WNOHANG)[0] == 0: break
        except ChildProcessError: break
    checks["killed_attempts"] = len(actives)
    # 2. plain resume: interrupted attempts stay BLOCKED, the third task completes
    plain = subprocess.run(module("run_baselines", "resume", "--root", r0), capture_output=True, text=True, timeout=120)
    snap = json.loads(plain.stdout.strip().splitlines()[-1])
    checks["plain_resume"] = {"exit": plain.returncode, "jobs": snap["jobs"], "status": snap["status"]}
    assert plain.returncode == 2 and snap["jobs"].get("BLOCKED") == len(actives), checks
    # 3. explicit recovery
    rec = subprocess.run(module("run_baselines", "resume", "--root", r0, "--recover-incomplete"), capture_output=True, text=True, timeout=120)
    snap = json.loads(rec.stdout.strip().splitlines()[-1])
    recovery = read(next((r0 / "recoveries").glob("*.json")))
    checks["recovery"] = {"exit": rec.returncode, "jobs": snap["jobs"], "status": snap["status"],
                          "requeued": len(recovery["jobs_requeued"]), "moved": sum(bool(j["moved_attempt"]) for j in recovery["jobs_requeued"]),
                          "aborted_attempt_dirs": len(list((r0 / "aborted_attempts").iterdir()))}
    assert rec.returncode == 0 and snap["status"] == "COMPLETE_VALID_MATRIX" and checks["recovery"]["moved"] == len(actives), checks
    # 4. shard 1 normally, then the merged snapshot
    one = subprocess.run(module("run_baselines", "start", "--root", r1, "--spec", base / "spec.json", "--manifest", manifest,
                                "--shard", "1/2"), capture_output=True, text=True, timeout=120)
    assert one.returncode == 0, one.stderr[-2000:]
    out = subprocess.run(module("collect_results", "--root", r0, r1, "--snapshot", base / "snapshot"), capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    summary = read(base / "snapshot" / "summary.json")
    runs = list(csv.DictReader((base / "snapshot" / "runs.csv").open()))
    checks["merged"] = {"status": summary["status"], "complete_parents": summary["complete_parents"], "solved": summary["solved"],
                        "statuses": sorted({(r["instance_key"], r["status"]) for r in runs}),
                        "conflicts": sorted((r["instance_key"], r["action"], r["conflicts"]) for r in runs)}
    assert summary["status"] == "COMPLETE_VALID_MATRIX" and summary["complete_parents"] == 2, checks
    assert all(r["conflicts"] not in ("", None) for r in runs), checks
    # 5. a merge with one shard missing must be refused
    bad = subprocess.run(module("collect_results", "--root", r0, "--snapshot", base / "snapshot_bad"), capture_output=True, text=True, timeout=60)
    checks["single_shard_merge_refused"] = bad.returncode != 0 and "partition" in bad.stderr
    assert checks["single_shard_merge_refused"], bad.stderr[-1000:]
    checks["node_local_left"] = sorted(str(x.relative_to(local)) for x in local.rglob("*") if x.is_file())
    write(base / "RECOVERY_CHECK.json", {"status": "PASS", **checks})
    print(json.dumps({"status": "PASS", **checks}))


if __name__ == "__main__":
    main()
