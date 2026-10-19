# Empirical implementation audit and bounded SIC plan

Audit performed against the actual five-page docs/ps2.pdf and read-only PS1
Parquet schemas, source functions and config/project.toml. No empirical result
is asserted by this audit. Existing daily partitions will not be re-extracted.

## Verified assignment requirements

- Page 1: outcomes July 1963--December 2025; add initialization history as needed.
  Main writeup at most five pages, excluding tables/figures; code also submitted.
  Due October 19, 2026, 5pm (course/client time America/New_York).
- Q1 pp.1--3, footnotes1--5: daily CRSP VW total market returns minus same-day
  French RF; stock total returns minus that RF; intercept OLS for one-year,
  three-year and full-history beta estimates and next-month realized targets;
  age-weighted Welch slope winsorization. Pooled predictive calibration is the
  primary regression under the user's correction. Shared stocks and ME at
  forecast-origin month-end for VW comparisons; average monthly MSE then sqrt.
  Develop an alternative using IS only; compare separately IS/OOS and use
  Newey--West on monthly paired weighted squared losses. Beta sorts are optional.
- Q2 pp.3--4, footnotes6--8: jointly estimate three traded-factor exposures;
  forecast stock excess returns as beta-prime times premium, not plus alpha.
  CRSP VW expanding mean baseline; expanding traded factor means and a proposed
  alternative. Hold exposures, observations and weights fixed across premium
  methods. Separate IS/OOS factor and stock MSE/pseudo-R-squared and uncertainty.
- Q3 pp.4--5, footnotes9--11: historical month-end SIC to FF12; full industry
  indicators without an additional intercept plus standardized log ME, log BM,
  profitability, investment and Q1 beta. WLS objective w=sqrt(ME), row multiplier
  ME^(1/4). Compare affine normalizations and omission of an economic control.
  Jointly project a selected signal on controls spanning the constant, verify
  C'Wz_perp=0 and weighted variation explained. Same rows/weights for projection,
  full and pure return regressions; never restandardize the residual. FWL slope
  equality is an identity, not empirical return-predictive evidence.

## Verified repository inputs

|Path|Rows|Use and timing limitation|
|---|---:|---|
|data/processed/security_month.parquet|4,846,942|757 observation months Dec1962--Dec2025,39,973 PERMNOs;3,489,583 eligible rows/26,377 eligible IDs. PERMNO,PERMCO,monthly ret,me,lag_me,eligible,observation_date. Month is an observation label. ME in USD millions.|
|data/processed/company_month.parquet|3,453,733|PS1 eligible-share-class company aggregates; do not substitute a PERMCO return for a PERMNO beta silently.|
|data/processed/formation.parquet|287,673|Company/formation-year BM,OP,INV,BE and fiscal dates;1963--2025.234,068 rows have positive BM and nonnull OP/INV. None has a financial-statement date at/after July1 formation year.|
|data/processed/annual_accounting.parquet|505,192|PS1 annual accounting definitions and dated statements, not release-date vintages.|
|data/processed/q2_factors.parquet|750|PS1 traded Mkt-RF,HML,SMB and other factors; July1963--Dec2025.|
|data/processed/ref_ff5_0.parquet|750|Monthly French RF and reference factors; distinguish from daily RF compounding/rounding.|
|data/processed/crsp_index.parquet|750|Monthly CRSP VW/EW total returns for Q2 baseline.|
|data/raw/crsp_names/history.parquet|191,048|Prior full-source security history has intervals/classifications but NO SIC column. Existing extraction source is stksecurityinfohist.|
|data/raw/ps2/historical/{stock,index}/YYYY|66 annual pairs|Accepted daily sources1960--2025; retain all bytes/manifests.|
|data/processed/ps2/french/20261019T032947505510Z|16,610 daily rows|Decimal daily factors/RF,12 FF12 categories,49 inclusive SIC ranges.|

Source code read: src/ps1/panel.py (eligible, calendar_lag, annual_accounting,
characteristics), src/ps1/analysis.py (rf, construct_factors, q4), config/*.toml,
src/ps2/{betas,welch,factor_forecasts,residualization,french}.py.
Do not call PS1 build/save/table functions: they overwrite processed files/DB.

## Exact missing integration

1. Q1: validated daily-to-excess-return alignment, explicit duration/flag/history
   eligibility, bounded monthly sufficient-statistic/age-weighted history engine,
   realized target pairing, origin ME weights, IS/OOS split, IS-only alternative,
   pooled calibrations, common samples, RMSE/HAC/sensitivities and beta-sort plot.
   Existing beta modules are pure per-security functions only; no empirical cache
   or forecast/target panel exists. Expanding data starts1960, not full CRSP1926.
2. Q2: actual monthly return/factor/RF assembly, origin-date joint exposures,
   premium forecast features and IS-only specification, fixed exposure panel,
   matched loss panels, factor/stock evaluation and economic interpretation.
   Existing engine is monthly; no actual exposures or forecasts exist.
3. Q3: SIC acquisition/classification, origin-date accounting join and ME,
   selected timing-safe Q1 beta, joint monthly matched sample, actual coefficients,
   normalization/omitted-control comparison, signal projection/FWL diagnostics,
   time-series coefficient summaries and return interpretation. Existing functions
   are one-month primitives tested on synthetic data only.
4. Reporting: immutable run configuration/source fingerprints, stage manifests,
   synthetic integration tests, counts/exclusions/date assertions, figures/tables,
   concise self-contained report and reproduction command.

PS1 formation_year on a RETURN-month row is for July--June holdings. It is not
automatically the correct latest available formation vintage at a FORECAST
origin: June-end can observe the new June formation; June's realized return
used the prior one. A month-end feature join must account for that boundary.

## Proposed empirical policies, not computed results

- Use PERMNO stocks with PS1 eligibility and positive ME at origin, and original
  company-level PS1 fundamentals linked by that origin's PERMCO. Define exactly
  which June formation is available and never use future June links.
- Use positive, verified one-trading-period daily durations D1--D4/DU, not a
  blanket D1-only filter that would exclude weekends/holidays. Decide/report
  missing-value flag eligibility; never overwrite raw observations.
- Appendix rho2/256 as labeled main Welch specification and2/252 sensitivity;
  market-calendar and valid-pair age sensitivity. Historical and realized minimum
  counts must be explicit. A20-day realized threshold would remove entire short
  months, so it cannot be silently copied from the paper's historical eligibility.
- Reuse the pre-existing PS1 split July2000 as an explicitly justified candidate;
  no OOS-driven tuning. Primary calibration pooled. Mean-reversion/shrinkage is a
  candidate Q1 improvement; expanding lagged-factor predictive OLS a Q2 candidate.
- Q3 equal-weight ddof0 standardization follows PS1; signal log BM and controls
  the other four characteristics plus full represented FF12 is a candidate.
  Affine-unit sensitivity preserves spans; dropping OP changes the comparison.

## Open substantive initialization question

RESOLVED: the user explicitly approved "expanding since 1960 with disclosure."
No pre-1960 acquisition is needed or authorized. Subsequent computed results
are in outputs/ps2/empirical_20261019T054917302234Z, not in this initial audit.

User decision requested: accept the explicitly labeled expanding-since1960
benchmark with initialization disclosure, or require earlier history before
final Q1 results. No pre1960 acquisition is authorized or planned here. This
does not block the separately authorized bounded SIC stage.

## Bounded historical SIC scope and exact SQL

Potential Q3 origins:3,459,176 positive-ME PS1-eligible security-months,
26,299 PERMNOs; June1963--November2025. Actual calendar month-end keys,
June30,1963--November30,2025. No historical SIC before the first needed date
or after the last needed date is requested except original intervals that
overlap those dates. Each PERMNO receives its own needed min/max date bounds.
1000 PERMNOs/batch,27 sequential queries,25000 rows/batch and250000 total.
Each SELECT limit is accepted remaining cap+1. Never mark a sentinel result
complete. Prior191048-row full-source snapshot is a sizing reference, not a
claim of today's row count. Five raw columns imply a small interval snapshot
(roughly several to tens of MB, bounded250000 rows), not daily stock history.

```sql
WITH requested AS (
    SELECT * FROM unnest(CAST(:permnos AS integer[]),
                         CAST(:start_dates AS date[]),
                         CAST(:end_dates AS date[]))
      AS t(permno,start_date,end_date)
)
SELECT h.permno,h.permco,h.secinfostartdt,h.secinfoenddt,h.siccd
FROM crsp.stksecurityinfohist h
JOIN requested r ON h.permno=r.permno
WHERE (h.secinfostartdt<r.end_date OR h.secinfostartdt IS NULL)
  AND (h.secinfoenddt>=r.start_date OR h.secinfoenddt IS NULL)
ORDER BY h.permno,h.secinfostartdt NULLS FIRST,h.secinfoenddt NULLS FIRST
LIMIT :overflow_limit
```

Field names/types verified in outputs/ps2/wrds_schema_report.txt. Parameter arrays
come exclusively from read-only security_month, not caller-supplied tickers.
Exclusive end is each ID's latest needed origin month-end+1 day. Closed-interval
month-end joins follow the existing PS1 BETWEEN convention. Null endpoints
are counted and treated as open bounds, never backfilled with another row.
Raw files use a source/universe/query-fingerprint directory, UUID attempts,
exclusive writes and per-batch checksums/manifests. Restart verifies batches
before skipping. DuckDB local processing memory limited256MB. Global interval
overlaps, duplicate interval keys, multiple stock-month matches, wrong month-end
keys and PERMCO disagreements stop validation. Missing/invalid SIC is retained
and reported, not converted to Other or carried backward/forward. Final FF12
assignment will use the preserved official mapping in the empirical Q3 stage.

Preview: .\.venv\Scripts\python.exe -B scripts/ps2_extract_q3_sic.py

Execute approved bounded scope:
.\.venv\Scripts\python.exe -B scripts/ps2_extract_q3_sic.py --execute

Six synthetic SIC tests passed, including endpoint transitions/leap month-end,
duplicate/overlap failures, missing/invalid codes, no arbitrary multiple match,
parameter scope/caps, overflow without completion and restart/checksum rejection.
