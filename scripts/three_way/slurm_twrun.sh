#!/usr/bin/env bash
# Submit scripts/three_way/twrun.py as a Slurm array of exclusive CPU nodes
# (gs-srun container; one-element arrays work too).
#
#   scripts/three_way/slurm_twrun.sh <num_nodes> <jobs_per_node> <time> -- <twrun args...>
#   e.g. scripts/three_way/slurm_twrun.sh 1 48 02:00:00 -- probe --hashes configs/three_way/dev_hashes.txt
#
# Logs: $FP_DATA/logs/slurm/tw-<cmd>-<jobid>_<task>.{out,err}
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
N="$1"; JOBS="$2"; TIME="$3"; shift 3; [ "$1" = "--" ] && shift
FP_DATA="${FP_DATA:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase}"
mkdir -p "$FP_DATA/logs/slurm"
# arguments go through a file: sbatch --export splits values at commas
ARGF="$(mktemp "$FP_DATA/logs/slurm/tw-args-XXXXXX")"
printf '%q ' "$@" > "$ARGF"
sbatch --parsable --job-name="tw-$1" --partition=cpu-low --nodes=1 --ntasks=1 --exclusive --mem=0 \
  --time="$TIME" --array="0-$((N-1))" \
  --output="$FP_DATA/logs/slurm/tw-$1-%A_%a.out" --error="$FP_DATA/logs/slurm/tw-$1-%A_%a.err" \
  --export=ALL,FP_DATA="$FP_DATA",TW_ARGF="$ARGF",TW_N="$N",TW_JOBS="$JOBS",TW_ROOT="$ROOT" <<'EOS'
#!/usr/bin/env bash
source /mnt/data/shared/config/env.sh
export GENESIS_IMAGE_VER="${GENESIS_IMAGE_VER:-1_26}"
echo "task $SLURM_ARRAY_TASK_ID/$TW_N on $(hostname) at $(date -u)"
gs-srun --ntasks=1 --cpus-per-task="$SLURM_CPUS_ON_NODE" \
  bash -c "cd '$TW_ROOT' && FP_DATA='$FP_DATA' FP_LOCAL=/tmp/fp_local_\$USER python3 scripts/three_way/twrun.py $(cat "$TW_ARGF") --shard $SLURM_ARRAY_TASK_ID/$TW_N --jobs $TW_JOBS"
echo "finished at $(date -u)"
EOS
