# MSA ground-fit moments

This page explains how the plugin computes the MSA ion moments: density, core temperature and effective temperature. The **Inspector** tab shows each step on real records.

## Why fit on the ground

The MSA L2pre files carry onboard moment variables, but they are empty for the archived flybys: the flight computation was misconfigured. So the plugin rebuilds the moments from the energy spectra, by fitting model distributions to them. The method follows the LPP internship report by Diane Kara Youssef (2026).

## Input data

The plugin reads one L2pre variable per species from the LPP archive, through Speasy:

| Species | Variable | Mass A (u) | Charge q |
|---|---|---|---|
| H⁺ | `diff_dir_en_flux_h_plus` | 1.00728 | 1 |
| He²⁺ (alphas) | `diff_dir_en_flux_alphas` | 4.0026 | 2 |
| Heavies | `diff_dir_en_flux_heavies` | 16 (O⁺ proxy) | 1 |
| Total | `diff_dir_en_flux_total` | 1.00728 (proton equivalent) | 1 |

Each record is a differential directional energy flux F, in cm⁻² s⁻¹ sr⁻¹ eV⁻¹, on 64 energy steps. When a day has several reprocessed versions of the same file, only the newest is used.

The energy table is in volts, that is energy per charge. An ion of charge q at E volts has a kinetic energy of q·E eV. Everything below uses that kinetic energy, so the alphas see twice the table energies.

## From flux to phase-space density

The models describe the phase-space density f, in s³ m⁻⁶. Each flux point is converted with:

**f = m² F / (2 E²) × 10⁴**

where m is the ion mass in kg and E the kinetic energy in J. The factor 10⁴ converts cm⁻² to m⁻².

## Which points a fit uses

A point is used only if all of these hold:

- the flux is at or above the noise floor of **10⁵ cm⁻² s⁻¹ sr⁻¹ eV⁻¹**;
- the value is finite (fill values become NaN when the data is read);
- f is positive.

A record with fewer than **6** usable points is not fitted. On the 2025-01-08 flyby this leaves about one H⁺ record in ten.

That floor is the original method's, and it is strict: see *Noise floor and weighting* below for what it means in counts, and for the alternative.

## The models

Densities n are in cm⁻³ and temperatures T in eV.

**Maxwellian:** f(E) = n (m / 2πkT)<sup>3/2</sup> exp(−E / kT)

**Kappa:** f(E) = n (πκθ²)<sup>−3/2</sup> · Γ(κ+1) / Γ(κ−½) · (1 + v² / κθ²)<sup>−(κ+1)</sup>, with θ² = (2κ−3)/κ · kT/m and v² = 2E/m.

A kappa distribution has a power-law tail; it tends to a Maxwellian when κ grows large.

The plugin offers five models:

| Model | Populations |
|---|---|
| Maxwellian | one Maxwellian |
| Kappa | one kappa |
| Maxwellian + kappa | Maxwellian core + kappa halo |
| 2 Maxwellians | core + hot Maxwellian |
| 2 Maxwellians + kappa | core + warm Maxwellian + kappa halo |

## How one fit runs

Every fit is a least-squares fit of ln f, with the parameters log₁₀ n, log₁₀ T and κ, using SciPy's `curve_fit` inside bounds.

The multi-population models are fitted in steps, so each population starts close to the right answer:

1. Seed the core from the slope of ln f against E over a low-energy window.
2. Fit the core alone on that window.
3. Subtract it. Fit the next population on the positive residual above its threshold, and so on.
4. Fit all populations together on every used point, starting from those values.

The windows and bounds, all on kinetic energy:

| Model | Population | Fitted on | T bounds | κ bounds |
|---|---|---|---|---|
| Maxwellian | single | all used points | 1 eV – 31.6 keV | |
| Kappa | single | all used points | 1 eV – 31.6 keV | 1.55 – 12 |
| Maxwellian + kappa | core | 20 – 700 eV | 1 eV – 1 keV | |
| | halo | residual above 800 eV | 31.6 eV – 31.6 keV | 1.55 – 12 |
| 2 Maxwellians | core | below 400 eV | 1 eV – 3.16 keV | |
| | hot | residual above 300 eV | 31.6 eV – 31.6 keV | |
| 2 Maxwellians + kappa | core | 10 – 200 eV | 3.2 – 316 eV | |
| | warm | residual 200 – 1500 eV | 100 eV – 3.16 keV | |
| | halo | residual above 1500 eV | 1 – 31.6 keV | 1.55 – 12 |

Densities are bounded to 10⁻³ – 10⁴ cm⁻³, and 10⁻⁴ – 10³ cm⁻³ for the 2 Maxwellians + kappa halo.

A fit is thrown away when:

- `curve_fit` does not converge;
- a halo or hot temperature ends above 20 keV;
- κ ends at 11.9 or more: it is stuck at its bound, so the population is really a Maxwellian.

## Noise floor and weighting

The flux of one count is the same on every energy step, because the steps are a fixed fraction of their energy. Comparing the L1 counts with the L2pre flux of the same records gives about **10³** of energy flux per count (9·10² – 1.2·10³ over energies, for H⁺ and alphas, on the 2024-09-04 and 2025-01-08 flybys).

So the original floor of 10⁵ keeps only points with about **100 counts** or more. Most of the signal is below that: this floor is the main reason the moments have gaps.

The **Noise floor** choice, on each moment product and in the Inspector, offers:

| Choice | Points used | Fit |
|---|---|---|
| 10⁵ flux, unweighted (original) | flux ≥ 10⁵ (about 100 counts) | every point weighs the same |
| 1 count, Poisson-weighted | ≥ 1 count | each point weighted by its Poisson error |
| 2 counts, Poisson-weighted | ≥ 2 counts | same |
| 5 counts, Poisson-weighted | ≥ 5 counts | same |
| 10 counts, Poisson-weighted | ≥ 10 counts | same |

Counts are derived from the flux with the 10³ factor. A point of C counts has a relative error of 1/√C, which is the error of ln f used to weight it: a 2-count point has an error about 7 times larger than a 100-count point, so about 50 times less weight in χ².

On 2024-09-04, the 2-count floor accepts 757 of 948 H⁺ records, against 184 with the original floor. On the records both accept, the density agrees (median ratio 0.99) but the core temperature comes out much colder (median ratio 0.12), and a different model wins in about 60 % of them. The low-count points at the lowest energies pull the core down. Whether they are real cold plasma or contamination is not settled: check records in the Inspector before relying on these values.

## Goodness of fit and model choice

Each fit gets a reduced χ² computed in log space:

**χ² = Σ (ln f_obs − ln f_model)² / (N − p)**

where N is the number of used points and p the number of fitted parameters. With the original floor all points weigh the same. With a counts floor each residual is divided by its Poisson error, so χ² is in units of the expected noise.

The **Model** choice, on each moment product and in the Inspector, decides which models are tried:

- **Auto (best χ²):** tries Maxwellian + kappa, 2 Maxwellians and 2 Maxwellians + kappa, and keeps the lowest χ². The single-population models are not part of Auto.
- **Any other choice:** fits that model only.

A record whose best χ² is above the limit is rejected:

- with the original floor, above **1**: real spectra fit at χ² ≈ 0.002 – 0.09, fits to pure noise around 3.7 – 4.4;
- with a counts floor, above **50**: real records fit at a median of 12 – 22, fits to random counts with no plasma shape at 97 and more.

A weighted χ² well above 1 for real records means the models do not capture everything at the precision of the counts.

## The moments

From the accepted fit of each record:

- **density:** the sum of the population densities, n = Σ nᵢ;
- **T_c:** the core temperature (the only temperature for a single-population model);
- **T_eff:** the density-weighted temperature, Σ nᵢ Tᵢ / Σ nᵢ.

They are published as the products `msa/moments_fit/<species>/density`, `T_c` and `T_eff`. Records without an accepted fit have no value.

## Caching

The plugin fits whole UTC days. The result of each species, day, model and noise floor is cached for 30 days. The first plot of a day can take a while; later plots and model switches back to an already fitted model are immediate.

## Reading the Inspector

- **Top plot:** the raw energy flux. Filled points were used, hollow points were dropped; the red line is the noise floor.
- **Bottom plot:** the phase-space density with the same used and dropped points, the best model's populations and their total, and the total of every other model that converged.
- **Table:** every model that converged for this record, best first, with its χ², moments and parameters. The status column says which fit was accepted, or why the best one was rejected.
- **Fitted records only:** steps the slider through the records that have at least one fit.

## Limits to keep in mind

- The fit uses the energy spectrum only. It assumes an isotropic distribution and computes no bulk velocity.
- Heavies and Total mix ions of different masses, and no single mass converts their flux exactly. They are fitted as O⁺ and as protons respectively, so their moments are approximate; their product labels say so.
- There are no error bars. χ² tells how well a model follows the points, not how precise the moments are.
- The counts are derived from the flux with one factor of 10³ for every species and energy, measured on two flybys; reading the L1 counts directly would be exact.
- The windows above were tuned on flyby spectra. A very different plasma, much hotter or much colder, may need other windows.
