# v11 最终报告：扩大题目范围后的结构与 flag 偏好

日期：2026-10-28。目标：[Agent Goal v11](../../docs/AGENT_GOAL.md)。协议：[BROAD_SCOPE_PROTOCOL_V11.md](../../docs/BROAD_SCOPE_PROTOCOL_V11.md)（偏离见第 12 节）。tag：`v11-panel-freeze`（52066f1）与 `v11-rule-freeze`（99f33de）。

本报告中的陈述分为四类：**实测**、**相关**、**假说**、**未知**。

## 中文摘要

**问题**：哪些 SAT 结构对 CaDiCaL 的 D / F+ / F− 有稳定偏好？这种偏好能否由 CNF 廉价识别，并迁移到未见的实例、规模、编码和家族？

**做了什么**：
- **生成家族**：8 个，包括 3 个桥接家族和 5 个新家族：
  - 桥接：随机 3-SAT、图 3 着色、耦合分配；
  - 新增：基数约束点覆盖、job-shop 调度、积木规划、乘法器因子分解、拉丁方补全。
  - 每家族 3 档规模，共 768 题：发现 288、开发 240、确认 240。
- **公开题**：120 道，来自 10 个来源，其中 60 道来自 2022–2026 年的比赛，30 个 GBD 家族与生成家族无关。
- **编码与变号诊断**：在 48 个基础问题上做了 4 种语义等价的替代编码、全局翻转、变量重排和 solver seed。
- **运行规模**：全部约 4970 次运行，每次单独上限 3600 CPU s，答案都经独立检查；生成题的 SAT 模型还按问题本身解码检查（共 1838 个，全部通过）。
- **预算**：累计核时不设上限，共 958 核时。

**实测结论**：
1. **D 是广泛可靠的默认**：
   - 训练池 528 题：D 解 505 题，F− 452，F+ 394。F± 没有解出任何 D 解不出的题。逐题 oracle 只比 D 少 13% CPU。
   - 确认 240 题：D 228，F− 204，F+ 180。
   - 公开 120 题：D 82，F− 78，F+ 75。
2. **只有一个家族有可复现的偏好：积木规划 → F−**：训练池中便宜 18%；在 30 道新的确认题上便宜 24.1%，区间 [13.9, 32.6]。其他家族都偏 D 或差别在噪声以内（factor）。
3. **F± 的严重失败可复现**：
   - 拉丁方 minimal 编码下 F+ 全部超时：训练池 66/66，确认集 30/30；
   - 点覆盖上 F± 大量超时：确认集 F+ 12/30、F− 8/30 可解，D 27/30；
   - job-shop 与大规模分配题上 F± 慢数倍到十余倍。
4. **编码可以单独决定偏好**：拉丁方换成 extended 编码后 F+ 从全败变为与 D 相当；job-shop 的 time-indexed 编码比 order 编码慢约 100 倍，赢家也随之改变。
5. **单题偏好有相当部分是噪声**：
   - 只改变量编号时，31/48 保持最快模式；只换 solver seed 时，34/48 保持；
   - 全局翻转后 F+ 与 F− 在 rand3 / 积木 / 着色上大致互换，但在 job-shop、因子分解上不互换。
6. **方法比较**（训练池嵌套分组 CV）：静态树、带越界回退的类型路由、静态 + D 前缀读出器，都没有超过固定 D：
   - 静态树 −0.2%，类型路由 −0.7%，前缀读出器 −1.6%；
   - 前缀读出器相对匹配的无内容对照为 −1.5%；
   - v10 冻结策略少解 44 题。

   按预先登记的规则，冻结的主策略就是固定 D，结构对照（静态树）的冻结结果是单叶 D。
7. **独立确认**：
   - 主策略等于开发 SBS，选择收益为 0，未达到“≥ 5% 且区间下界 > 0”的可靠收益标准；
   - 结构对照与 D 的差别只是重复运行的计时噪声与约 0.2 s 的静态分析开销；
   - v10 策略在新家族上少解 25 题（确认集）和 4 题（公开集）。

**相关与假说**：
- F± 的收益主要出现在 UNSAT 上：训练池 63 道 UNSAT 上 F+ 比 D 少 33% CPU。但答案不可在线获得，UNSAT 只占可解题的 12%。
- 偏好随规模反转：分配、着色、随机 3-SAT 的小档偏 F±、大档偏 D。所以在一档学到的“类型 → flag”不能直接外推。
- 在留一家族诊断中，没有越界回退的静态树会把被留出的拉丁方整体送到 F+（0/66 可解）。带回退的类型路由则安全地回到 D。

**未知与局限**：
- 本轮冻结的方法没有取到积木 → F− 这一小块收益（约占开发池 SBS→oracle 空间的 6%）。类型路由在开发验证中把它与因子分解上的折内噪声相抵。一个只针对规划结构的路由是新假说，需要下一轮独立确认。
- 点覆盖家族 M/L 档偏易；job-shop、积木、拉丁方的实例全为 SAT；部分 rand3 L 与 col3 实例三模式都超时。
- 公开集有 38 题 D 超时，其中 35 题三模式都超时。

**结论措辞**：本轮没有发现可靠的细粒度在线预测收益。“廉价结构识别后选 flag”在这些家族上也没有超过始终用 D，因为可识别的稳定偏好几乎只有一个家族。

## English summary

**Question.** Which SAT problem structures have stable preferences among CaDiCaL's D / F+ / F− modes? Can such a preference be recognised cheaply from the CNF, and does it transfer to unseen instances, sizes, encodings and families?

**What was done.**
- Eight generated families with three size levels each, 768 instances in total (discovery 288, development 240, confirmation 240):
  - three bridge families: random 3-SAT, graph 3-colouring, coupled assignment;
  - five new families: vertex cover with a cardinality bound, job-shop scheduling, blocks-world planning, multiplier factoring, quasigroup completion.
- 120 public instances from 10 sources: 60 from the 2022–2026 competitions, and 30 GBD families unrelated to the generated ones.
- Diagnostics on 48 base problems: four semantically equivalent alternative encodings, global literal flips, variable permutations and solver seeds.
- About 4970 runs, each capped at 3600 CPU s, every answer independently verified. In addition, 1838 SAT models from generated instances were decoded and checked against the problem itself, all passing. Total compute was 958 CPU-hours, with no aggregate cap.

**Measured.**
1. **D is the broadly reliable default.**

   | Panel | D | F− | F+ |
   |---|---:|---:|---:|
   | Training pool (528) | 505 | 452 | 394 |
   | Confirmation (240) | 228 | 204 | 180 |
   | Public (120) | 82 | 78 | 75 |

   F± never solved a pool instance that D missed, and the per-instance oracle is only 13% below D.
2. **Only one family has a reproducible preference: blocks-world planning → F−.** F− is 18% cheaper than D on the pool, and 24.1% [13.9, 32.6] cheaper on 30 new confirmation instances.
3. **Severe F± failures reproduce.**
   - F+ times out on every minimal-encoding quasigroup instance.
   - F± time out on most vertex-cover instances.
   - F± are several to more than ten times slower on job-shop and large assignment instances.
4. **The encoding alone can decide the preference.** With the extended quasigroup encoding, F+ becomes as fast as D. The time-indexed job-shop encoding is about 100× slower than the order encoding, and the winner changes with it.
5. **A large share of per-instance preferences is noise.** The fastest mode survives a variable permutation on 31/48 bases and a solver-seed change on 34/48.
6. **No method beat fixed D in nested grouped CV on the pool.**

   | Method | vs fixed D |
   |---|---:|
   | Static tree | −0.2% |
   | Type router with out-of-range fallback | −0.7% |
   | Static + D-prefix reader | −1.6% (−1.5% vs its matched content-free control) |
   | Frozen v10 strategy | 44 fewer solved |

   The registered rule therefore froze fixed D as the main strategy. The frozen structural control turned out to be a single-leaf "D" tree.
7. **Confirmation.**
   - The main strategy equals the development SBS, so the selection gain is zero by construction, and the "≥ 5% with lower CI bound > 0" criterion is not met.
   - The structural control differs from D only by re-run timing noise and about 0.2 s of static analysis.
   - The v10 strategy solves 25 fewer confirmation and 4 fewer public instances than D.

**Correlational, hypotheses and open questions.**
- F± gains concentrate on UNSAT instances: F+ is 33% cheaper than D on the 63 UNSAT pool instances. The answer is not available online, though.
- Preferences flip with size: small levels lean towards F±, large levels towards D.
- A planning-specific router is a new hypothesis that needs fresh confirmation.

**Conclusion.** There is no reliable gain from fine-grained online prediction, and on these families cheap structural routing does not beat always-D, because stable recognisable preferences exist for essentially one family.

## 图（reports/broad_scope_v11/）

1. [fig1_pool_cells.png](fig1_pool_cells.png)：训练池每家族 × 档的三模式成本与超时数。
2. [fig2_family_flag_vs_oracle.png](fig2_family_flag_vs_oracle.png)：家族固定 flag 与 SBS、oracle 的对比（事后、样本内）。
3. [fig3_encoding_stability.png](fig3_encoding_stability.png)：替代编码、翻转、重排与 seed 下最快模式保持不变的比例。
4. [fig4_cv_methods.png](fig4_cv_methods.png)：嵌套 CV 方法比较与留一家族诊断。
5. [fig5_confirm_gains.png](fig5_confirm_gains.png)：确认 240 题按家族的已解数，以及相对 D 的 CPU 变化。
6. [fig6_public.png](fig6_public.png)：公开集解题曲线（未见家族、相关家族、比赛年份）。

## 交付清单

| 文件 | 内容 |
|---|---|
| [SOURCE_AUDIT.md](SOURCE_AUDIT.md) | 来源、生成器、曝光与家族关系 |
| [协议](../../docs/BROAD_SCOPE_PROTOCOL_V11.md)、[PILOT.md](PILOT.md) | 规则、探索、pilot 与清单冻结（偏离 1–7） |
| [BASELINES.md](BASELINES.md) | 三模式基线、oracle 界、集中度 |
| [ENCODING.md](ENCODING.md) | 编码、变号、重排与 seed |
| [STRUCTURE_MAP.md](STRUCTURE_MAP.md) | 偏好地图 |
| [SELECTION.md](SELECTION.md) | 方法比较与冻结 |
| [VALIDATION.md](VALIDATION.md) | 确认、公开与部署核对 |
| [COMPUTE.md](../../results/broad_scope_v11/COMPUTE.md) | 958.4 核时，其中 54.2 核时是 disc_dev 改为并行时主动取消、重跑的部分 |

## 复现

下面的命令已实际执行过，输出原样列出：

```bash
source /mnt/data/shared/config/env.sh; export GENESIS_IMAGE_VER=1_26
gs-srun --partition=cpu-mid --nodes=1 --ntasks=1 --cpus-per-task=4 --mem=32G --time=00:30:00 \
  bash -c "cd ~/workspace/online-tuning-forcephase && scripts/broad_scope_v11/repro.sh"
# regenerated v11-jssp-S-s3000 sha256 match True vars 45892 clauses 779828
# frozen main: fixed D | structural: configs/broad_scope_v11/frozen/structural.json
# main (fixed D) exit 10 answer SAT tree_cpu 0.51 verified True checkmodel semantic True
# structural wrapper exit 10 answer SAT tree_cpu 0.71 verified True checkmodel semantic True path reader action D static ok 0.156 s
```

分析可以从运行记录完整重算，使用分析 venv `/mnt/data/zhaofeng/venvs/online-tuning-forcephase`：

```bash
$FP_PY scripts/broad_scope_v11/baselines.py
$FP_PY scripts/broad_scope_v11/selection.py cv
$FP_PY scripts/broad_scope_v11/validation.py --panel confirm
$FP_PY scripts/broad_scope_v11/validation.py --panel public
$FP_PY scripts/broad_scope_v11/figures.py
```
