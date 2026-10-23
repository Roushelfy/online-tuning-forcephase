# Goal v6 的算力账本

由 `scripts/stable_selection_v6/compute_ledger.py` 生成；只计 v6 新产生的 CPU，复用的运行列出但不计。

| 项 | 记录数 | 求解 / 工具 CPU 核时 | 检查器 CPU 核时 | 备注 |
|---|---:|---:|---:|---|
| fprun 固定运行 v6_seed1 | 69 | 3.17 | 0.00 | 复用 21 次（不计） |
| fprun 固定运行 v6_seed2 | 90 | 4.10 | 0.00 | 复用 0 次（不计） |
| fprun 固定运行 v6_validate_fixed | 165 | 8.71 | 0.07 | 复用 0 次（不计） |
| SATzilla 2024 subset | 521 | 0.13 | 0.00 | |
| obsprofile6 | 461 | 0.04 | 0.00 | |
| obsprofile6 (before the cap-check fix, superseded) | 72 | 0.01 | 0.00 | |
| v5 local-search control (eng12) | 36 | 0.00 | 0.00 | |
| wrapper (R3 check30) | 30 | 1.33 | 0.01 | |
| wrapper (validation) | 55 | 2.78 | 0.02 | |
| SATzilla 构建与测试、主机 smoke、建模与报告（估计上限） | — | 2.00 | — | |
| **合计** | | **22.26** | **0.11** | |

- v6 合计 22.37 核时（v6 上限 60）；v6 之前累计 122.28，现累计 144.65（上限 200）。
- 独占节点的墙钟占用未计入；上表是 CPU 时间。
