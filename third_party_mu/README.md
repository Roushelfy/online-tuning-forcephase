# Copied from collaborator Mu's archive

Source: GitHub `Ch40gRv1-Mu/online-tuning-forcephase`, branch `codex/forcephase-results-2026-11-11`, commit 1384bea,
path `research/2026-11-11/forcephase-2022-results/src/anniversary2022_baseline/`. Copied unchanged:

- `native_linear42.cpp`: native extractor of the 47 raw GBD base statistics behind the 42 selector inputs (8 s CPU limit;
  Mu's retry binary is the same source with a 16 s limit, generated at build time by substituting `cpu{8,8}` -> `cpu{16,16}` and `alarm(12)` -> `alarm(24)` only; see tools/build_week_tools.sh).
- `linear42_only_vector.py`: frozen raw-statistics -> 42-input mapping.
- `vendor_gbdc_base_9f3a418/`: the pinned GBD (gbdc 9f3a418) files the extractor includes, with Mu's SOURCE_LOCK.json.
