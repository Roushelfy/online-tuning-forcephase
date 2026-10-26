#!/usr/bin/env bash
# Run one v10 stage on a non-exclusive cpu-low allocation (72 logical CPUs = 36 physical cores, 700 GB) inside the
# gs-srun container; optionally a generator step first (generator venv). No aggregate CPU-hour limit
# (configs/resource_policy.json); every run is capped at 3600 CPU s (configs/run_timeout_policy.json); the Slurm
# walltime is a scheduling constraint only. --no-requeue: a node failure ends the job instead of silently re-running
# it (v9 lost two runs that way); re-runs go to a new stage.
#   scripts/cross_scale_v10/slurm_run.sh <stage> [plan.json] ["gen.py args"] [time=7-00:00:00] [extra sbatch args]
# Logs: $FP_DATA/logs/slurm/v10-<stage>-<jobid>_0.{out,err}
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE="$1"; PLAN="${2:-}"; GENARGS="${3:-}"; TIME="${4:-7-00:00:00}"; EXTRA="${5:-}"
FP_DATA="${FP_DATA:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase}"
mkdir -p "$FP_DATA/logs/slurm"
df -h /mnt/data | tail -1
# --array=0-0: gs-srun inside sbatch runs in the allocation only for array jobs
sbatch --parsable --no-requeue --job-name="v10-$STAGE" --partition=cpu-low --nodes=1 --ntasks=1 \
  --cpus-per-task="${V10_CPUS:-72}" --mem="${V10_MEM:-700G}" --time="$TIME" --array=0-0 $EXTRA \
  --output="$FP_DATA/logs/slurm/v10-$STAGE-%A_%a.out" --error="$FP_DATA/logs/slurm/v10-$STAGE-%A_%a.err" \
  --export=ALL,FP_DATA="$FP_DATA",V10_ROOT="$ROOT",V10_PLAN="$PLAN",V10_STAGE="$STAGE",V10_GENARGS="$GENARGS" <<'EOS'
#!/usr/bin/env bash
source /mnt/data/shared/config/env.sh
export GENESIS_IMAGE_VER="${GENESIS_IMAGE_VER:-1_26}"
echo "v10 $V10_STAGE on $(hostname) at $(date -u)"; df -h /mnt/data | tail -1
gs-srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK:-$SLURM_CPUS_ON_NODE}" bash -c "
  set -e; cd '$V10_ROOT'; export FP_DATA='$FP_DATA'
  if [ -n '$V10_GENARGS' ]; then
    /mnt/data/zhaofeng/venvs/online-tuning-forcephase-v8gen/bin/python scripts/cross_scale_v10/gen.py $V10_GENARGS
  fi
  if [ -n '$V10_PLAN' ]; then
    python3 scripts/cross_scale_v10/runner.py --plan '$V10_PLAN' --stage '$V10_STAGE'
  fi"
echo "finished at $(date -u)"
EOS
