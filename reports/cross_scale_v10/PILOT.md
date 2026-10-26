# v10 试采样记录（72 题，只跑 D）

协议第 3.3 节。数据：`$FP_DATA/runs/cross_scale_v10/pilot`；决定：[scales.json](../../configs/cross_scale_v10/scales.json)。72 个运行全部完成并验证；`v10p-rand3-X-5` 最终用时 1511.6 s（UNSAT），与决定时使用的下界 1431 s 一致：规则结果不变。

| 类型 | 档 | 参数 | 6 题 D CPU（s，升序） | 几何平均 g | 规则 |
|---|---|---:|---|---:|---|
| rand3 | S | 220 | 0.02, 0.07, 0.30, 0.37, 0.66, 3.03 | 0.26 | kept (in band) |
| rand3 | M | 290 | 0.45, 0.79, 20.05, 21.49, 22.21, 96.67 | 8.30 | kept (in band) |
| rand3 | L | 340 | 14.41, 142.13, 142.21, 461.95, 506.31, 558.20 | 183.37 | kept (in band) |
| rand3 | X | 360 | 0.52, 0.53, 0.54, 5.66, 700.83, 1491.36 | 9.81 | pilot max D 1491 s > 1200 s -> one grid step down: 350 |
| col3 | S | 350 | 0.02, 0.04, 0.11, 0.46, 1.38, 1.43 | 0.21 | kept (in band); order violated -> candidate kept |
| col3 | M | 450 | 0.05, 0.23, 0.42, 0.51, 0.92, 1.04 | 0.37 | moved: fitted param for 3.0 s = 546.6 -> grid 550; order violated -> candidate kept |
| col3 | L | 550 | 0.09, 0.51, 0.99, 28.79, 55.95, 74.67 | 4.23 | kept (in band); order violated -> candidate kept |
| col3 | X | 625 | 1.23, 1.25, 1.47, 6.45, 6.78, 679.69 | 6.38 | kept (pilot max D within coverage bound); order violated -> candidate kept |
| assign2 | S | 250 | 0.11, 0.30, 0.34, 0.84, 1.03, 1.39 | 0.49 | kept (in band) |
| assign2 | M | 350 | 1.39, 1.95, 2.56, 6.30, 6.35, 7.87 | 3.60 | kept (in band) |
| assign2 | L | 450 | 5.70, 5.85, 7.79, 8.82, 12.26, 14.42 | 8.60 | kept (in band) |
| assign2 | X | 550 | 10.78, 18.27, 54.63, 55.04, 58.59, 93.99 | 38.51 | kept (pilot max D within coverage bound) |

最终规模：rand3 n = 220 / 290 / 340，外推 350；col3 n = 350 / 450 / 550，外推 625；assign2 T = 250 / 350 / 450，外推 550。

- 只运行 D，没有运行 F±，也没有用答案或任何动作的胜负。
- 生成正确性：72 题都进入了真实搜索（S 档最少 63 次冲突，其余档都在千次以上），SAT 与 UNSAT 都有。
