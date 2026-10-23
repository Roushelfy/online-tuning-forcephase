#!/usr/bin/env bash
# Build the goal-v5 observation profiler into build/tools/ without touching
# the round-1 / v4 tools:
#   obsprofile (tools/obsprofile.c)   static / propagation / structure observations
# Run inside the gs-srun container (same toolchain as the solver builds).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$ROOT/build/tools"
mkdir -p "$OUT"
CC="${CC:-gcc}"
$CC -O2 -Wall -static -o "$OUT/obsprofile" "$ROOT/tools/obsprofile.c" -lm
{
  echo "cc=$($CC --version | head -1)"
  echo "obsprofile_sha256=$(sha256sum "$OUT/obsprofile" | cut -d' ' -f1)"
  echo "source_sha256=$(sha256sum "$ROOT/tools/obsprofile.c" | cut -d' ' -f1)"
  echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$OUT/BUILDINFO_v5"
cat "$OUT/BUILDINFO_v5"
