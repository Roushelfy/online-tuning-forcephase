# lpn_sparse_main: pre-registered predictions Q1–Q5 (T=120 s)

Instances complete: 480 / 480; missing runs: 0; answered-but-unverified: 0.

Effect = median over instances of log2((c_X+0.1)/(c_D+0.1)) with 95% bootstrap CI; ×ratio in parentheses.

| prediction | effect [95% CI] | verdict |
|---|---|---|
| Q1 implicit+planted: F− vs D | -2.44 [-3.54, -1.60] (×0.18) | supported |
| Q1 (τ_e = 1/4) | -1.28 [-2.46, +0.00] (×0.41) | |
| Q1 (τ_e = 1/5) | -3.57 [-5.30, -2.44] (×0.08) | |
| Q2 paired d = r(explicit) − r(implicit), n=80 | +2.23 [+1.17, +3.32] (×4.68) | supported |
| Q2 explicit+planted: F− vs D | -0.23 [-0.42, +0.03] (×0.85) | |
| Q3 implicitflip+planted: F+ vs D | -2.17 [-3.62, -1.39] (×0.22) | supported |
| Q3 implicitflip+planted: F− vs D (predicted slower) | +0.00 [+0.00, +0.00] (×1.00) | not supported (CI includes 0) |
| Q4 implicit random: F− vs D (planted -2.44) | +0.00 [+0.00, +0.00] (×1.00) | vacuous (nothing solved on random) |
| Q4 explicit random: F− vs D (planted -0.23) | -0.05 [-0.10, -0.00] (×0.96) | not supported |
| Q4 implicitflip random: F− vs D (planted +0.00) | +0.00 [+0.00, +0.00] (×1.00) | vacuous (nothing solved on random) |

Q3 solved counts (implicitflip, planted): `{"D": 19, "Im": 16, "Fm": 0, "Fp": 56, "Im_noR": 0}`

## Q5 (exploratory)

| cell | F− vs I− | F− vs I−/no-R |
|---|---|---|
| implicit/planted | -2.47 [-3.57, -1.74] (×0.18) | -1.42 [-2.44, -0.04] (×0.37) |
| implicit/random | +0.00 [+0.00, +0.00] (×1.00) | +0.00 [+0.00, +0.00] (×1.00) |
| explicit/planted | -0.15 [-0.49, +0.08] (×0.90) | +0.05 [-0.33, +0.16] (×1.03) |
| explicit/random | -0.04 [-0.07, -0.01] (×0.97) | +0.00 [-0.03, +0.02] (×1.00) |
| implicitflip/planted | +0.00 [+0.00, +0.00] (×1.00) | +0.00 [+0.00, +0.00] (×1.00) |
| implicitflip/random | +0.00 [+0.00, +0.00] (×1.00) | +0.00 [+0.00, +0.00] (×1.00) |

## Solved / PAR2 (s) per cell, and median log2 ratio vs D

| cell | n | D | I− | F− | F+ | I−/no-R |
|---|---:|---|---|---|---|---|
| implicit/planted | 80 | 25 / 174.3 | 22 / 181.5 · +0.00 | 61 / 71.2 · -2.44 | 1 / 237.0 · +0.00 | 38 / 136.6 · +0.00 |
| implicit/random | 80 | 0 / 240.0 | 0 / 240.0 · +0.00 | 0 / 240.0 · +0.00 | 0 / 240.0 · +0.00 | 0 / 240.0 · +0.00 |
| explicit/planted | 80 | 80 / 2.4 | 80 / 2.3 · -0.01 | 80 / 2.0 · -0.23 | 80 / 2.3 · -0.13 | 80 / 2.1 · -0.19 |
| explicit/random | 80 | 80 / 4.4 | 80 / 4.4 · -0.01 | 80 / 4.2 · -0.05 | 80 / 3.8 · -0.12 | 80 / 4.2 · -0.06 |
| implicitflip/planted | 80 | 19 / 191.8 | 16 / 197.3 · +0.00 | 0 / 240.0 · +0.00 | 56 / 86.4 · -2.17 | 0 / 240.0 · +0.00 |
| implicitflip/random | 80 | 0 / 240.0 | 0 / 240.0 · +0.00 | 0 / 240.0 · +0.00 | 0 / 240.0 · +0.00 | 0 / 240.0 · +0.00 |

## Solved by size

| cell | n inst | D | I− | F− | F+ | I−/no-R |
|---|---:|---:|---:|---:|---:|---:|
| implicit/planted/n=24 | 20 | 14 | 12 | 20 | 1 | 19 |
| implicit/planted/n=32 | 20 | 5 | 3 | 19 | 0 | 10 |
| implicit/planted/n=40 | 20 | 3 | 3 | 14 | 0 | 5 |
| implicit/planted/n=48 | 20 | 3 | 4 | 8 | 0 | 4 |
| implicit/random/n=24 | 20 | 0 | 0 | 0 | 0 | 0 |
| implicit/random/n=32 | 20 | 0 | 0 | 0 | 0 | 0 |
| implicit/random/n=40 | 20 | 0 | 0 | 0 | 0 | 0 |
| implicit/random/n=48 | 20 | 0 | 0 | 0 | 0 | 0 |
| explicit/planted/n=24 | 20 | 20 | 20 | 20 | 20 | 20 |
| explicit/planted/n=32 | 20 | 20 | 20 | 20 | 20 | 20 |
| explicit/planted/n=40 | 20 | 20 | 20 | 20 | 20 | 20 |
| explicit/planted/n=48 | 20 | 20 | 20 | 20 | 20 | 20 |
| explicit/random/n=24 | 20 | 20 | 20 | 20 | 20 | 20 |
| explicit/random/n=32 | 20 | 20 | 20 | 20 | 20 | 20 |
| explicit/random/n=40 | 20 | 20 | 20 | 20 | 20 | 20 |
| explicit/random/n=48 | 20 | 20 | 20 | 20 | 20 | 20 |
| implicitflip/planted/n=24 | 20 | 11 | 9 | 0 | 20 | 0 |
| implicitflip/planted/n=32 | 20 | 2 | 3 | 0 | 16 | 0 |
| implicitflip/planted/n=40 | 20 | 3 | 3 | 0 | 14 | 0 |
| implicitflip/planted/n=48 | 20 | 3 | 1 | 0 | 6 | 0 |
| implicitflip/random/n=24 | 20 | 0 | 0 | 0 | 0 | 0 |
| implicitflip/random/n=32 | 20 | 0 | 0 | 0 | 0 | 0 |
| implicitflip/random/n=40 | 20 | 0 | 0 | 0 | 0 | 0 |
| implicitflip/random/n=48 | 20 | 0 | 0 | 0 | 0 | 0 |

## By noise rate

| cell | n inst | D solved | I− solved | F− solved | F+ solved | I−/no-R solved |
|---|---:|---:|---:|---:|---:|---:|
| implicit/planted/tau=1/4 | 40 | 12 | 8 | 27 | 1 | 16 |
| implicit/planted/tau=1/5 | 40 | 13 | 14 | 34 | 0 | 22 |
| implicit/random/tau=1/4 | 40 | 0 | 0 | 0 | 0 | 0 |
| implicit/random/tau=1/5 | 40 | 0 | 0 | 0 | 0 | 0 |
| explicit/planted/tau=1/4 | 40 | 40 | 40 | 40 | 40 | 40 |
| explicit/planted/tau=1/5 | 40 | 40 | 40 | 40 | 40 | 40 |
| explicit/random/tau=1/4 | 40 | 40 | 40 | 40 | 40 | 40 |
| explicit/random/tau=1/5 | 40 | 40 | 40 | 40 | 40 | 40 |
| implicitflip/planted/tau=1/4 | 40 | 7 | 5 | 0 | 25 | 0 |
| implicitflip/planted/tau=1/5 | 40 | 12 | 11 | 0 | 31 | 0 |
| implicitflip/random/tau=1/4 | 40 | 0 | 0 | 0 | 0 | 0 |
| implicitflip/random/tau=1/5 | 40 | 0 | 0 | 0 | 0 | 0 |
