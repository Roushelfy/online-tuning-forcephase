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
- **内核层面的上限（2026-10-25 补充）**：除控制器在 cap_cpu 处停止外，固定运行在启动时设 RLIMIT_CPU = 3600 s；三个 wrapper（v7 `wrapper_long.py`、v8 `wrapper.py`、v9 `presolve.py`）在 exec 正式求解之前，把 RLIMIT_CPU 设为“3600 − 已等待的观察 / probe 子进程 CPU”。这样即使控制器轮询滞后，整棵进程树也在上限处被 SIGXCPU 停止。控制器把这种退出同样记为 `policy_timeout`。上限值由控制器通过环境变量 `FP_RUN_CPU_LIMIT` 传给 wrapper。
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

## 5. 执行清单完成情况（对照 [RESOURCE_POLICY.md](RESOURCE_POLICY.md)“执行 agent 下一步必须先”）

| 步骤 | 状态 | 依据 |
|---|---|---|
| 1. 盘点作业与验证状态，安全停止达到截止且未求解的作业，提交实际停止时间与逐题清单 | 完成 | 第 1–2 节；停止日志 `$FP_DATA/logs/policy_stops/2026-10-25T06:10*`；逐题清单 [policy_stops.json](../results/policy_stops.json)，共 13 个，实际停止 CPU 与时间都在其中；停止时没有正在验证的任务；三个作业随后结束，目前没有运行中的作业 |
| 2. 接入 v7 / v8 / v9 控制器及 wrapper：累计不限、统一进程树计时、`policy_timeout` 状态、新的运行 id | 完成 | `scripts/run_timeout_policy.py`；`completion_v7/longrun.py`、`stratified_v8/runner.py`、`online_selection_v9/runner.py`：在 cap 处停止，并加内核 RLIMIT_CPU；wrapper `completion_v7/wrapper_long.py`、`stratified_v8/wrapper.py`、`online_selection_v9/presolve.py`：exec 前按剩余预算设 RLIMIT_CPU；运行 id 含 `run_policy_id` |
| 3. 用可控子进程验证固定臂、probe 后重启的总计时、已出答案的独立验证与历史记录兼容，再发布运行配置 | 完成 | `tests/test_run_timeout_policy.py`：v7、v8、v9 控制器的真实子进程、wrapper 自身限时、checkmodel 验证、旧运行 id 不变；`tests/test_resource_policy.py` 已更新；26 项全部通过；运行配置已发布在 [run_timeout_policy.json](../configs/run_timeout_policy.json) 的 `execution_status` 与 `enforcement` |
| 4. 重建旧 55 题与外推进度报告，分开呈现旧无限运行结果与新 3600 s 评价，只重建轨迹充分的记录 | 完成 | [TIMEOUT_3600.md](../reports/online_selection_v9/TIMEOUT_3600.md)、[TIMEOUT_3600_TABLES.md](../reports/online_selection_v9/TIMEOUT_3600_TABLES.md)、[OLD55_PROGRESS.md](../reports/online_selection_v9/OLD55_PROGRESS.md)、[VALIDATION.md](../reports/online_selection_v9/VALIDATION.md) 外推一节；只有 300 s 下界的历史记录标为不可重建 |
| 5. 后续研究以秒级到分钟级的多规模面板为主，极难比赛题在统一截止下作压力测试 | 已写入方向 | TIMEOUT_3600.md 第 4 节；之后的新面板在冻结前用独立试采样选择能在 3600 s 内覆盖的规模。这一条不是本次执行要立即完成的实验 |

原 55 题的完整均值仍为 null，这是如实记录的状态，不是遗漏。按政策，不为超时题放宽上限或重跑。
