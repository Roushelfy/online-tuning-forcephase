# v7 完成时间表（由 `scripts/completion_v7/report.py` 生成）

## 1. 固定面板与完成情况

固定清单 55 题（`configs/completion_v7/panel.txt`）。只有全部 55 题都有独立验证通过的完成时间，完整均值才可计算。

| 方法 | 完成数 | 完整平均 CPU（秒） | 总 CPU | 相对 D | 已执行 CPU 之和（完成时间 + 未完成题的实际下界，秒） |
|---|---:|---|---|---|---:|
| D | 47/55 | 未知（null） | 未知 | 未计算 | 145367（下界） |
| F+ | 30/55 | 未知（null） | 未知 | 未计算 | 23201（下界） |
| F− | 29/55 | 未知（null） | 未知 | 未计算 | 22613（下界） |
| P1_M05_long | 47/55 | 未知（null） | 未知 | 未计算 | 145150（下界） |
| oracle（事后最快，不可部署） | 44/55 已确定 | 未知（null） | | | |

主比较是否完整：**否**。未完成时，均值、总量与收益都是 null；最后一列只是“已经实际执行的 CPU”，对总耗时是**下界**，不是完整总耗时。

## 2. 未完成实例（至少一个方法尚无完成时间）

数值为经验证的完成 CPU 秒；`≥ x` 为实际执行到 x 秒仍未完成的下界（来源见 `results/completion_v7/per_instance.csv`）。

| 实例 | 家族 | 规模 | GBD 已知结果 | D | F+ | F− | P1_M05_long | oracle |
|---|---|---|---|---:|---:|---:|---:|---:|
| 07df5e6f67 | cyclic-anti-bandwidth | large | unknown | ≥ 12296 | ≥ 300 | ≥ 300 | ≥ 12297 | 待定（D/Fp/Fm） |
| 090eefb9bc | profitable-robust-production | large | sat | 793.7 | ≥ 796 | ≥ 796 | 795.6 | 793.7 |
| 0a8a4c28d2 | sat-x | large | sat | ≥ 12278 | ≥ 300 | 43.9 | ≥ 12278 | 43.9 |
| 0ef0d91d37 | trigonometric-functions | large | unsat | 8696.4 | ≥ 300 | ≥ 300 | 8696.8 | 待定（Fp/Fm） |
| 1afa2d7a3d | scheduling | large | sat | 17.6 | ≥ 300 | 9.0 | 15.4 | 9.0 |
| 1b88068128 | oddball-weighing | large | sat | 137.0 | ≥ 300 | ≥ 300 | 136.3 | 137.0 |
| 25cc054738 | software-verification | large | unsat | 1124.4 | ≥ 1128 | ≥ 1126 | 1125.9 | 1124.4 |
| 2e05884137 | planning | large | sat | 152.8 | 59.9 | ≥ 301 | 176.4 | 59.9 |
| 3b0eeddcab | allowable-seqence | large | sat | 3807.7 | ≥ 300 | ≥ 301 | 3809.2 | 待定（Fp/Fm） |
| 4af0fbe308 | coloring | mid | unknown | ≥ 12259 | ≥ 300 | ≥ 300 | ≥ 12259 | 待定（D/Fp/Fm） |
| 511a2d8166 | random-circuits | large | sat | 653.0 | ≥ 656 | ≥ 654 | 653.5 | 653.0 |
| 5ceb95f596 | hardware | large | sat | 634.9 | 542.4 | ≥ 637 | 635.5 | 542.4 |
| 6543793076 | risc-instruction-removal | large | unsat | 1091.8 | ≥ 1093 | 760.4 | 1093.9 | 760.4 |
| 69e34d0f49 | planning | large | unsat | 1074.0 | 838.2 | ≥ 1076 | 1075.5 | 838.2 |
| 761651d4b6 | quantum-kochen-specker | mid | unsat | 437.5 | 216.4 | ≥ 300 | 236.4 | 216.4 |
| 7ff8c9781b | scheduling | small | unsat | ≥ 12253 | ≥ 300 | ≥ 300 | ≥ 12253 | 待定（D/Fp/Fm） |
| 8cfc8e99d3 | trigonometric-functions | large | unsat | 4486.3 | ≥ 300 | ≥ 300 | 4486.9 | 待定（Fp/Fm） |
| 9541d12f3e | cyclic-anti-bandwidth | large | sat | 1933.2 | ≥ 1936 | ≥ 1935 | 1933.9 | 1933.2 |
| 98c6da979a | profitable-robust-production | large | sat | 3158.3 | ≥ 3161 | 3066.0 | 3161.5 | 3066.0 |
| aa6e6f6771 | independent-set | large | unknown | ≥ 12222 | ≥ 300 | ≥ 300 | ≥ 12222 | 待定（D/Fp/Fm） |
| ac3e3bb744 | 2d-strip-packing | large | unsat | ≥ 12243 | ≥ 300 | ≥ 300 | ≥ 12243 | 待定（D/Fp/Fm） |
| af834fd3ce | sat-x | large | sat | ≥ 12235 | ≥ 300 | 50.1 | ≥ 12235 | 50.1 |
| b64f7d56f1 | tree-decomposition | large | sat | 51.8 | ≥ 301 | ≥ 300 | 50.0 | 51.8 |
| b88d206fb3 | maxsat-optimum | mid | sat | 1002.2 | 983.9 | ≥ 1005 | 1002.3 | 983.9 |
| c7bf3517f4 | risc-instruction-removal | large | unknown | ≥ 12237 | ≥ 301 | ≥ 303 | ≥ 12241 | 待定（D/Fp/Fm） |
| c8cde50f32 | belpyramid-puzzle | large | sat | 631.6 | ≥ 633 | ≥ 634 | 632.0 | 631.6 |
| ca6db14aaa | graph-isomorphism | large | unsat | 746.2 | 179.7 | ≥ 301 | 747.1 | 179.7 |
| d5b11b0b73 | risc-instruction-removal | large | unknown | 5121.3 | ≥ 301 | ≥ 301 | 5123.4 | 待定（Fp/Fm） |
| dbbcaa7797 | cyclic-anti-bandwidth | large | unsat | 5057.5 | ≥ 300 | ≥ 300 | 5058.0 | 待定（Fp/Fm） |
| e2deb375e5 | random-circuits | large | sat | 183.0 | ≥ 300 | 207.0 | 162.8 | 183.0 |
| e8abb9c83e | software-verification | large | unsat | 169.5 | 280.6 | ≥ 300 | 173.7 | 169.5 |
| ed410c758e | independent-set-reconfiguration | mid | sat | 1119.6 | ≥ 1122 | ≥ 1122 | 1119.7 | 1119.6 |

## 3. 补充：P1_M05_long 与 D 总 CPU 之差的可证明区间（不是主指标）

在 P1_M05_long 选 D 的题上，D 的测量取自同一次运行的正式求解，所以“P1 − D”恰好等于观察与 wrapper 的 CPU，即使该运行尚未完成也已知。两个方法都已完成的题上差值精确；其余题只能给出区间。

- 差值精确的题：55；只能给出区间的题：0（无）。
- 总差值 Σ(P1 − D) ∈ [-217.2, -217.2] 秒（负 = P1_M05_long 更省时）。
- D 总 CPU 的实际下界为 145367 秒，所以若两方法都在同一次运行中完成，P1_M05_long 相对 D 的收益介于 0 与 +0.149% 之间（收益 = −Σ(P1 − D) / D 总 CPU，分母只会更大）。这只是界，不是主指标；主指标仍为 null。

## 4. 算力

见 [COMPUTE.md](../../results/completion_v7/COMPUTE.md)：v7 合计 51.24 核时，累计 195.89 / 200。

