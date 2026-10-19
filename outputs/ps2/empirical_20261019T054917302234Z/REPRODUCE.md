# Reproduce the PS2 empirical run locally

All commands below are local-only. They neither query WRDS nor rewrite PS1,
accepted daily data, pilot files, French archives or completed outputs.
Use the existing virtual environment and repository root in PowerShell.

## Selected completed artifacts

- Valid beta cache: `data/processed/ps2/beta_panel/8bffb23a2e2550fcf25c`.
- Accepted SIC: `data/processed/ps2/sic_q3/20261019T053427199109Z/stock_month_sic.parquet`.
- Empirical products: `data/processed/ps2/empirical_20261019T054917302234Z`.
- Results: this directory, with separate `q1`, `q2`, and `q3` tables and figures.
- `report.pdf` is the self-contained writeup. Tables/plots are separate artifacts.
- `final_validation.json` verifies keys/counts/horizons and all accepted daily checksums.
- `reproducibility.json` fingerprints code and PS1 inputs.
- `file_inventory.json` inventories final empirical outputs and products with hashes.

## Tests (the actual command used)

```powershell
@'
import sys, unittest
sys.path[:0] = ['src', 'scripts']
suite = unittest.defaultTestLoader.discover('tests')
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
'@ | .\.venv\Scripts\python.exe -B -
```

The run's actual captured results are `tests.txt` and `tests.json`: 145 tests,
zero failures/errors/skips. Authentication is not used in these synthetic tests.

## Fresh empirical computation from the accepted local cache

```powershell
.\.venv\Scripts\python.exe -B scripts/ps2_empirical.py --beta-cache data/processed/ps2/beta_panel/8bffb23a2e2550fcf25c
```

This prints a NEW `EMPIRICAL_OUTPUT=outputs/ps2/empirical_<timestamp>` path.
Use that new path rather than this completed run in the following command:

```powershell
.\.venv\Scripts\python.exe -B scripts/ps2_finish_empirical.py --run outputs/ps2/empirical_<timestamp> --beta-cache data/processed/ps2/beta_panel/8bffb23a2e2550fcf25c --sic data/processed/ps2/sic_q3/20261019T053427199109Z/stock_month_sic.parquet
```

The finalizer verifies completed Q2/Q3 artifacts before skipping them. Annual Q2
state and monthly Q3 products support resuming completed units with checksum
verification. An interrupted unit lacking a completion manifest is never silently
accepted; a partial Q2 year stops rather than overwriting it. Existing tables are
compared numerically before reuse, and existing final reports refuse overwrite.

For a fresh run, first capture `tests.json` and `tests.txt` in its output directory;
the finalizer now performs that capture automatically if no test record exists.

## Rebuilding daily sufficient statistics

```powershell
.\.venv\Scripts\python.exe -B scripts/ps2_build_beta_panel.py
```

The builder uses local accepted daily Parquets, bounded DuckDB processing and
rolling/expanding state; no WRDS connection. It prints its cache path. Source and
configuration fingerprints select the cache; completed years require valid
checksums. The valid selected cache was reconstructed from checksum-verified
monthly sufficient statistics after correcting a Parquet date-type comparison:

```powershell
.\.venv\Scripts\python.exe -B scripts/ps2_build_beta_panel.py --reuse-moments data/processed/ps2/beta_panel/275a26e1b1c1e65a73b5
```

`275a26e1b1c1e65a73b5` is an abandoned derived beta-output attempt: its monthly
moments were valid but a date-type comparison made current-return eligibility
false. Do not use its beta outputs. It and failed empirical attempts are retained
for audit. Neither contains changed raw data. The final selected cache has the
corrected monthly eligibility and passed regression/roundtrip tests.

## Fixed policies and genuine limits

- Expanding historical beta begins in 1960, explicitly approved by the user.
- Q1/Q3 outcomes cover all 750 assignment months; Q2 comparison covers 689 months
  starting August 1968 after the factor-premium initialization period.
- OOS begins July 2000. No model replacement was selected using OOS results.
- Q1's IS-fitted shrinkage selects k=1: no improvement over Welch; zero SE and
  undefined t-statistic are intentional, not a missing computation.
- Q2's expanding VAR(1) worsens OOS stock losses; this is a computed result.
- SIC missing/invalid values are excluded explicitly, not imputed to Other.
- Accounting uses the inherited prior-calendar-year/June formation convention;
  exact historical statement-release vintages are unavailable.
- Welch rho=2/256 primary versus 2/252 and both aging conventions are reported.
- WLS uses objective sqrt(ME), row scaling ME^0.25; pure signals retain residual units.

The next checkpoint is review of these empirical choices and results, rather than
additional data acquisition. No pre-1960 or further SIC extraction is planned.
