#!/usr/bin/env bash
# Run one v9 stage on a non-exclusive cpu-low allocation (72 logical CPUs = 36 physical cores, 700 GB) inside the
# gs-srun container; optionally generate instances first (generator venv). No CPU-hour limit (configs/resource_policy.json);
# the Slurm walltime is a scheduling constraint only.
#   scripts/online_selection_v9/slurm_run.sh <stage> [plan.json] [gen-plan.json gen-manifest.json] [time=7-00:00:00] [extra sbatch args]
# Logs: $FP_DATA/logs/slurm/v9-<stage>-<jobid>_0.{out,err}
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE="$1"; PLAN="${2:-}"; GENPLAN="${3:-}"; GENMAN="${4:-}"; TIME="${5:-7-00:00:00}"; EXTRA="${6:-}"
FP_DATA="${FP_DATA:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase}"
mkdir -p "$FP_DATA/logs/slurm"
# --array=0-0: gs-srun inside sbatch runs in the allocation only for array jobs
sbatch --parsable --job-name="v9-$STAGE" --partition=cpu-low --nodes=1 --ntasks=1 --cpus-per-task="${V9_CPUS:-72}" --mem="${V9_MEM:-700G}" \
  --time="$TIME" --array=0-0 $EXTRA \
  --output="$FP_DATA/logs/slurm/v9-$STAGE-%A_%a.out" --error="$FP_DATA/logs/slurm/v9-$STAGE-%A_%a.err" \
  --export=ALL,FP_DATA="$FP_DATA",V9_ROOT="$ROOT",V9_PLAN="$PLAN",V9_STAGE="$STAGE",V9_GENPLAN="$GENPLAN",V9_GENMAN="$GENMAN" <<'EOS'
#!/usr/bin/env bash
source /mnt/data/shared/config/env.sh
export GENESIS_IMAGE_VER="${GENESIS_IMAGE_VER:-1_26}"
echo "v9 $V9_STAGE on $(hostname) at $(date -u)"
gs-srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK:-$SLURM_CPUS_ON_NODE}" bash -c "
  set -e; cd '$V9_ROOT'; export FP_DATA='$FP_DATA'
  if [ -n '$V9_GENPLAN' ]; then
    /mnt/data/zhaofeng/venvs/online-tuning-forcephase-v8gen/bin/python scripts/online_selection_v9/generate.py --plan '$V9_GENPLAN' --out-manifest '$V9_GENMAN'
  fi
  if [ -n '$V9_PLAN' ]; then
    python3 scripts/online_selection_v9/runner.py --plan '$V9_PLAN' --stage '$V9_STAGE'
  fi"
echo "finished at $(date -u)"
EOS
