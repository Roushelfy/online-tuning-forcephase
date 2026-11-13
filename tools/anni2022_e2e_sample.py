"""Stratified sample for the end-to-end check: 250 instances where the static or the dynamic (w=2, continue)
selector leaves D, 250 from the rest (seed 20261116), with the frozen OOF actions and the replay costs.

  python3 tools/anni2022_e2e_sample.py --data DATA --analysis ANALYSIS_DIR --out SAMPLE.json
"""
import argparse, csv, glob, json, os, random
import numpy as np
MODES = ("D", "Fplus", "Fminus")
p = argparse.ArgumentParser(); [p.add_argument(x, required=True) for x in ("--data", "--analysis", "--out")]; a = p.parse_args()
keys = sorted(r["instance_key"] for r in csv.DictReader(open(os.path.join(a.data, "cluster_v3_analysis/matrix.csv"))))
sa = np.load(os.path.join(a.analysis, "static_actions.npy")); sq = np.load(os.path.join(a.analysis, "static_query_fee.npy"))
sc = np.load(os.path.join(a.analysis, "costs/static_cluster.npy"))
pa = np.load(os.path.join(a.analysis, "actions/probe_w2_continue_learned:dynamic.npy"))
pc = np.load(os.path.join(a.analysis, "costs/probe_w2_continue_learned:dynamic.npy"))
receipts = {}
for f in glob.glob(os.path.join(a.data, "cluster_v3/shard-*/input_receipts/*.json")):
    r = json.load(open(f)); receipts[r["instance_key"]] = r["input_sha256"]
switch = [i for i in range(len(keys)) if sa[i] or pa[i]]; rest = [i for i in range(len(keys)) if not (sa[i] or pa[i])]
rng = random.Random(20261116); pick = sorted(rng.sample(switch, 250) + rng.sample(rest, 250))
inst = [{"instance_key": keys[i], "static_action": MODES[sa[i]], "static_query_fee": float(sq[i]), "probe_action": MODES[pa[i]],
         "stratum": "switch" if (sa[i] or pa[i]) else "rest", "replay": {"static_PAR2": float(sc[i]), "probe_PAR2": float(pc[i])}} for i in pick]
json.dump({"instances": inst, "input_sha256": {r["instance_key"]: receipts[r["instance_key"]] for r in inst},
           "switch_population": len(switch), "rest_population": len(rest)}, open(a.out, "w"), indent=1)
print(len(inst), "instances; switch population", len(switch), "rest", len(rest))
