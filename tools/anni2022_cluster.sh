#!/usr/bin/env bash
# Cluster launcher for the Anniversary 2022 T600 baseline (Genesis Slurm, cpu-mid, gs-srun container).
# Each shard is one owner process (the original single-owner runner, 8 CPU tokens) on its own Slurm job and run root.
#
#   tools/anni2022_cluster.sh start  [INDEX ...]   # first launch (default: every shard 0..COUNT-1)
#   tools/anni2022_cluster.sh resume [INDEX ...]   # re-attach to existing shard roots (frozen spec read from the root)
#   tools/anni2022_cluster.sh recover [INDEX ...]  # resume --recover-incomplete: requeue attempts interrupted by a lost job
#   tools/anni2022_cluster.sh status               # per-shard progress.json summary
#   tools/anni2022_cluster.sh collect SNAPSHOT_DIR # merged snapshot over all shard roots (run in a container)
#
# Environment: ANNI_RUN (run directory), ANNI_COUNT (shards, default 24), ANNI_TIME (Slurm walltime, scheduling only).
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="${ANNI_RUN:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase/anni2022_baseline/cluster_v3}"
COUNT="${ANNI_COUNT:-24}"
SPEC="configs/anniversary2022_baseline/spec.cluster-v1.json"
MANIFEST="configs/anniversary2022_baseline/manifest.official-solvable.v1.csv"
CMD="${1:?start|resume|recover|status|collect}"; shift || true
mkdir -p "$RUN/logs"

shard_root() { printf '%s/shard-%03d' "$RUN" "$1"; }

case "$CMD" in
  status)
    for d in "$RUN"/shard-*; do
      [ -f "$d/progress.json" ] && python3 -c "import json,sys;p=json.load(open(sys.argv[1]));print(sys.argv[1].split('/')[-2],p['status'],p['completed_valid'],'/',p['expected_runs'],p['jobs'],p.get('admission_note'),p['updated_utc'])" "$d/progress.json"
    done; exit 0;;
  collect)
    OUT="${1:?snapshot directory}"
    roots=(); for i in $(seq 0 $((COUNT-1))); do roots+=("$(shard_root "$i")"); done
    cd "$SRC" && python3 -m src.anniversary2022_baseline.collect_results --root "${roots[@]}" --snapshot "$OUT"; exit 0;;
  start|resume|recover) ;;
  *) echo "unknown command $CMD" >&2; exit 1;;
esac

IDX=("$@"); [ ${#IDX[@]} -eq 0 ] && IDX=($(seq 0 $((COUNT-1))))
df -h /mnt/data | tail -1
for i in "${IDX[@]}"; do
  R="$(shard_root "$i")"
  if [ "$CMD" = start ]; then
    [ -e "$R/metadata/spec.json" ] && { echo "shard $i already started; use resume" >&2; exit 1; }
    ARGS="start --root '$R' --spec '$SPEC' --manifest '$MANIFEST' --shard $i/$COUNT"
  elif [ "$CMD" = recover ]; then
    ARGS="resume --root '$R' --recover-incomplete"
  else
    ARGS="resume --root '$R'"
  fi
  # --array=0-0: gs-srun inside sbatch runs in the allocation only for array jobs. --no-requeue: a node failure ends
  # the job; in-flight attempts are then BLOCKED by the runner and need an explicit recovery, never a silent re-run.
  sbatch --parsable --no-requeue --job-name="$(printf 'anni22-s%03d' "$i")" --partition=cpu-mid --nodes=1 --ntasks=1 \
    --cpus-per-task=20 --mem=200G --time="${ANNI_TIME:-4-00:00:00}" --array=0-0 \
    --output="$RUN/logs/shard-$(printf %03d "$i")-%A_%a.out" --error="$RUN/logs/shard-$(printf %03d "$i")-%A_%a.err" \
    --export=ALL,ANNI_SRC="$SRC",ANNI_ARGS="$ARGS" <<'EOS'
#!/usr/bin/env bash
source /mnt/data/shared/config/env.sh
export GENESIS_IMAGE_VER="${GENESIS_IMAGE_VER:-1_26}"
echo "anni2022 $ANNI_ARGS on $(hostname) at $(date -u)"; df -h /mnt/data | tail -1
gs-srun --ntasks=1 --cpus-per-task="$SLURM_CPUS_PER_TASK" bash -c "
  cd '$ANNI_SRC'; echo container \$(hostname) affinity \$(python3 -c 'import os;print(sorted(os.sched_getaffinity(0)))')
  df -h /var/tmp | tail -1
  python3 -m src.anniversary2022_baseline.run_baselines $ANNI_ARGS; rc=\$?
  echo 'proofs left on node-local disk (failed verifications only):'; ls -la /var/tmp/anni2022-cluster-v1/* 2>/dev/null
  exit \$rc"
rc=$?
echo "finished at $(date -u) exit $rc"
EOS
done
