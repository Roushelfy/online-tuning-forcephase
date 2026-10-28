# v11 算力账本

只记账，不设额度（[resource_policy.json](../../configs/resource_policy.json)）。每个运行单次上限 3600 CPU s（整棵进程树）。
由 `scripts/broad_scope_v11/ledger.py` 从全部 v11 记录生成，包括探索、pilot、失败与重跑。

| 阶段 | 记录数 | 求解 / wrapper CPU（核时） | 检查器 CPU（核时） | 状态 | 仍在运行（核时） | 平台中断损失，无记录（核时，上限估计） |
|---|---:|---:|---:|---|---:|---:|
| `confirm` | 1200 | 203.233 | 0.2848 | policy_timeout 157, solved 1043 | 0.000 | 0.000 |
| `deploy_dev` | 240 | 15.018 | 0.0436 | policy_timeout 10, solved 230 | 0.000 | 0.000 |
| `disc_dev` | 1584 | 298.488 | 0.3434 | policy_timeout 233, solved 1351 | 0.000 | 54.208 |
| `encoding` | 360 | 93.418 | 0.0413 | policy_timeout 75, solved 285 | 0.000 | 0.000 |
| `explore` | 112 | 0.653 | 0.0114 | solved 112 | 0.000 | 0.000 |
| `explore_r2` | 24 | 0.000 | 0.0001 | solved 24 | 0.000 | 0.000 |
| `explore_r3` | 24 | 0.001 | 0.0001 | solved 24 | 0.000 | 0.000 |
| `explore_r4` | 18 | 1.578 | 0.0055 | policy_timeout 1, solved 17 | 0.000 | 0.000 |
| `measure_pool` | 528 | 0.391 | 0.0000 | measured 528 | 0.000 | 0.000 |
| `pilot` | 84 | 4.660 | 0.0187 | policy_timeout 3, solved 81 | 0.000 | 0.000 |
| `pilot_jssp` | 12 | 0.054 | 0.0008 | solved 12 | 0.000 | 0.000 |
| `public` | 600 | 240.283 | 0.9640 | policy_timeout 204, solved 396 | 0.000 | 0.000 |
| `public_pilot` | 40 | 14.888 | 0.1408 | policy_timeout 11, solved 29 | 0.000 | 0.000 |
| `seeds` | 144 | 29.139 | 0.0125 | policy_timeout 23, solved 121 | 0.000 | 0.000 |
| **合计** | | **901.802** | **1.8668** | | 0.000 | 54.208 |

- `policy_timeout*`：被内核 CPU 上限（SIGXCPU）在 3600 s 处停止、记为 `error` 的运行（v11 runner 已按 v10 修正直接记为 `policy_timeout`，此行只作保险）。
- 平台中断损失：作业被 Slurm 中断时正在运行、没有写出记录的部分，按最后一次心跳计。本轮唯一一次是 `disc_dev` 改为三节点并行时主动取消的单节点作业 757707（协议第 12 节第 7 条），92 个在跑的运行（54.2 核时）由新 runner 从头重跑。
- 不在表内的少量开销：语义检查、生成器测试、复现脚本与分析脚本（各为几分钟级 CPU）。
- 实例生成 CPU：0.4914 核时（试采样与正式清单）。
- v11 合计（求解 + 检查 + 生成 + 平台中断损失）：**958.368 核时**。
