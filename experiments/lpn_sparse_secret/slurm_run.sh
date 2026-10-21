#!/usr/bin/env bash
# Run run_all.sh on one exclusive Slurm node inside the gs-srun container
# (CoreWeave cluster layout; tested). The job is a one-element array because
# gs-srun inside a plain (non-array) sbatch allocation fails with "CPU count
# per node can not be satisfied". All run_all.sh variables (GRID, T, WORKERS,
# QUIET_LOAD, VERIFY_WORKERS, LPN_WORK, SKIP_BUILD, SKIP_TEST, PYTHON, ...)
# are passed through from the caller's environment.
#
#   experiments/lpn_sparse_secret/slurm_run.sh [partition=cpu-low] [time=12:00:00]
#   GRID=smoke T=10 WORKERS=8 experiments/lpn_sparse_secret/slurm_run.sh
#
# Logs: $LPN_WORK/logs/<EXP>-<jobid>_0.{out,err}
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PART="${1:-cpu-low}"; TIME="${2:-12:00:00}"
export LPN_WORK="${LPN_WORK:-${FP_DATA:+$FP_DATA/lpn_sparse_secret}}"
[ -n "$LPN_WORK" ] || { echo "set LPN_WORK or FP_DATA" >&2; exit 1; }
EXP="${EXP:-lpn_${GRID:-sparse_main}}"
mkdir -p "$LPN_WORK/logs"
sbatch --parsable --job-name="$EXP" --partition="$PART" --nodes=1 --ntasks=1 --exclusive \
  --mem=0 --time="$TIME" --array=0-0 \
  --output="$LPN_WORK/logs/$EXP-%A_%a.out" --error="$LPN_WORK/logs/$EXP-%A_%a.err" \
  --export=ALL,LPN_HERE="$HERE" <<'EOS'
#!/usr/bin/env bash
source /mnt/data/shared/config/env.sh
export GENESIS_IMAGE_VER="${GENESIS_IMAGE_VER:-1_26}"
echo "start $(hostname) $(date -u +%FT%TZ)"
# pass run_all.sh settings explicitly rather than relying on the container
# inheriting the job environment
ENVS=""
for v in GRID EXP T WORKERS QUIET_LOAD MAX_WALL_HOURS CONFIGS VERIFY_WORKERS LPN_WORK LPN_CADICAL \
         LPN_LRAT_CHECK LPN_MIN_FREE_GB SKIP_BUILD SKIP_TEST PYTHON; do
  [ -n "${!v:-}" ] && ENVS+="$v=$(printf %q "${!v}") "
done
echo "settings: $ENVS"
gs-srun --ntasks=1 --cpus-per-task="$SLURM_CPUS_ON_NODE" bash -c "cd $(printf %q "$LPN_HERE") && env $ENVS ./run_all.sh"
echo "exit $? at $(date -u +%FT%TZ)"
EOS
