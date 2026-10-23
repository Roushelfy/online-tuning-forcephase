# Goal v5 的算力账本

由 `scripts/observations_v5/compute_ledger.py` 生成；只计 v5 新产生的 CPU（单核 CPU 时间之和），复用的 v4/第一轮运行不计。

| 项 | 批次 | 记录数 | 求解 / 工具 CPU 核时 | 检查器 CPU 核时 |
|---|---|---:|---:|---:|
| arm | collection | 4586 | 0.60 | 0.00 |
| arm | superseded_first_collection | 4586 | 0.60 | 0.00 |
| eqv | collection | 294 | 1.42 | 0.00 |
| eqv | first_gate_runner_version | 288 | 1.28 | 0.00 |
| eqv | superseded_first_collection | 6 | 0.15 | 0.00 |
| obs | collection | 593 | 0.10 | 0.00 |
| obs | superseded_first_collection | 593 | 0.10 | 0.00 |
| wrap (observe-only, kappa) | collection | 1056 | 0.22 | 0.00 |
| wrap (observe-only, kappa) | superseded_first_collection | 1056 | 0.22 | 0.00 |
| wrap (real) | confirm | 156 | 9.07 | 0.06 |
| wrap (real) | deploy_dev | 802 | 45.99 | 0.13 |
| fprun 固定运行 | v5_seed1 | 147 | 5.26 | 0.08 |
| fprun 固定运行 | v5_confirm_fixed | 234 | 14.02 | 0.10 |
| 工程 smoke（2 个 dev 实例，容器内） | v5_smoke | 22 | 0.00 | 0.00 |
| 建模、筛查与报告（分析节点，估计上限） | — | — | 3.00 | — |
| **合计** | | | **82.02** | **0.37** | 

- v5 合计 82.38 核时；加上 v4 的 39.90，v4 之后累计 122.28 核时（上限 200）。
- `superseded_first_collection` 是协议偏离 1–2 之前的第一次采集，已作废但照常计费。
- 主机上的工具 smoke（11 个实例的 obsprofile 和 2 万冲突等价检查，几分钟）未逐项计量，包含在分析估计上限中。
- 独占节点的墙钟占用（每节点 48 个并发）未计入；上表是 CPU 时间。
