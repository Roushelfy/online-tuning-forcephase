#!/usr/bin/env bash
# Submit scripts/observations_v5/obsrun.py as a Slurm array of exclusive CPU
# nodes (gs-srun container; one-element arrays work too).
#
#   scripts/observations_v5/slurm_obsrun.sh <num_nodes> <jobs_per_node> <time> -- <obsrun args...>
#   e.g. scripts/observations_v5/slurm_obsrun.sh 1 48 01:00:00 -- eqv --hashes configs/observations_v5/eng_panel.txt
#
# Logs: $FP_DATA/logs/slurm/v5-<cmd>-<jobid>_<task>.{out,err}
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
N="$1"; JOBS="$2"; TIME="$3"; shift 3; [ "$1" = "--" ] && shift
FP_DATA="${FP_DATA:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase}"
mkdir -p "$FP_DATA/logs/slurm"
# arguments go through a file: sbatch --export splits values at commas
ARGF="$(mktemp "$FP_DATA/logs/slurm/v5-args-XXXXXX")"
printf '%q ' "$@" > "$ARGF"
sbatch --parsable --job-name="v5-$1" --partition=cpu-low --nodes=1 --ntasks=1 --exclusive --mem=0 \
  --time="$TIME" --array="0-$((N-1))" \
  --output="$FP_DATA/logs/slurm/v5-$1-%A_%a.out" --error="$FP_DATA/logs/slurm/v5-$1-%A_%a.err" \
  --export=ALL,FP_DATA="$FP_DATA",V5_ARGF="$ARGF",V5_N="$N",V5_JOBS="$JOBS",V5_ROOT="$ROOT" <<'EOS'
#!/usr/bin/env bash
source /mnt/data/shared/config/env.sh
export GENESIS_IMAGE_VER="${GENESIS_IMAGE_VER:-1_26}"
echo "task $SLURM_ARRAY_TASK_ID/$V5_N on $(hostname) at $(date -u)"
gs-srun --ntasks=1 --cpus-per-task="$SLURM_CPUS_ON_NODE" \
  bash -c "cd '$V5_ROOT' && FP_DATA='$FP_DATA' FP_LOCAL=/tmp/fp_local_\$USER python3 scripts/observations_v5/obsrun.py $(cat "$V5_ARGF") --shard $SLURM_ARRAY_TASK_ID/$V5_N --jobs $V5_JOBS"
echo "finished at $(date -u)"
EOS
