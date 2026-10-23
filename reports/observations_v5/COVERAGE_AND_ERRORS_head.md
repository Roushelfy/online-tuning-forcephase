# V0：旧观测的真实覆盖、旧选择器的损失来源，以及计时和标签检查

本报告由 `scripts/observations_v5/v0_coverage.py`（第 1–4 节，只用 v4 已有记录）和 `scripts/observations_v5/v1_engineering.py`（第 5 节，V1 新跑的 seed 重复）生成，正文是对生成表格的解读。v4 的 12 个交叉验证候选在 v4 代码、折和 κ 下**逐个精确复现**（OOF PAR2 与 [v4 SELECTOR_CV](../three_way/SELECTOR_CV.md) 一致），因此下面的逐题分解与 v4 报告同源。

## 1. 旧的 28 + 24 个指标登记

| v4 指标 | 实际代码含义 | 与 v5 候选库的关系 |
| --- | --- | --- |
| `p_log_vars`、`p_log_clauses`、`p_cv_ratio`、`p_len_*`、`p_unit/bin/ter/len4p/len10p_frac` | 原式规模与子句长度分布（`tools/cnfprofile.c`） | 背景特征（S28），每个 v5 观察包都带上 |
| `p_pos_lit_frac` | 全局正文字比例（不加权） | A01 的不加权版本；A01 改为短子句加权，并在根传播残余式上重算（C01/C02） |
| `p_allpos_cls_frac`、`p_allneg_cls_frac` | 全正 / 全负子句比例 = 全 0 / 全 1 赋值下违反的子句比例 | **就是 A04 在原式上的不加权版本**；v5 只把加权版和残余式版算作新观测 |
| `p_binpos_frac`、`p_binneg_frac` | 二元子句的符号组成 | A07 / D01 的背景；v5 新增 AMO/EO 组覆盖率与蕴含图结构 |
| `p_horn_frac`、`p_antihorn_frac` | Horn / 反 Horn 子句比例 | A08 的已有部分；A08 的新内容（集中位置）本轮未做 |
| `p_var_bal_mean/std`、`p_var_absbal_mean`、`p_var_posmaj/negmaj_frac` | 每变量出现次数的极性平衡 | A09 的均值部分；v5 新增分位数、两端质量与熵，A02 改为 JW 加权 |
| `p_var_purepos/pureneg_frac` | 纯变量比例 | A11 的已有部分；v5 新增剔除纯变量与根固定变量后的平衡 |
| `p_occ_mean/cv/max_rel` | 出现次数分布 | A03 的背景；v5 新增高频变量的极性 |
| `q_started`、`q_log_conflicts/decisions/props`、`q_conf_per_sec_log`、`q_dec_per_conf`、`q_props_per_dec_log` | D 一个臂的进度 | E01/E02/E05 的单动作基线；v5 新增 F+、F− 两个臂与三者之差 |
| `q_fixed_frac`、`q_elim_frac`、`q_learned_len` | 根固定、消元、学习子句长度 | E09 / C03 / E06 的单动作基线 |
| `q_chrono_frac`、`q_restarts_per_kconf` | chrono 回退率、重启率 | F10 的总比例；v5 按回退类型分开统计 glue 与正文字比例 |
| `q_neg_dec_frac`、`q_native_pos_frac`、`q_target/saved/fallback_src_frac` | D 下自由决策的符号与相位来源 | F03 的决策部分（**旧值，不算新观测**）；v5 新增传播与根级赋值的符号 |
| `q_has_checkpoint`、`q_cp_glue_mean/low_frac`、`q_cp_stable_frac`、`q_cp_trail_frac`、`q_cp_saved_neg_frac`、`q_cp_target_neg_frac` | 1,000 次冲突处的 checkpoint 状态 | F04/E06/E07/E11 的基线；v4 没有 saved 与 target 之间的分歧率，也没有正确的 saved 翻转率（v1 的 `x_saved_flip_frac` 已失效，v4 也未使用） |

结论：v4 实际测过的是原式的全局计数，以及 D 一个臂的进度和相位来源。传播、残余式、结构、三动作相对反应、学习子句极性，以及正确的相位轨迹，都**没有测过**。

## 2. 覆盖：0.1 秒探测的大部分特征其实没有被观察到

见第 A 节表。在 v4 选中的 0.1 s 预算下：

- dev 中 **30% 的实例还没有进入搜索**（没有冲突），24 个试跑特征中 16 个对这些实例缺失；
- 只有 45% 达到 1,000 次冲突、写出 checkpoint，所以 6 个 `q_cp_*` 特征有 55% 缺失；
- 只有 55% 进入 stable 模式。进入 stable、出现 target 决策和发生过 rephase 三列完全相同：这三件事都在约 1,000 次冲突时首次发生。

v4 的树把缺失编码成哨兵值 −10，logistic 用中位数填补，两者都没有缺失指示变量。`q_target_src_frac = 0` 往往只表示“还没进入 stable”，即机制尚未触发，而不是“target 不起作用”。

2 秒预算下覆盖率已达 88–94%，但 v4 中 2 秒的三个候选也都不如 D（−2.1% 到 −5.4%）。所以**预算太短是 0.1 秒选择器的一部分问题，但不是唯一问题**：覆盖足够时，单个 D 臂的这些特征仍然没有带来收益。

## 3. 损失来自少数“把 D 可解题送去超时”的错误偏离

见第 B 节表。12 个候选全部呈现同一结构：

- 正确偏离 D 共节省 6–14 秒/题；
- 错误偏离 D 共损失 15–38 秒/题；
- 观察开销合计 ≤ 1.3 秒/题，相比之下很小；
- 每个候选都有 12–29 个实例从“D 解出”变成“超时”，只有 4–11 个实例从“D 超时”变成“解出”。

以两个 v4 冻结流程为例：static-logreg 与 probe0.1-logreg 的损失都集中在少数实例上，**前 10 大损失占全部损失的 78–80%**，而且这 10 个**全部**是 D 能解、所选动作超时的情况。微秒级、亚秒级的倍数差异贡献很小。旧 test99 上的历史分解（第 E 节）结构相同：错误偏离的损失约是正确偏离收益的 1.5–2.5 倍。

**对 v5 的含义**：首要问题是“没有把握时不要偏离 D”。读出器应当以绝对秒数的 regret 为目标，并带一个默认回退门（M01/M02/M04），而不只是增加特征或模型容量。

## 4. logistic 的权重并不是主要问题

见第 C 节。v4 logistic 的 log 倍数权重与“第二名 − 第一名”的绝对秒数在这个面板上高度同序（Spearman ρ = 0.86）。绝对差小于 10 秒的实例占权重的 7.3%，但只占绝对差的 0.6%，有偏差，但不大。v4 的成本树本来就直接最小化模拟成本。因此不能说“成本敏感从未做过”。v4 两种读出器共同缺少的是：

- 分别估计 F+、F− 相对 D 的净收益；
- 证据不足时保留 D 的门槛；
- 把超时损失（最多 600 − t_D 秒）放进目标。

## 5. 标签与计时

- **优势组 margin**（第 D 节）：
  - 124 个优势题中，26 个的 margin 在 1.5–2 之间。这些标签对计时噪声较敏感；
  - 64 个是“只有赢家解出”（exclusive），这类标签不会因计时噪声翻转；
  - F− 优势组里有 4 题赢家在 1 秒内解出（微小题）。
- **计时重复**：
  - v4 test 上有 76 对“wrapper 正式求解 vs 同动作固定运行”：同一个二进制、同样的参数和 seed，因此是确定性搜索的重复。
  - CPU 比值中位数 0.984，5%–95% 分位为 0.928–1.079。
  - 所以 margin 小于约 1.1 的优劣可能是计时噪声；协议的 margin 门槛 1.5 远大于这个范围。
- **seed 敏感性**：上面的计时重复不能反映 seed 敏感性，由 V1 在工程面板上用 `--seed=1` 重跑来补充（第 6 节）。

