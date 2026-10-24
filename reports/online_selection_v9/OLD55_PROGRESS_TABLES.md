# 原 55 题恢复进度（由 `scripts/online_selection_v9/old55.py` 生成）

更新：2026-10-24 08:56 UTC。阶段：stage1,stage2,old55_r1a,old55_r1b（docs/OLD55_RECOVERY_V9.md）。

| 方法 | v7 结束时完成数 | 现在完成数 | 完整平均 CPU |
|---|---:|---:|---|
| D | 47/55 | 47/55 | null（未全部完成） |
| Fp | 30/55 | 33/55 | null（未全部完成） |
| Fm | 29/55 | 32/55 | null（未全部完成） |
| P1_M05_long | 47/55 | 47/55 | null（未全部完成） |
| oracle（已确定） | 44/55 | 50/55 | null |

## 未完成或 oracle 待定的题

| 实例 | D | F+ | F− | P1_M05_long | oracle 待定动作 |
|---|---|---|---|---|---|
| 07df5e6f67 | 运行中 ≥ 9810 s | 运行中 ≥ 9287 s | 运行中 ≥ 9418 s | 运行中 ≥ 9810 s | D/Fp/Fm |
| 090eefb9bc | 794 s | ≥ 796 s（noncompetitive_bound） | ≥ 796 s（noncompetitive_bound） | 796 s | 已确定 |
| 0a8a4c28d2 | 运行中 ≥ 9802 s | ≥ 300 s（censored） | 44 s | 运行中 ≥ 9802 s | 已确定 |
| 1afa2d7a3d | 18 s | ≥ 300 s（censored） | 9 s | 15 s | 已确定 |
| 1b88068128 | 137 s | ≥ 300 s（censored） | ≥ 300 s（censored） | 136 s | 已确定 |
| 25cc054738 | 1124 s | ≥ 1128 s（noncompetitive_bound） | ≥ 1126 s（noncompetitive_bound） | 1126 s | 已确定 |
| 2e05884137 | 153 s | 60 s | ≥ 301 s（censored） | 176 s | 已确定 |
| 3b0eeddcab | 3808 s | ≥ 3809 s（noncompetitive_bound） | ≥ 3809 s（noncompetitive_bound） | 3809 s | 已确定 |
| 4af0fbe308 | 运行中 ≥ 9814 s | 运行中 ≥ 9284 s | 运行中 ≥ 9341 s | 运行中 ≥ 9814 s | D/Fp/Fm |
| 511a2d8166 | 653 s | ≥ 656 s（noncompetitive_bound） | ≥ 654 s（noncompetitive_bound） | 653 s | 已确定 |
| 5ceb95f596 | 635 s | 542 s | ≥ 637 s（noncompetitive_bound） | 636 s | 已确定 |
| 6543793076 | 1092 s | ≥ 1093 s（noncompetitive_bound） | 760 s | 1094 s | 已确定 |
| 69e34d0f49 | 1074 s | 838 s | ≥ 1076 s（noncompetitive_bound） | 1075 s | 已确定 |
| 761651d4b6 | 438 s | 216 s | ≥ 300 s（censored） | 236 s | 已确定 |
| 7ff8c9781b | 运行中 ≥ 9823 s | 运行中 ≥ 9406 s | 运行中 ≥ 9355 s | 运行中 ≥ 9823 s | D/Fp/Fm |
| 8cfc8e99d3 | 4486 s | ≥ 4489 s（noncompetitive_bound） | ≥ 4489 s（noncompetitive_bound） | 4487 s | 已确定 |
| 9541d12f3e | 1933 s | ≥ 1936 s（noncompetitive_bound） | ≥ 1935 s（noncompetitive_bound） | 1934 s | 已确定 |
| 98c6da979a | 3158 s | ≥ 3161 s（noncompetitive_bound） | 3066 s | 3161 s | 已确定 |
| aa6e6f6771 | 运行中 ≥ 9793 s | 运行中 ≥ 9224 s | 运行中 ≥ 9299 s | 运行中 ≥ 9793 s | D/Fp/Fm |
| ac3e3bb744 | 运行中 ≥ 9797 s | 3597 s | 1772 s | 运行中 ≥ 9797 s | 已确定 |
| af834fd3ce | 运行中 ≥ 9805 s | ≥ 300 s（censored） | 50 s | 运行中 ≥ 9805 s | 已确定 |
| b64f7d56f1 | 52 s | ≥ 301 s（censored） | ≥ 300 s（censored） | 50 s | 已确定 |
| b88d206fb3 | 1002 s | 984 s | ≥ 1005 s（noncompetitive_bound） | 1002 s | 已确定 |
| c7bf3517f4 | 运行中 ≥ 9790 s | 运行中 ≥ 9296 s | 运行中 ≥ 9343 s | 运行中 ≥ 9790 s | D/Fp/Fm |
| c8cde50f32 | 632 s | ≥ 633 s（noncompetitive_bound） | ≥ 634 s（noncompetitive_bound） | 632 s | 已确定 |
| ca6db14aaa | 746 s | 180 s | ≥ 301 s（censored） | 747 s | 已确定 |
| dbbcaa7797 | 5057 s | ≥ 5059 s（noncompetitive_bound） | ≥ 5059 s（noncompetitive_bound） | 5058 s | 已确定 |
| e2deb375e5 | 183 s | ≥ 300 s（censored） | 207 s | 163 s | 已确定 |
| e8abb9c83e | 170 s | 281 s | ≥ 300 s（censored） | 174 s | 已确定 |
| ed410c758e | 1120 s | ≥ 1122 s（noncompetitive_bound） | ≥ 1122 s（noncompetitive_bound） | 1120 s | 已确定 |
