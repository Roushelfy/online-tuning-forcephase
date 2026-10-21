# lpn_smoke: pre-registered predictions Q1–Q5 (T=10 s)

Instances complete: 24 / 24; missing runs: 0; answered-but-unverified: 0.

Effect = median over instances of log2((c_X+0.1)/(c_D+0.1)) with 95% bootstrap CI; ×ratio in parentheses.

| prediction | effect [95% CI] | verdict |
|---|---|---|
| Q1 implicit+planted: F− vs D | -0.73 [-1.55, +0.21] (×0.60) | not supported (CI includes 0) |
| Q1 (τ_e = 1/5) | -0.73 [-1.55, +0.21] (×0.60) | |
| Q2 paired d = r(explicit) − r(implicit), n=4 | +0.71 [-0.22, +1.59] (×1.63) | not supported (CI includes 0) |
| Q2 explicit+planted: F− vs D | -0.00 [-0.04, +0.05] (×1.00) | |
| Q3 implicitflip+planted: F+ vs D | -0.05 [-0.69, +1.29] (×0.97) | not supported (CI includes 0) |
| Q3 implicitflip+planted: F− vs D (predicted slower) | +0.66 [-0.28, +3.23] (×1.58) | not supported (CI includes 0) |
| Q4 implicit random: F− vs D (planted -0.73) | -0.16 [-0.27, -0.07] (×0.89) | not supported |
| Q4 explicit random: F− vs D (planted -0.00) | +0.00 [-0.01, +0.02] (×1.00) | not supported |
| Q4 implicitflip random: F− vs D (planted +0.66) | -0.08 [-0.38, +0.05] (×0.95) | supported |

Q3 solved counts (implicitflip, planted): `{"D": 4, "Im": 4, "Fm": 4, "Fp": 4, "Im_noR": 4}`

## Q5 (exploratory)

| cell | F− vs I− | F− vs I−/no-R |
|---|---|---|
| implicit/planted | -0.75 [-2.11, -0.02] (×0.60) | -0.58 [-1.23, +0.01] (×0.67) |
| implicit/random | -0.06 [-0.12, +0.02] (×0.96) | -0.03 [-0.21, +0.02] (×0.98) |
| explicit/planted | -0.00 [-0.01, +0.02] (×1.00) | -0.00 [-0.01, +0.02] (×1.00) |
| explicit/random | -0.00 [-0.01, +0.00] (×1.00) | -0.00 [-0.01, +0.00] (×1.00) |
| implicitflip/planted | +0.38 [-0.14, +2.39] (×1.30) | -0.02 [-0.09, +0.95] (×0.99) |
| implicitflip/random | -0.07 [-0.17, -0.02] (×0.95) | -0.00 [-0.20, +0.03] (×1.00) |

## Solved / PAR2 (s) per cell, and median log2 ratio vs D

| cell | n | D | I− | F− | F+ | I−/no-R |
|---|---:|---|---|---|---|---|
| implicit/planted | 4 | 4 / 0.2 | 4 / 0.3 · +0.18 | 4 / 0.1 · -0.73 | 4 / 0.3 · +0.42 | 4 / 0.2 · -0.11 |
| implicit/random | 4 | 4 / 0.5 | 4 / 0.4 · -0.10 | 4 / 0.4 · -0.16 | 4 / 0.4 · -0.07 | 4 / 0.4 · -0.10 |
| explicit/planted | 4 | 4 / 0.0 | 4 / 0.0 · +0.01 | 4 / 0.0 · -0.00 | 4 / 0.0 · +0.00 | 4 / 0.0 · +0.01 |
| explicit/random | 4 | 4 / 0.0 | 4 / 0.0 · +0.00 | 4 / 0.0 · +0.00 | 4 / 0.0 · +0.01 | 4 / 0.0 · +0.01 |
| implicitflip/planted | 4 | 4 / 0.1 | 4 / 0.2 · +0.05 | 4 / 0.4 · +0.66 | 4 / 0.1 · -0.05 | 4 / 0.3 · +0.72 |
| implicitflip/random | 4 | 4 / 0.5 | 4 / 0.4 · -0.06 | 4 / 0.4 · -0.08 | 4 / 0.4 · -0.03 | 4 / 0.4 · -0.08 |

## Solved by size

| cell | n inst | D | I− | F− | F+ | I−/no-R |
|---|---:|---:|---:|---:|---:|---:|
| implicit/planted/n=12 | 2 | 2 | 2 | 2 | 2 | 2 |
| implicit/planted/n=16 | 2 | 2 | 2 | 2 | 2 | 2 |
| implicit/random/n=12 | 2 | 2 | 2 | 2 | 2 | 2 |
| implicit/random/n=16 | 2 | 2 | 2 | 2 | 2 | 2 |
| explicit/planted/n=12 | 2 | 2 | 2 | 2 | 2 | 2 |
| explicit/planted/n=16 | 2 | 2 | 2 | 2 | 2 | 2 |
| explicit/random/n=12 | 2 | 2 | 2 | 2 | 2 | 2 |
| explicit/random/n=16 | 2 | 2 | 2 | 2 | 2 | 2 |
| implicitflip/planted/n=12 | 2 | 2 | 2 | 2 | 2 | 2 |
| implicitflip/planted/n=16 | 2 | 2 | 2 | 2 | 2 | 2 |
| implicitflip/random/n=12 | 2 | 2 | 2 | 2 | 2 | 2 |
| implicitflip/random/n=16 | 2 | 2 | 2 | 2 | 2 | 2 |

## By noise rate

| cell | n inst | D solved | I− solved | F− solved | F+ solved | I−/no-R solved |
|---|---:|---:|---:|---:|---:|---:|
| implicit/planted/tau=1/5 | 4 | 4 | 4 | 4 | 4 | 4 |
| implicit/random/tau=1/5 | 4 | 4 | 4 | 4 | 4 | 4 |
| explicit/planted/tau=1/5 | 4 | 4 | 4 | 4 | 4 | 4 |
| explicit/random/tau=1/5 | 4 | 4 | 4 | 4 | 4 | 4 |
| implicitflip/planted/tau=1/5 | 4 | 4 | 4 | 4 | 4 | 4 |
| implicitflip/random/tau=1/5 | 4 | 4 | 4 | 4 | 4 | 4 |
