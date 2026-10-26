# v10 算力账本

只记账，不设额度（[resource_policy.json](../../configs/resource_policy.json)）。每个运行单次上限 3600 CPU s（整棵进程树）。
由 `scripts/cross_scale_v10/ledger.py` 从全部 v10 记录生成，包括冒烟测试、失败与重跑。

| 阶段 | 记录数 | 求解 / wrapper CPU（核时） | 检查器 CPU（核时） | 状态 | 仍在运行（核时） | 平台中断损失，无记录（核时，上限估计） |
|---|---:|---:|---:|---|---:|---:|
| `confirm` | 1350 | 8.930 | 0.1706 | solved 1350 | 0.000 | 0.000 |
| `deploy_dev` | 540 | 2.478 | 0.0523 | solved 540 | 0.000 | 0.000 |
| `external` | 590 | 28.848 | 0.0063 | policy_timeout 23, policy_timeout* 5, solved 562 | 0.000 | 0.000 |
| `extrap` | 450 | 27.978 | 0.3069 | policy_timeout 2, policy_timeout* 1, solved 447 | 0.000 | 0.000 |
| `measure_dev` | 270 | 0.576 | 0.0000 | measured 270 | 0.000 | 0.000 |
| `pilot` | 72 | 1.514 | 0.0260 | solved 72 | 0.000 | 0.000 |
| `robust_dev` | 322 | 1.514 | 0.0293 | solved 322 | 0.000 | 0.199 |
| `robust_dev_r2` | 2 | 0.361 | 0.0071 | solved 2 | 0.000 | 0.000 |
| `s1_dev` | 810 | 4.755 | 0.0931 | solved 810 | 0.000 | 0.000 |
| `smoke_v10` | 9 | 0.010 | 0.0001 | measured 3, solved 6 | 0.000 | 0.000 |
| `stress_old55` | 110 | 40.715 | 0.1692 | policy_timeout 27, policy_timeout* 4, solved 79 | 0.000 | 0.000 |
| `stress_old55_fixed` | 29 | 17.782 | 0.1063 | policy_timeout 10, policy_timeout* 2, solved 17 | 0.000 | 0.000 |
| **合计** | | **135.462** | **0.9672** | | 0.000 | 0.199 |

- `policy_timeout*`：被内核 CPU 上限（SIGXCPU）在 3600 s 处停止、原记为 `error` 的运行，见 `status_corrections.json` 与协议第 12 节。
- 平台中断损失：作业被 Slurm 抢占时正在运行、没有写出记录的部分，按最后一次心跳计；`robust_dev` 的 2 个运行已在 `robust_dev_r2` 补跑。
- 实例生成 CPU：0.0405 核时（试采样与正式清单）。
- v10 合计（求解 + 检查 + 生成 + 平台中断损失）：**136.668 核时**。
