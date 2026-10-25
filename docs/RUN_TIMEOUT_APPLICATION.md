# 应用 3600 CPU 秒单次超时（[资源政策](RESOURCE_POLICY.md)，[run_timeout_policy.json](../configs/run_timeout_policy.json)）

日期：2026-10-25（UTC）。本页在停止任何运行之前提交，记录对已在运行作业的处理办法、控制器接入，以及历史记录在新政策下的解读。

## 1. 盘点（2026-10-25 06:09 UTC，`scripts/policy_stop.py --dry-run`）

| Slurm 作业 | 节点 | 阶段 | 运行中的求解进程 | 已用 CPU |
|---|---|---|---|---|
| 744795 | cpu-208-039 | v7 `old55_r1a` | 5 个：P1_M05_long 长时 wrapper，正式求解即 D；实例 07df、0a8a、4af0、aa6e、af83 | 约 84,900–86,000 s |
| 744796 | cpu-207-115 | v7 `old55_r1b` | 7 个：F+ / F−，实例 07df、4af0、7ff8、aa6e | 约 84,600–85,300 s |
| 744930 | cpu-207-115 | v9 `extrap` | 1 个：`v9x-assign2-X2-03` 的 F− | 约 43,100 s |

- 没有正在运行的答案检查器（lrat-trim / checkmodel），没有“已解出、等待验证”的任务需要保留。
- 13 个求解进程都远超 3600 s，都未解出。
- `extrap` 作业在 2026-10-24 约 18:05 UTC 被 Slurm 重新排队（Restarts = 1）：
  - 当时尚未结束的 2 个运行（`v9x-assign2-X2-02` 的 F+ 与 `v9x-assign2-X2-03` 的 F−）在原节点 cpu-207-123 上被杀死，没有写出记录。
  - 新分配从头重跑了这 2 个；前者已在 30,128 s 完成，后者即上表这个运行。
  - 被杀死的部分约用了 55,000 CPU 秒（按 10-24 12:26 的心跳加墙钟估计，上限），在账本中作为平台中断单列。

## 2. 对运行中作业的处理

- **停止**：在各作业的节点上运行 `scripts/policy_stop.py`，向这 13 个 cadical 进程发 SIGTERM，与控制器自身的停止相同。
  - 控制器随后照常写出记录：退出码 −15、实际 CPU、gzip 的 stdout / stderr / 遥测。未解运行的部分证明没有用处，随工作目录删除。
  - 停止清单（pid、命令、CPU、时间）记在 `$FP_DATA/logs/policy_stops/`。
- **记录解读**：旧控制器把这些外部停止记为 `error`，因为它不认识新政策；记录文件本身不修改。`results/policy_stops.json` 按记录 id 列出这些运行，归一化时它们一律记为 `policy_timeout`，实际 CPU 照记（不改写成 3600 s）。
- 这些运行都已从头运行、没有续算状态。按政策，不再为超时题放宽上限、重启或换 seed。

## 3. 控制器与 wrapper 接入（之后的新运行）

- **新模块**：`scripts/run_timeout_policy.py` 读取 `configs/run_timeout_policy.json`，对每个普通作业设置 `cap_cpu = 3600`、`cap_kind = policy_timeout`。
  - 显式的算法窗口（oracle_noncompetitive_bound）如果更短，保留其值。
  - 运行 id 中加入新的 `run_policy_id`，所以旧记录既不会被当作已完成而跳过，也不会被覆盖。
- **接入的控制器**：v7 `longrun.py`、v8 `runner.py`、v9 `runner.py`。
  - CPU 达到 3600 s 即 SIGTERM（60 s 后 SIGKILL）。若随后仍正常给出答案，照常检查；否则记为 `policy_timeout`。
  - 计时对象是整棵进程树：wrapper 的 probe 是被等待的子进程，exec 后的正式求解是同一进程，所以“观察 + 重启 + 正式求解”合计受同一个 3600 s 限制，不是 probe 之后再给 3600 s。
  - 检查器的 CPU 另记。
- **测试**：用受控子进程（不调用 SAT 求解器）检查：
  - 固定臂到 3600 s 时停止；
  - wrapper 的 probe 与重启合计计时；
  - 已给出答案的运行照常检查；
  - 旧记录的兼容。

## 4. 历史记录在 3600 s 视图下的解读（只做能确定的部分）

- **固定臂**：完成且 CPU ≤ 3600 s 的仍算已解；完成但 CPU > 3600 s、或停止 / 删失时实际 CPU ≥ 3600 s 的，在 3600 s 视图下算超时。300 s 删失之类不到 3600 s 的历史下界无法判断，标为“不可重建”。
- **wrapper**（P1_M05_long、v9 的 W_ref）：用整棵进程树的 CPU 做同样判断。它们的 CPU 从启动连续累计，所以 3600 s 时是否已解出是确定的。
- **报告**：旧的无上限结果（历史）与新的 3600 s 视图分开呈现。3600 s 视图先给出：
  - 已解数；
  - SAT / UNSAT 分层；
  - 解题数随 CPU 时间的曲线；
  - 超时清单。

  共同已解子集上的配对均值只作次要描述，并标明筛选偏差；不自动使用 PAR2。
- **v9 主比较**：270 题按原冻结协议与数字不变。若给出它的 3600 s 视图，标明是事后敏感性分析。
