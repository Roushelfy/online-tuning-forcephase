# 三选一研究的五年面板（2022–2026）

由 `scripts/three_way/dataset_report.py` 从冻结的抽样输出生成。规则见 [THREE_WAY_PROTOCOL.md](../../docs/THREE_WAY_PROTOCOL.md) 第 2 节与 [FIVE_YEAR_SAMPLE_PLAN.md](../../docs/FIVE_YEAR_SAMPLE_PLAN.md)；只用元数据，未使用任何求解结果。

## 1. 来源与重建

- GBD 快照 2026-10-18：meta.db `5b8bbc767bc5300cca6a12717fb2d7c8d52ccee24aced4447d71846352744ff3`，base.db `15a3d19fd23ba72dd7c77b1b86113873f160760fa1c9710e9e5ed6a23ba29d84`。
- 官方名单（2026-10-22 下载，存于 `$FP_DATA/benchmarks/official/`），与 GBD 快照逐题一致：
  - 2022：`gbd_getinstances_main_2022.txt`，400 题，sha256 `3726ae3459564c8c1ef8b9f6af61028df64f23b6a96081c002386fa1ec0fc627`
  - 2023：`gbd_getinstances_main_2023.txt`，400 题，sha256 `6c21f0a721f940cdb1a4de7a6204d0818bcaf604c5343c5b39fd17dd9435d057`
  - 2024：`gbd_getinstances_main_2024.txt`，400 题，sha256 `2a811049f9ce83c75301edc87f8ae3a889cf5960e70aa38b393bc62239e1e2f0`
  - 2025：`gbd_getinstances_main_2025.txt`，400 题，sha256 `7c444f6dd65920a8381033d1ba8cc781d796c2c12d4ba7f72b098efdf0f1d8fd`
  - 2026：`track_main_2026.uri`，400 题，sha256 `d4e5d76862bc5e8825e495a4f6b05163fc2ab4d706de0a3fd3defacf7808b995`
- 抽样 seed 20261022；年度配额 100；单家族组上限 10；资源条件：GBD 未压缩字节 ≤ 1e+09。
- `results/three_way/manifest.csv` sha256 `b2ae0147b1cee58ba2d9ea0da6aa60ace1d7c3d255f07c07b0f64a0a55a65a2b`；`candidates.csv` sha256 `acfceefb541828488cb8f002bb5465ee1940fc16065cb2aff21c78acd55a928f`。

重建（只读元数据，确定性）：

```bash
export FP_DATA=/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase
mkdir -p $FP_DATA/benchmarks/official && cd $FP_DATA/benchmarks/official
for y in 2022 2023 2024 2025; do curl -sL -o gbd_getinstances_main_$y.txt "https://benchmark-database.de/getinstances?track=main_$y"; done
curl -sL -o track_main_2026.uri https://satcompetition.github.io/2026/downloads/track_main_2026.uri
cd - && scripts/three_way/sample_panel.py --gbd $FP_DATA/benchmarks/gbd --official $FP_DATA/benchmarks/official
sha256sum results/three_way/manifest.csv   # 应为上面的值
scripts/fetch_benchmarks.py --manifest results/three_way/manifest.csv --checksums results/three_way/checksums.csv --splits train,val,test
```

GBD 会持续更新；若重新下载的 meta/base 与上面的 sha256 不同，抽样结果可能不同。冻结面板以提交的 manifest 为准。

## 2. 逐年候选、排除、入选与替补

| 配额年 | 独立问题 | 排除（>1 GB） | 合格 | 家族组 | 入选 | 入选覆盖的组 | 未用配额 | 预排替补 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 375 | 16 | 359 | 54 | 100 | 54 | 0 | 259 |
| 2023 | 395 | 22 | 373 | 55 | 100 | 55 | 0 | 273 |
| 2024 | 392 | 16 | 376 | 61 | 100 | 61 | 0 | 276 |
| 2025 | 372 | 12 | 360 | 78 | 100 | 78 | 0 | 260 |
| 2026 | 331 | 2 | 329 | 79 | 100 | 79 | 0 | 229 |

- 五年主赛道共 2,000 个（hash，年份）条目，1931 个不同 hash，按 isohash 合并为 1865 个独立问题；跨年出现的问题 90 个（只计一次，配额年取最早年份）。
- 面板中跨年出现的问题 36 个；isohash 类有多个 hash 的 9 个。
- 下载：500/500 个入选 CNF 已下载并记录校验（`results/three_way/checksums.csv`）；未发生替换。

## 3. 规模分布

规模层按各配额年合格问题的 log10(1+子句数) 三分位：

| 配额年 | small / mid 界 | mid / large 界 |
|---|---:|---:|
| 2022 | 4.95 | 6.19 |
| 2023 | 4.44 | 5.50 |
| 2024 | 4.13 | 5.39 |
| 2025 | 4.65 | 5.92 |
| 2026 | 4.51 | 5.75 |

| split | small | mid | large | >100 MB | ≤10 MB |
|---|---:|---:|---:|---:|---:|
| train | 118 | 106 | 77 | 11 | 228 |
| val | 36 | 45 | 19 | 1 | 77 |
| test | 16 | 25 | 58 | 49 | 35 |

## 4. 划分（按家族组）

| split | 实例 | 家族组 | 2022 | 2023 | 2024 | 2025 | 2026 | 第一轮运行过 | 家族第一轮运行过 | GBD sat / unsat / unknown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 301 | 96 | 43 | 66 | 71 | 59 | 62 | 253 | 301 | 153 / 121 / 27 |
| val | 100 | 30 | 12 | 26 | 17 | 22 | 23 | 91 | 100 | 30 / 63 / 7 |
| test | 99 | 31 | 45 | 8 | 12 | 19 | 15 | 20 | 55 | 34 / 55 / 10 |

第一轮曝光明细（实例曾在哪个第一轮 split 中被运行）：

| split | none | train | val | test | t2026 |
|---|---:|---:|---:|---:|---:|
| train | 48 | 114 | 34 | 43 | 62 |
| val | 9 | 35 | 20 | 12 | 24 |
| test | 79 | 10 | 2 | 2 | 6 |

注：GBD sat/unsat 只用于事后分层，不参与抽样、划分或选择器。

## 5. 家族组覆盖

每个家族组在面板中的实例数（按 split）：

| 家族组 | split | 实例 | 配额年 | 第一轮运行过该家族 |
|---|---:|---:|---:|---:|
| scheduling | train | 20 | 2022,2023,2024,2025,2026 | yes |
| coloring | val | 15 | 2022,2023,2024,2025,2026 | yes |
| cryptography | train | 13 | 2022,2023,2024,2025,2026 | yes |
| argumentation | train | 12 | 2022,2023,2024,2025,2026 | yes |
| miter | train | 12 | 2022,2023,2024,2025,2026 | yes |
| hardware | test | 11 | 2022,2023,2024,2025,2026 | yes |
| software-verification | test | 11 | 2022,2024,2025,2026 | no |
| disagreement-parity | train | 9 | 2022,2023,2024,2025,2026 | yes |
| hamiltonian | train | 9 | 2024,2025,2026 | yes |
| set-covering | val | 9 | 2022,2023,2025 | yes |
| tseitin-formulas | val | 9 | 2022,2023,2024,2025,2026 | yes |
| school-timetabling | train | 8 | 2023,2025,2026 | yes |
| circuit-equivalence-checking | test | 7 | 2022,2025 | yes |
| multiplier | train | 7 | 2022,2024,2025,2026 | yes |
| pigeon-hole | train | 7 | 2022,2023,2024,2025 | yes |
| planning | train | 7 | 2022,2023,2024,2025,2026 | yes |
| cryptography-simon | train | 6 | 2023,2024 | yes |
| grs-fp-comm | val | 6 | 2023,2024,2025 | yes |
| maxsat-optimum | test | 6 | 2022,2024 | yes |
| sudoku | train | 6 | 2022,2025,2026 | yes |
| belpyramid-puzzle | val | 5 | 2025 | yes |
| bitvector | train | 5 | 2022,2023,2024,2025,2026 | yes |
| cellular-automata | val | 5 | 2022,2023,2024,2025,2026 | yes |
| crafted-cec | train | 5 | 2022,2023,2024,2025,2026 | yes |
| cryptography-ascon | train | 5 | 2023,2024 | yes |
| graph-isomorphism | test | 5 | 2022,2023,2024,2025 | no |
| independent-set-reconfiguration | test | 5 | 2022,2025,2026 | yes |
| mutilated-chessboard | train | 5 | 2023,2024,2025 | yes |
| social-golfer | train | 5 | 2023,2026 | yes |
| algorithm-equivalence-checking | test | 4 | 2022,2025 | yes |
| brent-equations | train | 4 | 2023 | yes |
| independent-set | train | 4 | 2024,2025 | yes |
| influence-maximization | val | 4 | 2022,2024,2025,2026 | yes |
| interval-matching | train | 4 | 2023 | yes |
| polynomial-multiplication | test | 4 | 2022,2024,2025,2026 | yes |
| quasigroup-completion | train | 4 | 2023,2024,2025,2026 | yes |
| random-circuits | train | 4 | 2024,2025 | yes |
| random-graph-xorsat | train | 4 | 2022,2023,2025,2026 | yes |
| register-allocation | val | 4 | 2023 | yes |
| risc-instruction-removal | train | 4 | 2023,2024,2025 | yes |
| sat-x | test | 4 | 2022,2025 | no |
| subgraph-isomorphism | val | 4 | 2023,2024,2025,2026 | yes |
| tree-decomposition | test | 4 | 2022,2024,2025,2026 | yes |
| van-der-waerden | train | 4 | 2024,2025,2026 | yes |
| baseball-lineup | test | 3 | 2023,2025,2026 | no |
| cril-misc | test | 3 | 2023,2024,2026 | no |
| cryptography-cbmc | val | 3 | 2023,2024,2026 | yes |
| diagnosis | train | 3 | 2022,2025,2026 | yes |
| edge-matching | train | 3 | 2023,2025,2026 | yes |
| ensemble-computation | val | 3 | 2023,2025,2026 | yes |
| fpga-routing | train | 3 | 2023,2025,2026 | yes |
| generic-csp | train | 3 | 2023,2025,2026 | yes |
| heule-folkman | train | 3 | 2024 | yes |
| heule-nol | train | 3 | 2024 | yes |
| hgen | train | 3 | 2022,2023,2024 | yes |
| md5-equivalence-checking | test | 3 | 2025,2026 | no |
| oddball-weighing | test | 3 | 2025,2026 | yes |
| p-center | train | 3 | 2025,2026 | yes |
| prime-factoring | train | 3 | 2022,2023,2026 | yes |
| profitable-robust-production | train | 3 | 2023 | yes |
| puzzle | train | 3 | 2022,2024,2025 | yes |
| quantum-kochen-specker | val | 3 | 2024 | yes |
| ramsey | train | 3 | 2024,2025 | yes |
| random-csp | train | 3 | 2022,2024,2025 | yes |
| rbsat | train | 3 | 2023,2024,2025 | yes |
| rooks | train | 3 | 2023,2024,2025 | yes |
| sgen | val | 3 | 2023,2024,2026 | yes |
| station-repacking | train | 3 | 2025,2026 | yes |
| unknown-author-zhou | val | 3 | 2022,2023,2024 | yes |
| algebra | test | 2 | 2022 | yes |
| allowable-seqence | train | 2 | 2026 | yes |
| antibandwidth | train | 2 | 2022,2026 | yes |
| automata-synchronization | train | 2 | 2024,2026 | yes |
| battleship | train | 2 | 2024,2025 | yes |
| bioinformatics | train | 2 | 2022,2026 | yes |
| cardinality-constraints | train | 2 | 2022,2026 | yes |
| clique-formulas | val | 2 | 2024,2026 | yes |
| core-based-generator | test | 2 | 2022,2025 | no |
| count | train | 2 | 2026 | yes |
| cyclic-anti-bandwidth | test | 2 | 2026 | yes |
| ecc-equivalence-checking | test | 2 | 2026 | no |
| erdos-discrepancy | train | 2 | 2024,2026 | yes |
| exam-scheduling | train | 2 | 2026 | yes |
| fermat | train | 2 | 2024,2025 | yes |
| graceful-production | test | 2 | 2022,2025 | no |
| gray_codes | train | 2 | 2022,2026 | yes |
| hashtable-safety | test | 2 | 2023 | no |
| knights-problem | train | 2 | 2022,2024 | yes |
| ktf | test | 2 | 2022,2025 | yes |
| lights-out | val | 2 | 2026 | yes |
| linear-equations | train | 2 | 2026 | yes |
| matrix-multiplication | val | 2 | 2023,2026 | yes |
| mechanical-master-key | train | 2 | 2025 | yes |
| modcircuits | train | 2 | 2023,2025 | yes |
| ntil | val | 2 | 2026 | yes |
| or_randxor | train | 2 | 2023,2024 | yes |
| ordering-principle-xor | train | 2 | 2022,2025 | yes |
| pythagorean-triples | train | 2 | 2024,2025 | yes |
| random-modularity | val | 2 | 2024,2025 | yes |
| reg-n | test | 2 | 2023,2024 | yes |
| sliding-puzzle | test | 2 | 2022,2026 | yes |
| sorting-networks | train | 2 | 2025,2026 | yes |
| stable-semantics | train | 2 | 2026 | yes |
| stedman-triples | val | 2 | 2024,2025 | yes |
| subset-cardinality | train | 2 | 2024,2025 | yes |
| sum-of-3-cubes | train | 2 | 2025,2026 | yes |
| syndrome-decoding | train | 2 | 2026 | yes |
| termination-analysis | train | 2 | 2025,2026 | yes |
| test-configuration | val | 2 | 2022,2023 | yes |
| unknown-author-unknown | val | 2 | 2025,2026 | yes |
| xor-shifting | train | 2 | 2026 | yes |
| 01-integer-programming | train | 1 | 2026 | yes |
| 2d-strip-packing | val | 1 | 2026 | yes |
| agile | train | 1 | 2026 | yes |
| at-least-two-sol | train | 1 | 2025 | yes |
| auto-correlation | test | 1 | 2022 | no |
| binary-tree-parity | train | 1 | 2024 | yes |
| boxfolding | val | 1 | 2026 | yes |
| chnl | val | 1 | 2026 | yes |
| circuit-minimization | train | 1 | 2026 | yes |
| clique-width | train | 1 | 2024 | yes |
| clustered-random | train | 1 | 2025 | yes |
| datapath-equivalence-checking | val | 1 | 2026 | yes |
| discrete-logarithm | val | 1 | 2025 | yes |
| edit-distance | test | 1 | 2022 | no |
| equivalence-chain-principle | train | 1 | 2024 | yes |
| fixed-shape-random | train | 1 | 2025 | yes |
| genurq | train | 1 | 2026 | yes |
| grandtour-puzzle | train | 1 | 2025 | yes |
| greentao | test | 1 | 2026 | yes |
| hard-cep | train | 1 | 2026 | yes |
| hidoku | train | 1 | 2025 | yes |
| lam-discrete-geometry | train | 1 | 2026 | yes |
| linvrinv | train | 1 | 2026 | yes |
| long-learned-clauses | val | 1 | 2023 | yes |
| maximum-constraint-partition | val | 1 | 2025 | yes |
| mosoi-289 | train | 1 | 2026 | yes |
| parity-games | train | 1 | 2023 | yes |
| pebbling | train | 1 | 2023 | yes |
| petrinet-concurrency | test | 1 | 2022 | no |
| philips | train | 1 | 2026 | yes |
| popularity-similarity | train | 1 | 2024 | yes |
| product-configuration | val | 1 | 2023 | yes |
| purdom-instances | train | 1 | 2025 | yes |
| rubikcube | test | 1 | 2022 | no |
| st-connectivity-principle | train | 1 | 2024 | yes |
| subsumptiontest | train | 1 | 2023 | yes |
| summle | train | 1 | 2022 | yes |
| tensors | train | 1 | 2022 | yes |
| theorem-proving | train | 1 | 2023 | yes |
| tournament | train | 1 | 2025 | yes |
| trigonometric-functions | train | 1 | 2023 | yes |
| unknown-author-collatz | test | 1 | 2022 | no |
| unknown-author-mayer-eichberger | test | 1 | 2022 | no |
| unknown-author-moon | test | 1 | 2022 | no |
| xor-chain | train | 1 | 2026 | yes |
| xor_op | train | 1 | 2025 | yes |

## 6. 局限

- 代表性指“在可获取、≤1 GB 的主赛道问题中覆盖家族与规模”，不是对全部 SAT 应用或全部比赛题的无偏样本；pooled 结果是设计性抽样的结果，不能直接当作竞赛总体均值。
- test 以第一轮未运行的实例为优先，因而偏向 2022 年与大规模层；只有 44 个 test 实例的家族在第一轮从未被运行，其余 55 个所在家族第一轮出现过（20 个实例本身有第一轮结果）。test 不是完全独立的新盲测。
- 超过 1 GB 的 68 个问题被排除（多为 2022–2024 年的大实例），结论不适用于这一规模层。
