# 三选一研究最终报告：低成本观察后在 D、F+、F− 中选择一次

状态：完成（2026-10-22）。目标见 [Agent Goal v4](../../docs/AGENT_GOAL.md)，协议见 [THREE_WAY_PROTOCOL.md](../../docs/THREE_WAY_PROTOCOL.md)。

| 阶段 | 提交 | 报告 |
|---|---|---|
| S0：面板与协议 | `093cf3e` | [DATASET.md](DATASET.md) |
| S1：dev 三动作对照与优势组特点 | `63316c4` | [BASELINE_PROFILE.md](BASELINE_PROFILE.md) |
| S2：选择器交叉验证与冻结（tag `tw-freeze`） | `b9b7a87` | [SELECTOR_CV.md](SELECTOR_CV.md) |
| S3：test 上的真实运行 | 本报告所在提交 | [TEST_RESULTS.md](TEST_RESULTS.md) |

算力账本：[results/three_way/COMPUTE.md](../../results/three_way/COMPUTE.md)。

## 结论（简要）

1. **没有找到能稳定改进三选一的低成本观察。** 两类选择器都不如“始终用 D”：
   - 静态公式统计 + 逻辑回归：test 上 PAR2 −3.7%，95% 家族 cluster bootstrap CI [−10.4, +2.5]；
   - 静态统计 + 0.1 s D 试跑 + 逻辑回归：test 上 −1.7% [−7.9, +3.2]。

   两个区间都包含 0。dev 上的家族分组交叉验证也一样：12 个预先列出的候选全部比 D 差 1.4%–7.8%。负方向在 dev 和 test 上一致，可以把它看作可靠的负结果；但 test 只有 99 题，区间较宽，不能排除很小的正效应。
2. **最佳固定动作是默认 D**（dev PAR2 382.1，test 397.6）。两种强制都更差：
   - F+：dev −10.4%，test −13.4% [−20.0, −7.0]；
   - F−：dev −11.3%，test −7.1% [−16.5, +2.1]。

   差距主要来自 SAT：dev 上三者解出的 UNSAT 数相同（各 72 个），D 多解出 30 多个 SAT。
3. **收益空间存在，但小而分散。** hindsight oracle（每题事后选最好的动作）比 D 好 12.0%（dev）和 8.5%（test）。这部分增益集中在少数实例上：dev 上前 25 题占 67%。F+ 优势（dev 38 题）和 F− 优势（24 题）分散在 20 个家族中。
4. **观察成本不是失败的主因。** 静态特征的中位开销是 0.2 s，0.1 s 试跑约 0.3 s，只占 PAR2 的约 0.6–0.7%。即使把开销记为 0，两个选择器选出的动作本身也比 D 差：PAR2 分别为 409.7 和 401.5，D 为 397.6。失败的原因是选错，而不是付出的观察开销。
5. **可观察特点与胜负只有弱相关。** dev 上 291 个“特征 × 响应量”组合中，|ρ| 都不超过 0.30，只有 9 个在 train、val 和家族内都同号且 |ρ| ≥ 0.1。“正文字多就选 F+、负文字多就选 F−”在 dev 上不成立（ρ ≈ 0）。最一致的一条试跑信号与直觉**相反**：D 试跑中负决策越多，F+ 相对 F− 越好（ρ ≈ −0.2）。

## English abstract

We asked whether cheap observations can select once among CaDiCaL 3.0.1's default phase policy (D), forced-positive (F+) and forced-negative (F−) branching, with the observation cost charged. The observations were static formula statistics, optionally followed by a short probe run of D.

**Panel.** A representative panel of 500 SAT Competition main-track problems (2022–2026, 100 per year, deduplicated by isohash, sampled by family and size) was split by family group into dev (401) and test (99). All rules were frozen before any new solver run.

**Dev results.** D is the best fixed action: PAR2 382 vs 422 for F+ and 425 for F−, at T = 300 s. The hindsight oracle is 12% better than D, but its gain is concentrated in a few instances, and winner groups are small and spread over many families. Static features and D-probe statistics are only weakly related to which action wins (|ρ| ≤ 0.30). The intuitive polarity rule ("more positive literals → force positive") does not hold.

**Selection.** All 12 pre-registered candidates were worse than always-D in family-grouped cross-validation on dev (cost-sensitive trees of depth 1 or 3, and regularised logistic regression, each with static features or with D probes of 0.1, 0.5 or 2 s).

**Test.** We froze the best static and the best probe selector before running any test instance, then ran them for real with all overheads charged. On the family-disjoint test panel, the static selector changed PAR2 by −3.7% (95% cluster-bootstrap CI [−10.4, +2.5]) relative to D, and the probe selector by −1.7% [−7.9, +3.2]. Observation overhead was small (about 0.2–0.3 s median). The loss comes from wrong choices.

**Conclusion.** This is a bounded negative result: at this cutoff and on this panel, cheap observations do not reliably pick a better phase configuration than CaDiCaL's default.

## 1. 设计

- **动作**：
  - D = `--phase=1 --forcephase=0`（默认原生相位）；
  - F+ = `--phase=1 --forcephase=1`；
  - F− = `--phase=0 --forcephase=1`。

  所有动作都用第一轮的构建 `build/fpc`（CaDiCaL `c607304`，3.0.1；控制器关闭，搜索与上游一致），配合 LRAT 证明、遥测、seed 0、T = 300 CPU 秒、内存 16 GB。与第一轮完全相同的运行按 run id 直接复用。
- **面板**（[DATASET.md](DATASET.md)）：
  - 来源：SAT Competition 2022–2026 主赛道，与官方名单逐题核对；同一 isohash 只计一次，共 1,865 个独立问题；排除未压缩超过 1 GB 的问题。
  - 抽样：每年 100 题，先覆盖每个家族组，再按 sqrt(组大小) 分配剩余名额，按三分位规模层分层，seed 20261022。
  - 划分：按家族组分为 train 301、val 100、test 99；test 优先选第一轮从未运行过的实例。
- **流程**：
  - S1：在 dev 上运行三个固定动作，按冻结规则分优势组并比较特征。
  - S2：12 个预先列出的候选做家族分组 5 折 CV，冻结一个静态选择器和一个试跑选择器（tag `tw-freeze`）。
  - S3：在 test 上真实运行 3 个固定动作和 2 个 wrapper。

  wrapper（`scripts/three_way/select_solve.py`）的流程是：读取公式特征，可选再做一次 D 试跑，然后选择一次并从头求解。它的总 CPU 包括 Python 启动、特征提取、试跑、推理和正式求解。

## 2. dev：各模式适合什么题（S1）

| 动作 | solved | SAT / UNSAT | mean PAR2 |
|---|---:|---|---:|
| **D** | **166** | 94 / 72 | **382.1** |
| F+ | 136 | 64 / 72 | 422.0 |
| F− | 133 | 61 / 72 | 425.1 |
| oracle（事后最优） | 199 | | 336.2 |

优势组（m = (第二名 + 1)/(最好 + 1) ≥ 1.5）：

| 组 | 实例数 | 说明 |
|---|---:|---|
| D 优势 | 62 | 34 个家族；其中 36 个是强制直接失败 |
| F+ 优势 | 38 | 20 个家族 |
| F− 优势 | 24 | 20 个家族；22 个是 SAT |
| 差距很小 | 75 | 多为 UNSAT |
| 三者都超时 | 202 | 不提供标签 |

**家族偏好**：家族名只用于解释，不能作为部署特征。

| 偏好 | dev 家族 | test 家族 |
|---|---|---|
| D | school-timetabling、set-covering、planning、scheduling（强制在这些家族上明显更差） | software-verification、hardware |
| F+ | hamiltonian（9 题中 6 个 F+ 优势）、multiplier、disagreement-parity | — |
| F− | cryptography-ascon、cellular-automata、brent-equations | graph-isomorphism（PAR2 62，D 为 124）、sat-x（只有 F− 解出 1 题） |

**可观察特点**：只有弱相关。

- **规模**：实例越大，F+ 相对 D 越差。
- **Horn 比例**：比例越高，F− 越差。
- **试跑**：D 试跑中负决策比例越高，F+ 相对 F− 越好。
- **静态极性**：正负文字的比例与 F+/F− 的相对优劣无关。

详见 [BASELINE_PROFILE.md](BASELINE_PROFILE.md) §4，那里把每条关系标为稳定、相关或未确认。

## 3. 选择器（S2）

| 候选（摘要） | dev CV mean PAR2 | 相对 D |
|---|---:|---:|
| 始终 D（最佳固定） | 382.1 | — |
| **试跑 0.1 s + 逻辑回归（冻结）** | 387.3 | −1.4% |
| 试跑 2 s + 深度 1 成本树 | 390.0 | −2.1% |
| **静态 + 逻辑回归（冻结）** | 393.0 | −2.8% |
| 其余 9 个候选 | 393.7–411.8 | −3.0% 到 −7.8% |
| oracle | 336.3 | +12.0% |

- 树模型在样本内能比 D 好（深度 3 为 364.0），交叉验证时却变差：特征信号太弱，不足以支撑可泛化的选择。
- 实现核对：
  - 始终选 D 的模拟成本与 D 原值只差特征开销（382.15 对 382.10）；
  - 导出的纯 Python 推理与 sklearn 的预测 100% 一致；
  - test 上 wrapper 正式求解与同动作固定运行的 CPU 比的中位数为 0.98。

## 4. test：冻结后的真实运行（S3）

| 策略 | solved | mean PAR2 | 相对 D（95% CI） |
|---|---:|---:|---|
| **D（最佳固定动作）** | **41** | **397.6** | — |
| F+ | 30 | 450.7 | −13.4% [−20.0, −7.0] |
| F− | 34 | 425.7 | −7.1% [−16.5, +2.1] |
| 静态选择器 | 37 | 412.2 | −3.7% [−10.4, +2.5] |
| 试跑选择器（0.1 s） | 39 | 404.4 | −1.7% [−7.9, +3.2] |
| oracle（不可部署） | 46 | 363.7 | +8.5% |

**选择器行为**：

| 选择器 | 选 D / F− / F+ | 明显更好 / 明显更差（题） | 严重回退（题） | 观察开销中位数 |
|---|---|---|---:|---:|
| 静态选择器 | 51 / 29 / 19 | 4 / 8 | 5 | 0.20 s |
| 试跑选择器 | 51 / 38 / 10 | 2 / 4 | 3 | 0.30 s |

- 试跑选择器的 0.1 s 试跑在 test 上没有直接解出任何实例。
- 在至少一个动作解出的 46 题中，选中事后最优动作的比例：静态 33%，试跑 48%（仅作辅助指标）。

**按年份**（详见 [TEST_RESULTS.md](TEST_RESULTS.md) §4；每年题数少，只作描述）：

| 年份 | 选择器 vs D 的 PAR2 |
|---|---|
| 2025 | 两个选择器都比 D 好：245 / 241 对 275 |
| 2022 | 都比 D 差：468 / 464 对 445 |
| 2024 | 静态选择器差（466 对 424），试跑选择器与 D 持平（423） |
| 2023 | 都比 D 差：411 / 411 对 352 |
| 2026 | 三者相同 |

**按曝光**：
- 第一轮从未运行的 79 题：D 404，静态 415，试跑 412。
- 家族在第一轮从未被运行的 44 题：D 340，静态 353，试跑 355。

结论与全 test 相同。

## 5. 回答目标中的问题

| 问题 | 回答 |
|---|---|
| 什么廉价信息能帮助三选一？ | 在本面板和 T = 300 s 下，没有一种足以可靠地帮助选择。静态特征（规模、Horn 比例、极性、出现次数分布）和 D 短试跑统计（决策符号、来源、冲突速度、检查点相位）都只与胜负弱相关，家族内的信号更弱。 |
| 计入观察成本后，是否优于开发阶段选出的最佳固定动作？ | 否。两个冻结的选择器在 test 上都略差于 D，CI 含 0；dev CV 结论相同。 |
| 哪些观测有用 / 无用？ | 有一致方向但很弱的：规模（对 F+ 不利）、Horn 比例（对 F− 不利）、D 试跑的负决策比例（与 F+ 相对 F− 的优势相关，方向与“顺着 D 的极性”相反）。无用：静态正负文字比例、变量极性偏置均值、全正 / 全负子句比例。 |
| 哪些家族偏好哪种动作？ | 见 §2；偏好只在家族层面可见，选择器不能使用家族名。 |
| 选择错误的损失 | 选错的代价不对称：从“解出”变成“超时”的损失最多可达 600 s，而选对的平均收益小。test 上静态选择器有 5 题严重回退，试跑选择器有 3 题，抵消了少数正确偏离带来的收益。 |
| 观察成本是否吃掉收益？ | 没有。观察成本只占约 0.6–0.7% 的 PAR2；不计开销时，选出的动作本身仍差于 D。 |

## 6. 局限

- **单一设置**：只有一个 seed，T = 300 s，一个求解器版本，一类硬件。长 cutoff、其他求解器或多 seed 下的结论未检验。
- **test 不是完全独立的新盲测**：test 与本轮 dev 家族不相交，79/99 个实例第一轮从未运行，但其中 55 个实例所在的家族在第一轮出现过（20 个实例本身有第一轮结果），而且本 agent 读过第一轮按家族的报告。按曝光分层后结论不变。
- **test 偏向**：test 偏向 2022 年（45 题）和大规模层（58 题；49 题超过 100 MB）。dev 中超过 100 MB 的实例只有 12 个。超过 1 GB 的 68 个问题被排除，结论不适用于这一规模层。
- **样本量与选择范围**：test 只有 99 题，其中 53 题所有策略都超时，CI 较宽。选择器只覆盖了预先列出的 12 个简单候选，没有尝试更复杂的模型或更长的试跑预算（这是协议有意的约束）。
- **离线模拟**：S2 的 CV 使用离线模拟成本（κ = 0.08 s）。最终数字全部来自真实 wrapper 运行，并与模拟一致：test 上 wrapper 正式求解与固定运行的 CPU 比中位数为 0.98。

## 7. 与以往结果的关系

- **第一轮**（二元 D/F− 与动态切换，[FINAL_REPORT.md](../FINAL_REPORT.md)）的结论是“强制负整体有害；没有在线选择器胜过不切换”。本轮把动作扩展为 D/F+/F−、换成五年代表性面板和一次性选择，结论一致：默认 D 很难被廉价信号超越。
- **LPN 机制实验**（分支 `lpn-sparse-secret`，`experiments/lpn_sparse_secret/results/lpn_sparse_main/REPORT.md`）说明，在解很稀疏、而且稀疏性不在约束中的构造家族上，F−（或极性翻转后的 F+）可以大幅胜出。但这类结构在竞赛实例上无法用廉价特征识别，本轮的弱相关结果与此相容。

## 8. 复现

```bash
export FP_DATA=/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase FP_PY=/mnt/data/zhaofeng/venvs/online-tuning-forcephase/bin/python
scripts/three_way/sample_panel.py --gbd $FP_DATA/benchmarks/gbd --official $FP_DATA/benchmarks/official   # 面板（确定性）
scripts/fetch_benchmarks.py --manifest results/three_way/manifest.csv --checksums results/three_way/checksums.csv --splits train,val,test
scripts/three_way/build_tools.sh                                                       # 容器内构建 cnfprofile
scripts/slurm_submit.sh configs/three_way/tw_dev_fixed.json 1 48 cpu-low 08:00:00      # S1a（复用第一轮记录）
scripts/three_way/slurm_twrun.sh 1 48 02:00:00 -- profile --hashes configs/three_way/dev_hashes.txt
scripts/three_way/slurm_twrun.sh 1 48 03:00:00 -- probe --hashes configs/three_way/dev_hashes.txt
$FP_PY scripts/three_way/baseline_profile.py                                           # S1 报告
$FP_PY scripts/three_way/twselect.py --kappa 0.08 --export configs/three_way/frozen    # S2 + 冻结
scripts/slurm_submit.sh configs/three_way/tw_test_fixed.json 2 48 cpu-low 08:00:00     # S3 固定动作
scripts/three_way/slurm_twrun.sh 1 48 06:00:00 -- wrap --hashes configs/three_way/test_hashes.txt --model configs/three_way/frozen/static.json
scripts/three_way/slurm_twrun.sh 1 48 06:00:00 -- wrap --hashes configs/three_way/test_hashes.txt --model configs/three_way/frozen/probe.json
$FP_PY scripts/three_way/evaluate_test.py && python3 scripts/three_way/compute_ledger.py
```

部署时的单题用法：`scripts/three_way/select_solve.py --model configs/three_way/frozen/probe.json --cnf X.cnf --timeout 300 --workdir DIR`。

## 9. 算力

本阶段新计算共 **39.9 CPU 核时**（上限 200），没有中断的运行，也没有运行器错误。

| 项 | CPU 核时 |
|---|---:|
| dev 新固定运行（171 次） | 10.5 |
| test 新固定运行（237 次） | 15.3 |
| test wrapper（2 × 99 次） | 12.3 |
| 试跑、特征与 smoke | 1.6 |
| 检查器 | 0.2 |

此外复用了第一轮的 1,092 次运行，不计入本阶段。明细见 [COMPUTE.md](../../results/three_way/COMPUTE.md)。
