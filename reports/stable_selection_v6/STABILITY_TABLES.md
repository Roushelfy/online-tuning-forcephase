# R1 稳定性表（由 `scripts/stable_selection_v6/r1_stability.py` 生成）

诊断 30 题 × 3 动作 × seed 0/1/2；缺失运行 0。复用：seed 1 中与 v5 seed 重复相同的运行直接复用（`origin_exp = v5_seed1`），其余为 v6 新跑。

## 1. 按原优势组

| 原组 | n | 小面板内稳定、且与原标签同向 | 稳定为其他动作 | 不稳定 | 三个 seed 都赢（margin 1.5） | 原赢家在 seed 1/2 都仍是最快 |
|---|---:|---:|---:|---:|---:|---:|
| D 优势 | 10 | 7 | 0 | 3 | 7 | 8 |
| F+ 优势 | 10 | 8 | 0 | 2 | 5 | 9 |
| F− 优势 | 10 | 9 | 0 | 1 | 8 | 9 |

原 F+/F− 优势题中稳定保留的合计比例：17/20 = 85%（协议收缩规则阈值 30%：未触发）。

## 2. 赢家转换（seed 1 与 seed 2 合计 60 个“题 × seed”）

| 原组 \ 新 seed 下 | D 优势 | F+ 优势 | F− 优势 | 接近 | 全部超时 |
|---|---:|---:|---:|---:|---:|
| D 优势 | 15 | 0 | 0 | 3 | 2 |
| F+ 优势 | 2 | 13 | 0 | 5 | 0 |
| F− 优势 | 2 | 0 | 17 | 1 | 0 |

超时转换（相对 seed 0）：D solved->timeout 2；D timeout->solved 8；F+ solved->timeout 0；F+ timeout->solved 0；F− solved->timeout 0；F− timeout->solved 0。

## 3. 逐题连续成本（秒；600 = 超时）

| 原组 | 实例 | 家族 | 规模 | D s0/s1/s2 | F+ s0/s1/s2 | F− s0/s1/s2 | 稳定优势 |
|---|---|---|---|---|---|---|---|
| D 优势 | 92c17c00d8 | cryptography | small | 1/1/21 | TO/TO/TO | TO/TO/TO | D |
| D 优势 | fca71c2020 | edge-matching | mid | 15/120/217 | TO/TO/TO | 147/149/148 | — |
| D 优势 | 474e9594ec | fixed-shape-random | small | 4/294/214 | TO/TO/TO | TO/TO/TO | D |
| D 优势 | de7a6b0399 | heule-nol | small | 31/37/47 | TO/TO/TO | TO/TO/TO | D |
| D 优势 | 2d0c041c0f | hgen | small | 19/17/6 | TO/TO/TO | TO/TO/TO | D |
| D 优势 | 3cff6c97a5 | planning | mid | 5/8/7 | 75/76/77 | 20/20/20 | D |
| D 优势 | ddd3b43476 | profitable-robust-production | large | 11/27/9 | 44/40/40 | 18/19/19 | — |
| D 优势 | 33bcf82677 | scheduling | large | 44/98/38 | TO/TO/TO | TO/TO/TO | D |
| D 优势 | 9de6ddddf7 | set-covering | mid | 6/6/5 | TO/TO/TO | TO/TO/TO | D |
| D 优势 | 5ce7d13744 | station-repacking | large | 300/TO/TO | TO/TO/TO | TO/TO/TO | — |
| F+ 优势 | 945d67baeb | argumentation | small | TO/TO/TO | 181/180/180 | TO/TO/TO | F+ |
| F+ 优势 | 18d4124324 | cellular-automata | large | 56/51/66 | 27/27/28 | 59/56/56 | F+ |
| F+ 优势 | e0bf26a752 | cryptography | large | 132/40/51 | 33/32/32 | 188/183/196 | F+ |
| F+ 优势 | 5cae5c0629 | ensemble-computation | mid | TO/TO/290 | 53/52/53 | TO/TO/TO | F+ |
| F+ 优势 | 7d311f620f | hamiltonian | small | TO/TO/TO | 66/66/66 | TO/TO/TO | F+ |
| F+ 优势 | 931621d996 | influence-maximization | mid | 20/17/67 | 2/1/2 | TO/TO/TO | F+ |
| F+ 优势 | e9b4369f9a | multiplier | small | 35/28/15 | 12/12/11 | 42/42/42 | F+ |
| F+ 优势 | 09e0775d2b | ntil | mid | TO/123/TO | 111/110/111 | TO/TO/TO | F+ |
| F+ 优势 | fb0e505b8b | quantum-kochen-specker | mid | 38/34/33 | 25/25/25 | 40/40/41 | — |
| F+ 优势 | 73063c6257 | random-graph-xorsat | small | 242/19/9 | 99/98/98 | TO/TO/TO | — |
| F− 优势 | 2b35377a7b | agile | mid | 115/74/39 | 168/164/163 | 11/11/11 | F− |
| F− 优势 | eca3692344 | brent-equations | large | 8/8/8 | TO/TO/TO | 1/1/1 | F− |
| F− 优势 | 5457c05649 | disagreement-parity | small | TO/TO/TO | TO/TO/TO | 27/27/27 | F− |
| F− 优势 | 65ee6b4961 | lights-out | small | TO/TO/TO | TO/TO/TO | 4/4/4 | F− |
| F− 优势 | e7ee736cb1 | random-circuits | large | 164/148/117 | 192/190/196 | 90/89/92 | F− |
| F− 优势 | ea8a79747c | scheduling | small | TO/16/58 | TO/TO/TO | 239/229/226 | — |
| F− 优势 | 8d31ec9ede | social-golfer | mid | TO/271/162 | TO/TO/TO | 41/40/41 | F− |
| F− 优势 | 9ef9243ff0 | sum-of-3-cubes | mid | 66/278/110 | TO/TO/TO | 0/0/0 | F− |
| F− 优势 | b438fa464c | tensors | small | TO/94/42 | TO/TO/TO | 24/24/24 | F− |
| F− 优势 | bd0b055b89 | trigonometric-functions | large | TO/TO/TO | TO/TO/TO | 287/276/283 | F− |

## 4. 同一搜索的计时重复

F± 关闭了 rephase，不同 seed 下多数是同一搜索（冲突数相等）；这些对就是天然的计时重复。

| 动作 | 与 seed 0 搜索相同的（题 × seed）对 | 其中 ≥ 1 s 的 CPU 比中位 | 5%–95% |
|---|---:|---:|---|
| F+ | 28 | 0.996 | 0.904–1.043 |
| F− | 34 | 0.997 | 0.954–1.033 |
| D | 0 | — | — |

![稳定性](figures/stability.png)

