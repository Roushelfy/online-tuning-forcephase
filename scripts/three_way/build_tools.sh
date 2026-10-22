#!/usr/bin/env bash
# Build the three-way study's extra tool into build/tools/ without touching
# the round-1 tools (scripts/build_tools.sh):
#   cnfprofile (tools/cnfprofile.c)   static CNF profile for the selector
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$ROOT/build/tools"
mkdir -p "$OUT"
CC="${CC:-gcc}"
$CC -O2 -Wall -static -o "$OUT/cnfprofile" "$ROOT/tools/cnfprofile.c" -lm
{
  echo "cc=$($CC --version | head -1)"
  echo "cnfprofile_sha256=$(sha256sum "$OUT/cnfprofile" | cut -d' ' -f1)"
  echo "source_sha256=$(sha256sum "$ROOT/tools/cnfprofile.c" | cut -d' ' -f1)"
} > "$OUT/BUILDINFO_three_way"
cat "$OUT/BUILDINFO_three_way"
