# sciqlop-pyspedas (experimental)

MMS particle spectrograms computed by [pyspedas](https://github.com/spedas/pyspedas)
`mms_part_getspec`, exposed as SciQLop virtual products under `pyspedas/MMS/`:

- FPI ions / electrons, HPCA H+ / He+ / He++ / O+
- energy, pitch angle and gyrophase spectrograms
- knobs: probe (1-4) and data rate (FPI fast|brst, HPCA srvy|brst)

Computation runs in SciQLop's remote worker process. Downloaded CDFs go to
`<workspace>/spedas_data/` (a global `MMS_DATA_DIR` still wins). Any window
works: it is computed and cached in fixed 1 h fragments on the UTC hour grid.

Requires SciQLop 0.14+ (out-of-process products get their log axes from 0.14 on).
