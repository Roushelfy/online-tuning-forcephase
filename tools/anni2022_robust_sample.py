"""Sample for the preference-robustness check (seed 1 and a variable-permuted, clause-shuffled copy):
  R = all 162 instances where D times out and F+ or F- solves (the professor's list);
  G = 150 random instances where D solves and some forced mode is >= 2x faster with D >= 1 s;
  C = 150 random instances from the rest. Seed 20261117.
  python3 tools/anni2022_robust_sample.py --data DATA --out SAMPLE.json
"""
import argparse, csv, glob, json, os, random
p = argparse.ArgumentParser(); p.add_argument("--data", required=True); p.add_argument("--out", required=True); a = p.parse_args()
rows = sorted(csv.DictReader(open(os.path.join(a.data, "cluster_v3_analysis/matrix.csv"))), key=lambda r: r["instance_key"])
ok = lambda r, m: r[m + "_status"] in ("SAT", "UNSAT"); t = lambda r, m: float(r[m + "_cpu_s"])
R = [r["instance_key"] for r in rows if r["D_status"] == "CPU_TIMEOUT" and (ok(r, "Fplus") or ok(r, "Fminus"))]
G = [r["instance_key"] for r in rows if ok(r, "D") and t(r, "D") >= 1 and any(ok(r, m) and 2 * t(r, m) <= t(r, "D") for m in ("Fplus", "Fminus"))]
rest = [r["instance_key"] for r in rows if r["instance_key"] not in set(R) | set(G)]
rng = random.Random(20261117); Gs = sorted(rng.sample(G, 150)); Cs = sorted(rng.sample(rest, 150))
size = {}
for f in glob.glob(os.path.join(a.data, "cluster_v3/shard-*/input_receipts/*.json")):
    r = json.load(open(f)); size[r["instance_key"]] = r["bytes"]
inst = [{"instance_key": k, "stratum": s} for s, ks in (("R", R), ("G", Gs), ("C", Cs)) for k in ks]
json.dump({"instances": inst, "population": {"R": len(R), "G": len(G), "C": len(rest)}}, open(a.out, "w"), indent=1)
print(len(inst), {"R": len(R), "G": len(G), "C": len(rest)}, "plain GiB %.1f" % (sum(size[x["instance_key"]] for x in inst) / 2**30),
      "max GiB %.2f" % (max(size[x["instance_key"]] for x in inst) / 2**30))
