# 2022 Anniversary 基线：集群运行 v1

日期：2026-11-08。代码基于合作者分支 `codex/anniversary2022-baseline-2026-11-07`（d306829），只做下面列出的集群适配。

## 运行定义（不变）

- **题目**：按官方三赛道全部未解规则筛选后的 4719 题（[名单](../../configs/anniversary2022_baseline/manifest.official-solvable.v1.csv)，SHA `722bb437…`，筛选 receipt SHA `33f8fd43…`），不按我们的结果再删题。
- **配置**：D / F+ / F−，seed 0，共 14157 次运行。
- **计时与验证**：
  - 每次 600 CPU s，按 solver 进程 CPU 计时；
  - 1800 s wall 只作看门狗；
  - 运行时生成二进制 LRAT；
  - SAT 检查本次 model，UNSAT 用 lrat-trim 独立检查本次证明；
  - 只有验证通过、且 CPU ≤ 600 s 才计为解出。
- **二进制**：
  - CaDiCaL 3.0.1，固定 commit `c607304`，静态编译，SHA `250220f9…`；
  - lrat-trim `b30f400`，SHA `4094f88d…`。

## 集群适配（相对 d306829 的全部改动）

| 文件 | 改动 | 原因 |
|---|---|---|
| `common.py` | `validate_spec` 接受可选的 `shard` 与绝对路径 `proof_dir`；新增 `shard_rows` | 原 runner 每个 owner 最多 8 个 CPU token，单 owner 跑完需约两周。 |
| `run_baselines.py` | `start --shard i/n`：整个 4719 名单与 receipt 先完整校验，再只领取 `位置 % n == i` 的题。shard 写入该 root 的冻结 spec，resume 时读回。shard 的进度分母为本 shard 题数。磁盘准入在 `proof_dir` 上检查证明预留。session 记录增加主机名与 CPU 列表。 | 多节点并行；证明放节点本地盘，与 v11 一致。 |
| `run_one.py` | 证明写到 `proof_dir/<run_id>.lrat`，不再放在运行目录里 | 避免大量证明写入共享 /mnt/data。 |
| `collect_results.py` | `--root` 可接全部 shard root：检查各 shard 冻结 spec（除 shard 与 proof_dir 外）和测量身份相同、shard 恰好划分全集，再合并为一个 snapshot。单 root 的行为不变。 | 合并结果 |
| `common.py` `parse_stats` | **修正**：只读顶层统计行 `c conflicts:`。原正则 `^c\s+conflicts:` 也匹配 CaDiCaL 3.0.1 随后打印的缩进子项 `c   conflicts: 0 … per warmup`，并取最后一个匹配。 | 第一次启动（见下文）的 728 次运行中，有 667 次的 conflicts（多数为 0）与日志顶层值不符。 |
| `run_one.py` `limited_process` | **修正**：`prlimit --cpu` 后备上限由 截止+2 / +4 s 改为 ⌈1.02·截止⌉+5 / +10 s（600 s → 617 / 622 s）。 | 内核按 tick 采样的 CPU 时钟可能比 /proc 与 rusage 快约 0.4%。第一次启动中有 4 次运行在 SIGTERM 之前或期间被 SIGXCPU 杀死，没有统计输出；其中 2 次在 /proc 只显示 599.8 s 时被杀，记为 ERROR（无效）。 |
| `stage_inputs.py`、`run_baselines.py` | 输入 CNF 缓存放节点本地盘（spec `cache_dir`），receipt 仍在共享运行目录。resume 时，若有待跑任务的输入在本节点没有缓存文件，就重新下载并按原 SHA 核对。 | 共享 /mnt/data 的空闲空间在几分钟内从 1.7 TB 降到 89–200 GB（他人写入）。 |
| `run_baselines.py` | 共享运行目录空间低于 `root_reserve_bytes`（20 GiB）时只暂停领取新任务，owner 保持运行并重试，不再退出。 | 同上 |
| `run_baselines.py` | `resume --recover-incomplete`：随作业中断的 attempt 移到 `aborted_attempts/<run_id>.<时间>`（不覆盖、不删除），对应任务重新排队；暂存失败的输入重新排队；每次恢复写一份 `recoveries/<时间>.json`。不带该参数的 resume 行为不变，中断的 attempt 仍为 BLOCKED。 | 原 README 列为全量启动前缺的第 3 项 |
| `test_contracts.py` | 三个新测试：shard 划分不重不漏；非法 shard 或相对 `proof_dir` 被拒绝；缩进子统计不当作顶层计数 | |
| `spec.cluster-v1.json` | `FROZEN` 执行 spec | 原 `spec.draft.json` 按设计不可启动 |
| `tools/anni2022_cluster.sh` | Slurm 启动（start）、接上（resume）、恢复（recover）、状态与合并 | |
| `tools/anni2022_recovery_check.py` | 用真实 solver 的功能检查：两个 shard、节点本地缓存与证明；运行中杀掉 owner 与 solver；普通 resume 必须保留 BLOCKED，`--recover-incomplete` 恢复后完整；两个 shard 合并完整；缺一个 shard 的合并被拒绝。结果在 `anni2022_baseline/recovery_check_v1/RECOVERY_CHECK.json`：PASS。 | |

**测量定义没有改动**：
- 求解命令、600 CPU s 截止与 SIGTERM 停止不变；
- 验证、状态判定、PAR2 定义与结果字段不变。

两处修正只纠正统计解析和后备上限的余量。

## 资源设置

- **分片与分配**：24 个 shard，每个是一个 Slurm 作业：cpu-mid，20 个逻辑 CPU（10 个整核），200G 内存，`--no-requeue`。
- **CPU 绑核**：8 个 CPU token 取亲和列表前 8 个，即 8 个不同物理核各一个线程，同核的另一线程空闲。
- **单进程限制**：
  - 地址空间 32 GiB（solver 与 checker 相同）；
  - 文件大小 32 GiB；
  - checker 上限 1800 CPU s / 2400 s wall。
- **输入**：每个 shard 1 个下载线程，预取 12 题，缓存在节点本地 `/var/tmp/anni2022-cluster-cache/shard-XXX-of-024/`；三次运行都有效完成后删除。
- **证明**：写到节点本地 NVMe `/var/tmp/anni2022-cluster-v1/shard-XXX-of-024/`，有效结果后删除。容器的本地盘在作业结束时清空，所以验证失败的证明不会保留；作业结束前日志会列出它们。
- **运行目录**：`/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase/anni2022_baseline/cluster_v3/shard-XXX/`。

## 运行

```bash
tools/anni2022_cluster.sh start            # 提交 24 个 shard
tools/anni2022_cluster.sh status           # 各 shard 进度
tools/anni2022_cluster.sh resume 7         # 某 shard 作业中断后重新接上（已完成记录不重跑）
tools/anni2022_cluster.sh recover 7        # 同上，并把被中断的 attempt 移开、重新排队
tools/anni2022_cluster.sh collect SNAPSHOT # 在容器内合并全部 shard
```

## 第一次启动（已中止）

- 2026-11-08 19:30 UTC 启动，24 个 shard，运行目录 `cluster_v1`。
- 约 13 分钟后发现上面两个问题，19:43 取消全部作业。当时完成 728 次运行；答案验证全部正常，但统计解析和后备上限有问题。
- 这些记录保留在 `anni2022_baseline/cluster_v1_aborted/`，不并入正式结果。
- 两处修正后，单元测试 11/11 通过，集群上的 qualification 重新通过，conflicts 非零且与日志一致。

## 第二次启动（已中止）

- 21:47 UTC 在 `cluster_v2` 启动。
- 两分钟内 /mnt/data 空闲空间在 91–172 GB 间波动（他人写入）。输入缓存当时还在共享盘上，staging 连续两次低于 64 GiB 保留量就会把输入永久标为 BLOCKED，所以立即取消。
- 当时完成 92 次运行，保留在 `cluster_v2_aborted/`，不并入结果。
- 随后加入节点本地输入缓存、低空间暂停与显式恢复，并用功能检查验证。

## 正式运行（cluster_v3）

从新的运行目录重新启动全部 14157 次运行。
