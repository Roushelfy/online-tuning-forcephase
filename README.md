# Online Tuning of Forcephase

Research question: **Can cheap formula analysis or a short search probe select once among CaDiCaL’s default, forced-positive, and forced-negative configurations, and improve total solving cost?**

本仓库是科研项目 **Online Tuning Forcephase H:1** 的完整研究记录：固定版本 CaDiCaL 上的最小研究补丁、可复现的实验流水线、全部运行记录的汇总、分阶段报告和最终中文研究报告。

**历史最终报告：[reports/FINAL_REPORT.md](reports/FINAL_REPORT.md)**（含英文 abstract）。

**当前主评价口径为v7：同一批任务全部完成后的平均CPU时间。**下面v4–v6的PAR2数字均为历史截断实验，不是新口径下的完成时间；新口径尚未得到完整结果。

**三选一研究（Agent Goal v4）已完成（2026-10-22）：[reports/three_way/FINAL_REPORT.md](reports/three_way/FINAL_REPORT.md)。**五年代表性面板（2022–2026，500 题，dev 401 / test 99，家族不相交）上，默认 D 是最佳固定动作；冻结的静态选择器与 0.1 s 试跑选择器在 test 上相对 D 为 PAR2 −3.7% [−10.4, +2.5] 与 −1.7% [−7.9, +3.2]（含全部观察成本），dev 交叉验证中 12 个候选也全部不如 D：有界负结果。oracle 上限 dev 12% / test 8.5%，但集中于少数实例，廉价特征只与胜负弱相关。协议 [THREE_WAY_PROTOCOL.md](docs/THREE_WAY_PROTOCOL.md)；面板 [DATASET.md](reports/three_way/DATASET.md)；S1 [BASELINE_PROFILE.md](reports/three_way/BASELINE_PROFILE.md)；S2 [SELECTOR_CV.md](reports/three_way/SELECTOR_CV.md)；S3 [TEST_RESULTS.md](reports/three_way/TEST_RESULTS.md)；算力 39.9 CPU 核时（[COMPUTE.md](results/three_way/COMPUTE.md)）。

**Goal v6（稳定优势子群）已完成（2026-10-23）：[reports/stable_selection_v6/FINAL_REPORT.md](reports/stable_selection_v6/FINAL_REPORT.md)。**30 题的诊断面板显示，F+/F− 的原优势在 3 个 solver seed 下 85% 稳定，因为 F± 关闭了 rephase，几乎不受 seed 影响。局部搜索观测改为固定工作量后，同一输入重复运行的非计时特征逐项相同；SATzilla 2024 官方特征只有 3 组能放进观察预算。但 dev 上 8 个登记比较（S28、局部搜索、SATzilla × ridge 门 / 解出概率加条件耗时，再加 2 条规则）都不优于始终 D（−1.42% 到 −0.00%），新特征也没有增量。冻结后在 55 道新题上，负对照策略为 +2.2% [−0.2, +7.0]，收益来自 dev 家族上的 2 次偏离，在非 dev 家族上为 +0.0%。结论是有界负结果，瓶颈在逐题信号不足和错误偏离的不对称成本。协议见 [STABLE_SELECTION_PROTOCOL_V6.md](docs/STABLE_SELECTION_PROTOCOL_V6.md)；算力 22.4 核时，累计 144.7 / 200。

**Goal v5（扩大观测方式）已完成（2026-10-23）：[reports/observations_v5/FINAL_REPORT.md](reports/observations_v5/FINAL_REPORT.md)。**在 v4 的五年面板上实施了候选库中的 50 项新观测（A–G 七类，外加 1 项部分实施），包括三动作配对短试跑、双边传播、根传播残余式、加权极性、修正的相位轨迹、蕴含图、社区/WL 和局部搜索；分装成 11 个观察包，每个配上带默认回退门的绝对成本读出器，在 dev 401 上做家族分组嵌套交叉验证，全部观察 CPU 计入成本。结果是有界负结果：27 个登记比较没有一个可靠优于始终 D（−2.2% 到 +0.0%）；同一读出器下，没有一个观察包相对 v4 的 28 个静态特征有增量；新读出器比 v4 读出器好，但只是因为更少偏离。两个按协议选出的策略，在 dev 真实部署中为 −0.25% 与 −0.01%，在冻结后的 78 题确认集上为 +0.4% [−4.8, +6.0] 与 −1.4%。另外发现：局部搜索观测不可复现，大公式上观察常常触顶，单 seed 的 D 优势标签不稳定。协议见 [OBSERVATION_PROTOCOL_V5.md](docs/OBSERVATION_PROTOCOL_V5.md)，注册表见 [registry.json](configs/observations_v5/registry.json)；算力 82.4 CPU 核时，v4 之后累计 122.3（[COMPUTE.md](results/observations_v5/COMPUTE.md)）。

**当前执行目标：Agent Goal v7（评价口径已改，长时数据待采集）：[docs/AGENT_GOAL.md](docs/AGENT_GOAL.md)。**主指标改为同一批实例全部有效完成后的算术平均CPU时间（含观察与重启），不使用超时惩罚或300秒截断均值；有题未完成时主均值与相关收益为未知。第一批固定沿用v6的55题，先补默认完整时间、oracle与冻结策略长时版。新协议：[COMPLETION_TIME_PROTOCOL_V7.md](docs/COMPLETION_TIME_PROTOCOL_V7.md)；评价脚本：[evaluate.py](scripts/completion_v7/evaluate.py)；当前状态：[STATUS.md](reports/completion_v7/STATUS.md)。v6目标存档：[AGENT_GOAL_STABLE_SELECTION_V6.md](docs/AGENT_GOAL_STABLE_SELECTION_V6.md)。

**v5 的执行顺序**：核对旧观测的有效覆盖与错误损失 → 在小面板上验证新观测与开销 → 在开发集上分组筛选并保守选择 → 完整 wrapper 实测 → 小型新确认。各阶段的报告都在 `reports/observations_v5/`。

## 第一轮结论速览

状态：第一轮 M0–M5 于 2026-10-19 完成；同日按 [Agent Goal v2](docs/AGENT_GOAL_AUDIT_V2.md) 完成**审计修正与科研收尾**（[纠正协议](docs/CORRECTION_PROTOCOL.md)、[逐项关闭记录](reports/AUDIT_CLOSURE.md)）。结论是**有边界的负结果**。数据：SAT Competition 2023–2026 主赛道（≤100 MB），CaDiCaL 3.0.1，T = 300 s，所有 solved 结果经模型检查或 LRAT 证明检查。原始任务：[AGENT_GOAL_INITIAL.md](docs/AGENT_GOAL_INITIAL.md)；第一轮最终报告存档：[FINAL_REPORT_round1.md](reports/FINAL_REPORT_round1.md)。

- **强制负分支整体有害**：dev 上比 stock default 少解 58 个（PAR2 −10.8%），冻结的 family-disjoint test 上 −29%；损失主要在可满足实例。
- **机制（单因素配对）**：关闭 rephase（forcephase 隐含）有清楚的损害（dev −10.0% [−21.7, −2.0]，主要在 SAT）；在 rephase 已关闭时，强制负代替 target/saved 的点估计更差但区间跨 0。
- **编码相关**：经符号翻转检验的 F− 获胜家族（如 brent-equations）在全局翻转后变为大幅劣势，随机翻转后优势消失。
- **本轮未找到可迁移的预测策略**：同状态确定性重放标签（5,887 次重放、5,884 个有效配对）上，静态、time-only 与在线一次选择器在家族外都没有超过“不切换”；审计发现一个极性特征（saved 翻转率）计算有误，修复控制器并排除该特征后在同一数据与 folds 上重算，结论不变。
- **冻结评估**：预注册候选“先强制负 1e4 冲突再原生”在 family-disjoint test 上相对 validation-SBS（仅初始负）为 −1.0% [−3.4, +1.7]，**未达到 ≥5% 的预设目标**；在 2026 年实例上比 stock default 好 1.3% [+0.2, +2.5]，但不优于仅初始负。
- **工程**：控制器关闭 / telemetry-only 与上游搜索逐项相同；低噪声复测中 telemetry 开销中位 +0.05%、p95 +0.35%；第一轮 36,157 次运行（2,117 CPU 小时）与本轮审计（约 23.8 CPU 小时）均有账本，全账本完整性审计 0 问题。
- **未做 / 未知**：基于内容观测的重复切换控制器（门槛未满足，未继续）、正确 flip 特征的全集重采、长 cutoff 与其它求解器。

## 文档

| 文档 | 内容 |
| --- | --- |
| [当前 Agent Goal v7](docs/AGENT_GOAL.md) | 所有任务完成后的平均CPU时间、同面板长时复评 |
| [完成时间评价协议 v7](docs/COMPLETION_TIME_PROTOCOL_V7.md) | 完整均值、未完成状态、oracle下界与评价入口 |
| [已完成的稳定选择目标 v6](docs/AGENT_GOAL_STABLE_SELECTION_V6.md) | v6历史任务与旧300秒评价边界 |
| [已完成的观测目标 v5](docs/AGENT_GOAL_OBSERVATIONS_V5.md) | v5历史任务、候选库与结果边界 |
| [观测候选库v5](docs/OBSERVATION_CATALOG_V5.md) | 80项观测、12类决策方法、优先级、成本、文献与首轮观察包 |
| [已完成的三选一目标v4](docs/AGENT_GOAL_THREE_WAY_V4.md) | v4历史任务与结果边界 |
| [五年代表性抽样](docs/FIVE_YEAR_SAMPLE_PLAN.md) | 2022–2026，每年约 100 题，家族/规模覆盖、跨年去重与曝光标记 |
| [旧在线切换目标 v3](docs/AGENT_GOAL_SWITCHING_V3.md) | 历史目标存档，本阶段不继续扩展反复切换 |
| [研究计划](docs/RESEARCH_PLAN.md)、[实验协议](docs/EXPERIMENT_PROTOCOL.md)、[审计目标 v2](docs/AGENT_GOAL_AUDIT_V2.md) | 原问题、第一轮协议与审计交付标准 |
| [相关工作](docs/RELATED_WORK.md)、[源码审计](docs/SOURCE_AUDIT.md) | 文献与固定源码事实 |
| [实现设计](docs/DESIGN.md) | 补丁、控制器语义、切换状态处理、遥测 schema、策略文件格式 |
| [实验日志](docs/EXPERIMENT_LOG.md) | 预注册决定与每次协议具体化（含时间与“已接触哪些结果”） |
| [M0–M1 报告](reports/M0_M1_report.md) | 语义、正确性、确定性、观测开销 |
| [M2 报告](reports/M2_report.md) | 静态互补性、机制诊断、编码敏感性 |
| [M3 报告](reports/M3_report.md) | 同状态重放、一次选择、RQ3 时间变化 |
| [M4 报告](reports/M4_report.md) | 门槛判断、无观测固定调度、M5 候选 |
| [M5 报告](reports/M5_report.md) | 冻结后的 held-out 评估 |
| [算力账本](reports/COMPUTE_LEDGER.md)、[audit v2 账本](reports/audit_v2/COMPUTE_AUDIT_V2.md) | 所有尝试的 CPU 时间 |
| [纠正协议](docs/CORRECTION_PROTOCOL.md)、[审计关闭记录](reports/AUDIT_CLOSURE.md) | audit v2：缺陷、固定的纠正方案、修复与验证证据 |
| [数据位置](DATA_LOCATION.md)、[benchmark 来源](benchmarks/SOURCES.md) | 大文件位置、下载与校验 |

## 仓库结构

```text
third_party/   cadical（固定 c607304）、lrat-trim、drat-trim 子模块
patches/       cadical-fpc.patch（对上游的 hook，约 100 行）
solver/        fpcontrol.{hpp,cpp}：控制器、遥测、策略求值
tools/         checkmodel.c（模型检查）、cnffeatures.c（静态特征）、cnfscramble.c（变换/seed）
scripts/       构建、下载、运行（fprun.py + slurm_submit.sh）、汇总与分析
configs/       solver_configs.json、experiments/*.json、policies/、m5_freeze.json
benchmarks/    manifest.csv、family_groups.csv、checksums.csv、derived/（派生实例清单）
analysis/      fpstats.py（PAR2、cluster bootstrap、作图约定）
tests/         m0_suite.py、api_phase_test.cpp
results/       每个实验的 runs.csv（一行一次计划运行，含 run_id）、静态特征
reports/       分阶段报告、表格与图（全部由脚本生成）
```

## 复现

小型全流程（干净 checkout，约 10–20 分钟，8–16 核）：

```bash
git clone -b research/forcephase-study https://github.com/Roushelfy/online-tuning-forcephase.git
cd online-tuning-forcephase
FP_DATA=/path/to/data scripts/repro_small.sh /path/to/out
```

它会初始化子模块、构建四个求解器变体与检查工具、运行快速 M0 套件、下载 20 个 smoke 实例、以 10 s cutoff 运行 D/I−/F−/F+（带 LRAT 证明与验证）、汇总并生成 M2 风格的表和图。分析步骤需要 `pyproject.toml`/`uv.lock` 中的 Python 环境（通过 `FP_PY` 指定解释器）。

审计修订流程（读取已提交的运行汇总与 `$FP_DATA` 下的原始遥测，只读）：

```bash
scripts/build_solver.sh fpc2                       # v2 控制器（仅用于 C++ 一致性检查）
scripts/audit_v2/run_m3_revision.sh reports/audit_v2/m3_rerun   # 门禁 → 复现第一轮 → 修订 M3 → 对比 → 信号 → 策略一致性
scripts/audit_v2/integrity.py --out results/audit_v2/integrity  # 全账本完整性审计
scripts/audit_v2/m5_recheck.py --out reports/audit_v2/m5_recheck.md
```

完整实验（Genesis Slurm 集群，gs-srun 容器内）：

```bash
scripts/build_solver.sh && scripts/build_tools.sh                 # 容器内构建
scripts/build_manifest.py --gbd $FP_DATA/benchmarks/gbd --out benchmarks
scripts/fetch_benchmarks.py --splits train,val,test,t2026
scripts/slurm_submit.sh configs/experiments/m2_census.json 6       # 其余实验同理
scripts/collect.py --exp configs/experiments/m2_census.json --out results/m2_census/runs.csv
$FP_PY scripts/analyze_m2.py --runs results/m2_census/runs.csv --diag results/m2_diag/runs.csv --out reports/m2
```

各报告开头列出了对应的实验配置、命令和分析脚本。运行结果按内容寻址（二进制哈希、参数、实例、seed、cutoff、证明政策），重复提交只会补齐缺失的运行，不会覆盖已有结果。

## 关键语义（已由 M0 验证）

- 默认 `phase=1`：裸 `--forcephase` 强制**正**方向；负分支是 `--forcephase=1 --phase=0`。
- stock 默认包含 target phase 与 rephasing，不是“纯 phase saving”；`--forcephase` 同时关闭 rephasing。
- 强制负只作用于自由决策，单位传播仍产生正文字。

## 依赖与许可证

| 依赖 | 固定版本 | 许可证 | 用途 |
|---|---|---|---|
| [CaDiCaL](https://github.com/arminbiere/cadical) | `c60730422e758ef1cebe7aeddf2dda31c996bf04`（3.0.1） | MIT（`third_party/cadical/LICENSE`） | 求解器；`patches/` 与 `solver/` 是对它的修改，构建产物保留上游许可证文本 |
| [lrat-trim](https://github.com/arminbiere/lrat-trim) | `b30f400f4ee5c32b77ee566a7c006081b521534f` | MIT 型（`third_party/lrat-trim/LICENSE`） | LRAT 证明检查 |
| [drat-trim](https://github.com/marijnheule/drat-trim) | `2e3b2dc0ecf938addbd779d42877b6ed69d9a985` | MIT 型（`third_party/drat-trim/LICENSE`） | 备用 DRAT 检查（主流程未使用） |
| Python 分析环境 | `pyproject.toml` + `uv.lock`（numpy 1.26.4、scipy 1.13.1、pandas 2.2.2、matplotlib 3.9.2、scikit-learn 1.5.2） | 各自开源许可证 | 汇总、统计、作图、M3 模型 |
| benchmark | GBD / SAT Competition 2023–2026（见 `benchmarks/SOURCES.md`） | 按竞赛与 GBD 发布条款 | 不提交 CNF，只提交 manifest 与校验和 |

运行器 `scripts/fprun.py`、校验与变换工具 `tools/*.c` 只依赖 C/C++ 编译器与 Python 标准库。
