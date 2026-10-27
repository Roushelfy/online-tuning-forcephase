#!/usr/bin/env bash
# Run one v11 stage on a non-exclusive cpu-mid allocation (default 72 logical CPUs = 36 physical cores, 700 GB; cpu-low is
# preemptible, see v10 protocol section 12) inside the
# gs-srun container; optionally a generator step first (generator venv). No aggregate CPU-hour limit
# (configs/resource_policy.json); every run is capped at 3600 CPU s (configs/run_timeout_policy.json); the Slurm
# walltime is a scheduling constraint only. --no-requeue: a node failure ends the job instead of silently re-running
# it (v9 lost two runs that way); re-runs go to a new stage.
#   scripts/broad_scope_v11/slurm_run.sh <stage> [plan.json] ["gen.py args"] [time=7-00:00:00] [extra sbatch args]
# Logs: $FP_DATA/logs/slurm/v11-<stage>-<jobid>_0.{out,err}
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE="$1"; PLAN="${2:-}"; GENARGS="${3:-}"; TIME="${4:-7-00:00:00}"; EXTRA="${5:-}"
FP_DATA="${FP_DATA:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase}"
mkdir -p "$FP_DATA/logs/slurm"
df -h /mnt/data | tail -1
# --array=0-0: gs-srun inside sbatch runs in the allocation only for array jobs
sbatch --parsable --no-requeue --job-name="v11-$STAGE" --partition="${V11_PARTITION:-cpu-mid}" --nodes=1 --ntasks=1 \
  --cpus-per-task="${V11_CPUS:-72}" --mem="${V11_MEM:-700G}" --time="$TIME" --array=0-0 $EXTRA \
  --output="$FP_DATA/logs/slurm/v11-$STAGE-%A_%a.out" --error="$FP_DATA/logs/slurm/v11-$STAGE-%A_%a.err" \
  --export=ALL,FP_DATA="$FP_DATA",V11_ROOT="$ROOT",V11_PLAN="$PLAN",V11_STAGE="$STAGE",V11_GENARGS="$GENARGS" <<'EOS'
#!/usr/bin/env bash
source /mnt/data/shared/config/env.sh
export GENESIS_IMAGE_VER="${GENESIS_IMAGE_VER:-1_26}"
echo "v11 $V11_STAGE on $(hostname) at $(date -u)"; df -h /mnt/data | tail -1
gs-srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK:-$SLURM_CPUS_ON_NODE}" bash -c "
  set -e; cd '$V11_ROOT'; export FP_DATA='$FP_DATA' V11_MULTI='${V11_MULTI:-}'
  if [ -n '$V11_GENARGS' ]; then
    /mnt/data/zhaofeng/venvs/online-tuning-forcephase-v8gen/bin/python scripts/broad_scope_v11/gen.py $V11_GENARGS
  fi
  if [ -n '$V11_PLAN' ]; then
    python3 scripts/broad_scope_v11/runner.py --plan '$V11_PLAN' --stage '$V11_STAGE'
  fi"
echo "finished at $(date -u)"
EOS
