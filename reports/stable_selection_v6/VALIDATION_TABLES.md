# R4 验证（冻结后；由 `scripts/stable_selection_v6/v6_evaluate.py --validate` 生成）

55 题、30 个家族组；缺失运行 0。

## 全部（55 题，30 个家族组）

| 策略 | 解出 | PAR2 | 相对 D 的净收益 [95% 家族 cluster 区间] | 偏离 F+/F− | 观察不完整 |
|---|---:|---:|---|---|---:|
| D | 26 | 341.45 | +0.0% [+0.0, +0.0] |  |  |
| F+ | 25 | 362.27 | -6.1% [-19.1, +5.3] |  |  |
| F− | 25 | 350.86 | -2.8% [-16.9, +12.8] |  |  |
| P1|M05（冻结） | 27 | 334.01 | +2.2% [-0.2, +7.0] | 1/3 | 3 |
| 事后最优（不可部署） | 31 | 297.51 | +12.9% [+2.6, +27.7] | | |

## 非 dev 家族（27 题，15 个家族组）

| 策略 | 解出 | PAR2 | 相对 D 的净收益 [95% 家族 cluster 区间] | 偏离 F+/F− | 观察不完整 |
|---|---:|---:|---|---|---:|
| D | 15 | 300.11 | +0.0% [+0.0, +0.0] |  |  |
| F+ | 15 | 322.34 | -7.4% [-33.1, +11.0] |  |  |
| F− | 15 | 303.40 | -1.1% [-32.4, +34.7] |  |  |
| P1|M05（冻结） | 15 | 300.10 | +0.0% [-0.2, +0.2] | 0/2 | 0 |
| 事后最优（不可部署） | 19 | 230.84 | +23.1% [+0.3, +55.1] | | |

## 逐题：策略与 D 成本不同（差 > 1 s）的实例

| 实例 | 家族 | 规模 | 路径 | 动作 | D | F+ | F− | 策略 |
|---|---|---|---|---|---:|---:|---:|---:|
| 032941f5f2 | graceful-production | large | reader | D | 12.6 | 12.4 | 12.1 | 14.9 |
| 048142b604 | graceful-production | large | reader | D | 6.1 | 6.0 | 5.8 | 7.4 |
| 07b7859003 | hardware | small | reader | D | 71.1 | 113.4 | 94.9 | 69.6 |
| 1afa2d7a3d | scheduling | large | reader | D | 17.6 | 600.0 | 9.0 | 15.4 |
| 2e05884137 | planning | large | reader | D | 152.8 | 59.9 | 600.0 | 176.4 |
| 65b1e22536 | hashtable-safety | large | reader | D | 134.9 | 162.4 | 156.1 | 131.1 |
| 761651d4b6 | quantum-kochen-specker | mid | reader | F+ | 600.0 | 216.4 | 600.0 | 236.4 |
| 80bb5209e8 | argumentation | large | reader | D | 6.4 | 6.3 | 6.3 | 8.4 |
| 96a472b1fd | argumentation | large | reader | D | 22.6 | 94.7 | 37.0 | 24.0 |
| 9c5dd2eb0a | ecc-equivalence-checking | large | reader | F− | 8.9 | 9.1 | 8.9 | 10.3 |
| b64f7d56f1 | tree-decomposition | large | reader | D | 51.8 | 600.0 | 600.0 | 50.0 |
| c3de1f05d1 | software-verification | large | reader | D | 126.4 | 142.2 | 140.8 | 121.5 |
| c8e6440436 | miter | large | reader | F− | 69.4 | 8.9 | 14.5 | 15.8 |
| d699355595 | argumentation | large | observation_incomplete | D | 12.5 | 12.6 | 12.3 | 15.6 |
| e2deb375e5 | random-circuits | large | reader | D | 183.0 | 600.0 | 207.0 | 162.8 |
| e8abb9c83e | software-verification | large | reader | D | 169.5 | 280.6 | 600.0 | 173.7 |
| f554b55356 | ecc-equivalence-checking | large | reader | F− | 14.7 | 14.6 | 14.7 | 17.2 |

![验证](figures/validation.png)

