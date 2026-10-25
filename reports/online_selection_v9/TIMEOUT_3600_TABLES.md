# 3600 CPU 秒视图（由 `scripts/online_selection_v9/timeout_view.py` 生成）

按 [RUN_TIMEOUT_APPLICATION.md](../../docs/RUN_TIMEOUT_APPLICATION.md) 第 4 节：已解 = 经验证的完成且进程树 CPU ≤ 3600 s；超时 = 没有这样的完成，且有实际运行到 ≥ 3600 s；不可重建 = 只有低于 3600 s 的下界。不用 3600 s 代替完成时间，不算 PAR2。

## v7 55-instance panel（55 题；答案已知：SAT 28，UNSAT 24，未知 3）

| 方法 | 3600 s 内已解 | 其中 SAT / UNSAT | 超时 | 不可重建 |
|---|---:|---|---:|---:|
| D | 42/55 | 25 / 17 | 13 | 0 |
| Fp | 32/55 | 15 / 17 | 9 | 14 |
| Fm | 31/55 | 17 / 14 | 9 | 15 |
| P1_M05_long | 42/55 | 25 / 17 | 13 | 0 |

- 至少一个固定动作在 3600 s 内解出：46/55。
- 次要描述（各方法都在 3600 s 内解出的 23 题，存在筛选偏差）：平均 CPU D 220.1 s，Fp 194.3 s，Fm 190.5 s，P1_M05_long 218.3 s。
- 超时清单：D: 07df5e6f6742, 0a8a4c28d272, 0ef0d91d378e, 3b0eeddcabf3, 4af0fbe3087b, 7ff8c9781b3a, 8cfc8e99d31b, aa6e6f67719c, ac3e3bb744e2, af834fd3ce15, c7bf3517f47d, d5b11b0b73eb, dbbcaa779714；Fp: 07df5e6f6742, 3b0eeddcabf3, 4af0fbe3087b, 7ff8c9781b3a, 8cfc8e99d31b, aa6e6f67719c, c7bf3517f47d, d5b11b0b73eb, dbbcaa779714；Fm: 07df5e6f6742, 3b0eeddcabf3, 4af0fbe3087b, 7ff8c9781b3a, 8cfc8e99d31b, aa6e6f67719c, c7bf3517f47d, d5b11b0b73eb, dbbcaa779714；P1_M05_long: 07df5e6f6742, 0a8a4c28d272, 0ef0d91d378e, 3b0eeddcabf3, 4af0fbe3087b, 7ff8c9781b3a, 8cfc8e99d31b, aa6e6f67719c, ac3e3bb744e2, af834fd3ce15, c7bf3517f47d, d5b11b0b73eb, dbbcaa779714。

## holdout（270 题；答案已知：SAT 186，UNSAT 84，未知 0）

| 方法 | 3600 s 内已解 | 其中 SAT / UNSAT | 超时 | 不可重建 |
|---|---:|---|---:|---:|
| D | 270/270 | 186 / 84 | 0 | 0 |
| Fp | 270/270 | 186 / 84 | 0 | 0 |
| Fm | 270/270 | 186 / 84 | 0 | 0 |
| W_ref | 270/270 | 186 / 84 | 0 | 0 |

- 至少一个固定动作在 3600 s 内解出：270/270。
- 次要描述（各方法都在 3600 s 内解出的 270 题，存在筛选偏差）：平均 CPU D 57.9 s，Fp 31.4 s，Fm 34.5 s，W_ref 29.1 s。

## extrapolation（90 题；答案已知：SAT 74，UNSAT 16，未知 0）

| 方法 | 3600 s 内已解 | 其中 SAT / UNSAT | 超时 | 不可重建 |
|---|---:|---|---:|---:|
| D | 82/90 | 72 / 10 | 8 | 0 |
| Fp | 79/90 | 65 / 14 | 11 | 0 |
| Fm | 82/90 | 69 / 13 | 8 | 0 |
| W_ref | 78/90 | 65 / 13 | 12 | 0 |

- 至少一个固定动作在 3600 s 内解出：86/90。
- 次要描述（各方法都在 3600 s 内解出的 74 题，存在筛选偏差）：平均 CPU D 130.7 s，Fp 334.4 s，Fm 276.2 s，W_ref 250.1 s。
- 超时清单：D: v9x-assign2-X2-03, v9x-assign2-X2-13, v9x-rand3-X2-02, v9x-rand3-X2-03, v9x-rand3-X2-04, v9x-rand3-X2-07, v9x-rand3-X2-08, v9x-rand3-X2-14；Fp: v9x-assign2-X2-02, v9x-assign2-X2-03, v9x-assign2-X2-06, v9x-assign2-X2-09, v9x-assign2-X2-10, v9x-assign2-X2-11, v9x-assign2-X2-13, v9x-assign2-X2-14, v9x-rand3-X2-03, v9x-rand3-X2-10, v9x-rand3-X2-14；Fm: v9x-assign2-X2-02, v9x-assign2-X2-03, v9x-assign2-X2-04, v9x-assign2-X2-13, v9x-assign2-X2-14, v9x-rand3-X2-03, v9x-rand3-X2-07, v9x-rand3-X2-14；W_ref: v9x-assign2-X2-02, v9x-assign2-X2-03, v9x-assign2-X2-06, v9x-assign2-X2-09, v9x-assign2-X2-10, v9x-assign2-X2-11, v9x-assign2-X2-13, v9x-assign2-X2-14, v9x-rand3-X2-03, v9x-rand3-X2-07, v9x-rand3-X2-10, v9x-rand3-X2-14。

## external（60 题；答案已知：SAT 51，UNSAT 9，未知 0）

| 方法 | 3600 s 内已解 | 其中 SAT / UNSAT | 超时 | 不可重建 |
|---|---:|---|---:|---:|
| D | 60/60 | 51 / 9 | 0 | 0 |
| Fp | 60/60 | 51 / 9 | 0 | 0 |
| Fm | 60/60 | 51 / 9 | 0 | 0 |
| W_ref | 60/60 | 51 / 9 | 0 | 0 |

- 至少一个固定动作在 3600 s 内解出：60/60。
- 次要描述（各方法都在 3600 s 内解出的 60 题，存在筛选偏差）：平均 CPU D 0.5 s，Fp 0.5 s，Fm 0.4 s，W_ref 0.7 s。

