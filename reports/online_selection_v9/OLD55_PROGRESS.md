# 原 55 题（v7 面板）恢复进度

计划：[OLD55_RECOVERY_V9.md](../../docs/OLD55_RECOVERY_V9.md)，在任何恢复运行之前提交（`4b4f10c`）。逐题表由 `scripts/online_selection_v9/old55.py` 生成：[OLD55_PROGRESS_TABLES.md](OLD55_PROGRESS_TABLES.md)。v7 自己的结果文件（`results/completion_v7/`）保持原样不动；合并后的状态写在 `results/online_selection_v9/old55/`。

## 状态（2026-10-24 约 14:30 UTC，运行仍在继续）

| 方法 | v7 结束时 | 现在 | 完整平均 CPU |
|---|---:|---:|---|
| D | 47/55 | 49/55 | null |
| P1_M05_long | 47/55 | 49/55 | null |
| F+ | 30/55 | 34/55 | null |
| F− | 29/55 | 33/55 | null |
| oracle（已确定） | 44/55 | **51/55** | null |

## 两个阶段，均无核时上限

- `old55_r1a`（cpu-208-039）：
  - 8 道 D 未完成题上的 P1_M05_long 长时 wrapper，冻结的 v6 选择器在这 8 题上都选 D，所以它们同时就是 D 的测量。这 8 个运行此刻都已超过 11,100 s，从头重跑，没有拼接 v7 的 12,250 s。
  - 5 道 D 已完成题上的 F+ / F− oracle 臂已全部结束：
    - 3 题 F± 都在 D 的完成时间处停止，记为 `oracle_noncompetitive_bound`，D 即 oracle；
    - `0ef0d91d37`（UNSAT）：F− 1432 s、F+ 2326 s，都快于 D 的 8696 s；
    - `d5b11b0b73`（GBD unknown）：F+ 4585 s、F− 4625 s，快于 D 的 5121 s。
- `old55_r1b`（cpu-207-115）：6 道三个动作都未完成的题上的 F+ / F− 完整运行。
  - `ac3e3bb744`（UNSAT）：F− 1772 s、F+ 3597 s 完成。D 在 v7 中超过 12,243 s 仍未完成，所以 oracle 由 F− 确定。
  - 其余 5 题的 10 个运行此刻都已超过 10,000 s。

**09:20 时的状态**：新确定的 oracle 为 `0ef0d91d37`、`d5b11b0b73`、`ac3e3bb744`，以及 F± 都停在 D 时间处的 3 题；当时仍待定的 5 题是 `07df5e6f67`、`4af0fbe308`、`aa6e6f6771`、`c7bf3517f4`（GBD unknown）和 `7ff8c9781b`（UNSAT），它们的三个动作都在运行。

## 14:30 UTC 之前的新完成

- `c7bf3517f4`（GBD unknown，此前没有任何求解器解出）：UNSAT。D（P1_M05_long 正式求解）12,531 s，F− 12,233 s，F+ 12,395 s，oracle 由此确定。
- `ac3e3bb744`（UNSAT）：D 24,106 s。
- `7ff8c9781b`（UNSAT）：D 27,170 s 已结束，正在独立检查。

此刻仍在运行：`07df5e6f67`、`4af0fbe308`、`aa6e6f6771`（GBD unknown）以及两道 sat-x 题上的 D / P1_M05_long（各约 29,500 s），还有 4 题的 F± 运行（约 28,900 s）。

## 平台

- 证明写在节点本地盘，两节点各剩 5.3 / 6.9 TB。
- 剩余低于 400 GB 时，控制器会停止证明最大的运行，并记为平台删失，没有触发过。
- 没有发生平台中断。

## 结论

- 原 55 题的完整均值仍然未知（null），不能据新面板的结果推断。
- 运行会继续。完成或发生平台中断时，按 OLD55_RECOVERY_V9 第 4 节的采用顺序更新本页。
