# v11 来源登记与曝光审计（S0）

日期：2026-10-27。本审计在任何 v11 求解之前提交。协议见 [BROAD_SCOPE_PROTOCOL_V11.md](../../docs/BROAD_SCOPE_PROTOCOL_V11.md)。

## 1. 生成器来源与可用性

所有生成器都已在本仓库内实现，并通过极小实例与穷举的对照检验（[tests/test_broad_scope_v11_gen.py](../../tests/test_broad_scope_v11_gen.py)）。没有使用任何未经核实的外部下载或假定存在的编码工具。

| 家族 | 实现 | 依赖（版本固定在 [gen-requirements.txt](../../configs/stratified_v8/gen-requirements.txt)，venv `online-tuning-forcephase-v8gen`） | 许可 |
|---|---|---|---|
| rand3 | v9 `generate.py`，CNFgen `randkcnf` | cnfgen 0.9.6 | GPL-3.0（CNFgen） |
| col3 direct | v9 `generate.py`，CNFgen `kcolor` | cnfgen 0.9.6 | GPL-3.0 |
| col3 log | `families.col3_log`，本仓库 | — | 本仓库 |
| assign2 | v9 `generate.py`，结构 F | python-sat 1.9.dev15 `CardEnc` seqcounter | MIT（PySAT） |
| vcover | `families.vcover`，本仓库 | PySAT `CardEnc`（seqcounter / totalizer） | MIT |
| jssp（order / time） | `families.jssp`，本仓库 | — | 本仓库 |
| bwplan | `families.bwplan`，本仓库 | — | 本仓库 |
| factor | `families.factor`，本仓库（Miller–Rabin 用固定底 2–37，对 < 3.3·10²⁴ 确定） | — | 本仓库 |
| qcp（minimal / extended） | `families.qcp`，本仓库 | — | 本仓库 |

关于依赖的说明：
- PySAT 的 `pysat.pb` 需要 pypblib，环境中没有安装，所以本轮不使用一般伪布尔编码。基数家族只用 `CardEnc`。
- CNFgen 自带的 pigeonhole、ramsey、tseitin 等家族答案固定，证明结构也特殊，本轮没有选为主家族。

**正确性检验结果**（每个家族、每种编码各用 2–3 个极小规模，每个规模 12 个 seed，用 PySAT MiniSat 2.2 求解）：

| 家族 | SAT : UNSAT |
|---|---|
| vcover | 3 : 21 |
| jssp | 19 : 5 |
| bwplan | 33 : 3 |
| factor | 18 : 18 |
| qcp | 20 : 16 |
| col3 | 1 : 23 |

在每个家族上，求解器判定、穷举结果与替代编码三者完全一致，每个模型都能解码为合法解。

测试先暴露了一个测试代码自身的错误，已修复：积木规划的广度优先穷举多扩展了一步（允许 T+1 步计划）。生成器代码没有错误。

## 2. 生成任务登记

参数、编码与限制见协议第 3.1 节，网格与规则见 [generators.json](../../configs/broad_scope_v11/generators.json) 和 [panel_rule.json](../../configs/broad_scope_v11/panel_rule.json)。

**答案比例**：SAT/UNSAT 不强行平衡。factor 的任务由 seed 奇偶预先决定，大致各半；其他家族的答案比例在 BASELINES 中如实报告。

**已知限制**（在 STRUCTURE_MAP 中注明）：
- factor 的 UNSAT 一半是素数证明，证明结构特殊；
- vcover 只有单一全局基数约束；
- bwplan 的随机状态不是在全部状态上均匀抽取；
- qcp 的预填不做前向检查，部分 UNSAT 在传播阶段即可得出；
- rand3、col3、assign2 是 v8–v10 的桥接家族，其历史结论已经曝光。

## 3. 公开数据来源

**元数据**：GBD 快照 `$FP_DATA/benchmarks/gbd/{meta,base}.db`，2026-10-18 下载。文件来自 GBD 官方文件服务 `https://benchmark-database.de/file/<hash>`。2026-10-27 已在线核实 main_2026 track 的实例列表可以访问。

**许可**：SAT Competition 与 GBD 的基准按各提交者的条款公开分发，用于研究。本轮只在本地运行，不再分发。

规则见 [public_rule.json](../../configs/broad_scope_v11/public_rule.json)，实现为 `scripts/broad_scope_v11/public.py audit`，结果在 [public_pools.json](../../results/broad_scope_v11/public_pools.json)。

### 3.1 曝光集合

v1–v10 已曝光的 GBD 哈希来自以下文件：
- 本地下载目录：1594 个文件；
- `benchmarks/checksums.csv`（第 1 轮 M0–M5，1325 个）；
- three-way 选择（500 个）；
- v5 confirm（78 个）；
- 旧 55 题（v6/v7 面板）。

这些来源的并集共 1711 个哈希，对应 1568 个 GBD isohash。v11 排除这些哈希本身，以及与它们共享 isohash 的实例。

SATLIB 外部集（v9 60 题，v10 118 题）不在 GBD 中。v11 下载后用改名不变哈希与它们比较。

### 3.2 各来源的候选池（≤ 100 MB，排除曝光后）

| 来源 | 类别 | 候选 | 曝光哈希 | 曝光 isohash | 过大 / 无尺寸 | 前序来源已取 | 池 | GBD 家族数 | 与 v11 生成家族相关的家族（关键词规则） |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| comp2022 | 比赛 | 659 | 234 | 46 | 80 | 0 | 299 | 16 | scheduling、coloring、multiplier-circuits、set-covering |
| comp2023 | 比赛 | 636 | 341 | 64 | 42 | 0 | 189 | 16 | coloring-clique、school-timetabling |
| comp2024 | 比赛 | 1369 | 200 | 26 | 25 | 0 | 1118 | 12 | miter、random-circuits、scheduling、coloring |
| comp2025 | 比赛 | 350 | 175 | 2 | 45 | 0 | 128 | 13 | multiplier-verification、scheduling、clique-coloring、school-timetabling、multiplier-equivalence-checking |
| comp2026 | 比赛 | 1116 | 235 | 122 | 88 | 0 | 671 | 18 | graph-coloring、exam-scheduling、multiplier-circuit-miters、school-timetabling |
| planning2020 | 应用（规划） | 194 | 0 | 0 | 131 | 0 | 63 | 1 | planning |
| crypto2021 | 应用（密码） | 187 | 0 | 4 | 0 | 0 | 183 | 1 | — |
| agile | 应用（软件验证） | 2596 | 0 | 0 | 483 | 0 | 2113 | 1 | — |
| application0916 | 旧比赛应用 track | 1274 | 0 | 25 | 102 | 37 | 1110 | 34 | miter、scheduling、bitvector、planning、random、coloring、prime-factoring 等 |
| industrial0207 | 旧比赛工业 track | 936 | 0 | 64 | 60 | 191 | 621 | 17 | coloring-mycielski-graph、miter、planning、coloring |

**比赛年份的构成**：每年取 main 与 submissions track 的并集，且只保留在 GBD 中首次出现于该年的实例。只用 main track 不够，原因如下：
- 2022–2026 的 main track 几乎都已在 v1–v10 中运行过；
- 2023 年 main track 中未曝光的实例全部超过 1 GB；
- main track 全部 178 个 GBD 家族都至少有一题运行过。

submissions track 是同一届比赛公开发布的全部提交基准，其中包含未入选 main 的实例。

### 3.3 家族层面的曝光说明

- **比赛年份来源**：池中的每个 GBD 家族在 v1–v10 中都至少有一题被运行过。家族名层面没有“历史上从未出现”的家族。
- **未见家族的定义**：协议按“v11 的发现与训练中完全不出现”来定义未见家族，因为 v11 只用生成题训练。因此与 v11 生成家族无关的公开家族都算未见，例如 cryptography、agile（软件验证）、hardware-verification、argumentation、bioinformatics。
- **历史曝光另列**：这些家族在 v1–v10 中被运行过的其他实例，VALIDATION 会单独列出。
- **旧应用 track 的情况**：其中有 v1–v10 从未运行过的家族，例如 misc-satex、software-bmc、railway-safety、dining-philosophers、finite-state-machines、bounded-model-checking、alloy-vpn-models。
- **历史知识的影响**：早期轮次知道某些 GBD 家族在整体上偏好 D 或 F±（见第 4 节）。这些知识不进入 v11 的任何训练或阈值选择：v11 的规则只用生成题的发现与开发池拟合。但它是设计者已知的背景信息，在报告中如实注明。

## 4. 既有观测审计（不换名重复负结果）

### 4.1 v5 观测

（[reports/observations_v5](../observations_v5/FINAL_REPORT.md)）

- **观测范围**：11 个包，共 50 个新观测，分属 A–G 类：
  - 极性；
  - 根传播残差；
  - 双向 BCP / lookahead；
  - 蕴含图、社区与 WL 结构；
  - 三臂 probe（0.2 s、0.5 s、512 次冲突）；
  - 相位遥测；
  - 局部搜索。
- **开发结果**：27 个登记比较全部落在 −2.2% 到 +0.0% 之间。三臂 R07 为 −1.7% [−3.5, −0.3]。最大 |ρ| = 0.29。
- **确认结果**（78 题）：S1 +0.4% [−4.8, +6.0]。
- **v11 的处理**：三臂短 probe 大网格不再重开。D 前缀只作为单臂、小网格（0.1/0.5/2 s）的保守读出器保留，并与匹配的无内容对照比较。

### 4.2 v6 稳定选择

（[reports/stable_selection_v6](../stable_selection_v6/)）

- **稳定性**：F± 优势在 seed 0/1/2 上有 17/20 稳定。
- **局部搜索与特征**：局部搜索只显示组级模式，逐实例相关约 0.1。SATzilla 2024 特征只在 3 个组上拟合。
- **比较结果**：8 个比较在 −1.42% 到 −0.00% 之间。
- **新题结果**：55 新题 +2.2% [−0.2, +7.0]；开发中未用过的家族 +0.0%。
- **v11 的处理**：不重做局部搜索或 SATzilla 特征。静态特征用 v10 已实现的 static10（20 个指标）。

### 4.3 编码与变号证据

**M2（第 1 轮，388 题，300 s，只有 D/F−）**：

flipall 后 F− 的 PAR2 为 214.2，原题上 F+ 为 217.8，两者统计上对称，但逐步轨迹不对称（265 题中只有 5 题轨迹相同）。

| 变体 | 与原题 log 比的相关 |
|---|---|
| flipr | r = 0.48 |
| flipall | r = 0.09 |

F− 的优势按是否依赖极性分为两类：

| 类型 | 家族 |
|---|---|
| 优势依赖极性 | brent-equations、polynomial-multiplication 等 |
| 与方向无关的赢 | multiplier、cryptography-ascon、fpga-routing |
| 与方向无关的输 | set-covering、heule-nol、scheduling |

**v8（36 题）**：

| 条件 | 赢家不变 |
|---|---|
| flipall | 6/36 |
| flipall 后交换 F+/F− | 22/36 |
| perm | 21/36 |

rand3 UNSAT 上的 F± 优势在 perm 与 flipall 下都保持（5/5）。

**v10（54 题）**：

| 条件 | 最快动作不变 |
|---|---|
| perm | 24/54 |
| solver seed 1 | 49/54 |

整体顺序 F− < F+ < D 在各条件下保持，9 个严重的 F+ 损失也都保持。v8 之后没有在生成家族上做过全局翻转。

**v11 的新增内容**：
- 在 8 个家族（5 个是新的）上同时做替代编码、flipall、perm 与 solver seed；
- 首次加入语义等价的替代编码（col3 log、vcover totalizer、jssp time-indexed、qcp extended）。

M2 只做了 D/F−，也没有生成题。

### 4.4 v9 与 v10 的结论（曝光的背景）

- **v9**：
  - 生成家族上固定 F+ 比 D 好 45.8%；
  - 内容门控不如只看时间的门控；
  - assign 在大 T 时 F+ 严重变差。
- **v10**：
  - 确认收益来自类型路由（col3 → F+，rand3 → F−，大 assign → D），一题贡献约 63%；
  - 三臂 C 比单 D 前缀 B 差 14.4%；
  - SATLIB 外部集上 D 最好。
- **v11 的处理**：v11 把“CNF 结构识别后选固定 flag”设为主对照（协议第 7 节），以判断在线模型是否必要。

## 5. 数据与磁盘

- 生成题写在 `$FP_DATA/broad_scope_v11/cnf`，公开题写在 `$FP_DATA/broad_scope_v11/public/`，运行记录写在 `$FP_DATA/runs/broad_scope_v11/`。
- 审计时 /mnt/data 剩约 3 TB（总量 800 TB，使用率 100%）。v11 预计数据量为几十 GB，主要是公开 CNF 和 gzip 原始输出。磁盘不足时如实报告。
