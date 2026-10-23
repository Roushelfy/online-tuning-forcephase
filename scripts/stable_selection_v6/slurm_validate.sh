#!/usr/bin/env bash
# R4 (protocol section 5): fixed D / F+ / F- and the frozen wrapper(s) in the
# same Slurm batch on the same nodes, interleaved: on each node one runner per
# CPU socket (sockets swapped on odd array tasks), 24 jobs each (48 per node).
#
#   scripts/stable_selection_v6/slurm_validate.sh <num_nodes> <time> <strategy.json[,...]>
# (the 2026-10-23 run used an earlier version that waited with 'pgrep -f', which matched
#  its own command line; the job was cancelled after all records were written.)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
N="$1"; TIME="$2"; STRAT="$3"
FP_DATA="${FP_DATA:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase}"
mkdir -p "$FP_DATA/logs/slurm"
ARGF="$(mktemp "$FP_DATA/logs/slurm/v6-validate-XXXXXX")"
printf '%s' "$STRAT" > "$ARGF"
sbatch --parsable --job-name="v6-validate" --partition=cpu-low --nodes=1 --ntasks=1 --exclusive --mem=0 \
  --time="$TIME" --array="0-$((N-1))" \
  --output="$FP_DATA/logs/slurm/v6-validate-%A_%a.out" --error="$FP_DATA/logs/slurm/v6-validate-%A_%a.err" \
  --export=ALL,FP_DATA="$FP_DATA",V6_ARGF="$ARGF",V6_N="$N",V6_ROOT="$ROOT" <<'EOS'
#!/usr/bin/env bash
source /mnt/data/shared/config/env.sh
export GENESIS_IMAGE_VER="${GENESIS_IMAGE_VER:-1_26}"
echo "task $SLURM_ARRAY_TASK_ID/$V6_N on $(hostname) at $(date -u)"
S1=$(( SLURM_ARRAY_TASK_ID % 2 )); S2=$(( 1 - S1 ))
gs-srun --ntasks=1 --cpus-per-task="$SLURM_CPUS_ON_NODE" \
  bash -c "cd '$V6_ROOT' && export FP_DATA='$FP_DATA' FP_LOCAL=/tmp/fp_local_\$USER && \
    python3 scripts/stable_selection_v6/on_socket.py $S1 python3 scripts/fprun.py run --exp configs/stable_selection_v6/v6_validate_fixed.json --shard $SLURM_ARRAY_TASK_ID/$V6_N --jobs 24 > /tmp/v6_fixed.log 2>&1 & FIXED=\$!; \
    python3 scripts/stable_selection_v6/on_socket.py $S2 python3 scripts/stable_selection_v6/v6run.py wrap --hashes configs/stable_selection_v6/validate_hashes.txt --strategy $(cat "$V6_ARGF") --shard $SLURM_ARRAY_TASK_ID/$V6_N --jobs 24; \
    wait \$FIXED; cat /tmp/v6_fixed.log"
echo "finished at $(date -u)"
EOS
