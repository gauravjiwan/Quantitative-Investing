# Staged production review: 2020 only

Status: prepared and tested; no production WRDS connection or extraction authorized
by this document. The user must approve the commands below before execution.

## Review findings

- `stream_results=True` selects psycopg2 named server-side cursors, confirmed by
  the locally installed SQLAlchemy dialect documentation/implementation. Every fetch
  uses `fetchmany(25000)` with `max_row_buffer=25000`; there is no full-result `.all()`,
  DataFrame or concatenated table in the historical extraction path.
- Each chunk is converted directly to fixed-schema Zstandard Parquet. Python memory
  includes a few chunk representations, at most 366 date counters, flag counters,
  running moments, previous key and chunk-manifest metadata (at most 400 chunks at
  the 10-million annual cap/default batch size). PostgreSQL may still sort on its server;
  client streaming does not bound server sort resources.
- Dates and limits are bound through SQLAlchemy `text()` parameters, not interpolated
  into SQL. Sources and selected fields are fixed in code.
- `--year 2020` resolves exactly one half-open partition `[2020-01-01,2021-01-01)`.
  Conflicting/incomplete year flags and unscoped execution are rejected before auth.
  Stock/index jobs cannot select SIC history; SIC rejects year flags.
- Completed partitions are skipped only after source/query fingerprint, every chunk
  checksum and aggregate/Parquet counts are verified. Incomplete attempts restart in
  new UUID directories; old files are neither replaced nor deleted. Key failures and
  overflow prevent completion markers. Do not run concurrent writers for one partition.
- OS peak resident memory is recorded before/after streaming where available. It is
  process-lifetime high-water memory including imports, not an isolated allocation delta.

## Commands awaiting approval

```powershell
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2020 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2020 --chunk-size 25000 --execute
```

These are separate commands. Each selects one source and one year, then terminates.
Neither initiates another annual partition. If stock extraction fails, stop and review
before starting the index command. Existing PS1/pilot paths are never used as destinations.

Stock SQL:

```sql
SELECT permno, dlycaldt, dlyret, dlyretx,
       dlyretmissflg, dlyretdurflg, dlydelflg, dlyprevdt
FROM crsp.stkdlysecuritydata
WHERE dlycaldt >= :start_date AND dlycaldt < :end_date
ORDER BY permno, dlycaldt
LIMIT :overflow_limit;
```

Index SQL:

```sql
SELECT dlycaldt, vwretd
FROM crsp.wrds_dailyindexret_query
WHERE dlycaldt >= :start_date AND dlycaldt < :end_date
ORDER BY dlycaldt
LIMIT :overflow_limit;
```

Both bind start=2020-01-01 and end=2021-01-01. The stock limit is 10,000,001 with
an accepted cap of 10,000,000; the index limit is 367 with an accepted cap of 366.
The sentinel always aborts on overflow, never silently truncates. Outputs would be
`data/raw/ps2/historical/stock/2020/` and `data/raw/ps2/historical/index/2020/`.
An empty or partially covered source result is recorded explicitly, not declared full coverage.

The local PS1 2020 raw snapshot has 93,063 security-month rows. Multiplication by
an assumed 21 sessions/month gives a sizing proxy of 1,954,323 stock-days, not a WRDS
count. At the measured Pilot B rate this is about 4.5 minutes and 24 MB of compressed
stock data; annual sorting/cache/row composition can change both materially.
Budget 20-30 minutes for this checkpoint including validation, not as a guaranteed runtime.
Actual rows, elapsed time, memory, flags and output size remain pending execution approval.

## Separate SIC proposal, not approved for execution

Use `--kind sic --sic-start-date 1926-07-01 --sic-end-date 2026-01-01`, never a year command.

```sql
SELECT permno, permco, secinfostartdt, secinfoenddt,
       siccd, primaryexch, sharetype, securitytype,
       securitysubtype, usincflg, issuertype
FROM crsp.stksecurityinfohist
WHERE (secinfostartdt < :end_date OR secinfostartdt IS NULL)
  AND (secinfoenddt >= :start_date OR secinfoenddt IS NULL)
ORDER BY permno, secinfostartdt NULLS FIRST, secinfoenddt NULLS FIRST
LIMIT :overflow_limit;
```

Parameters: start=1926-07-01, end=2026-01-01, overflow_limit=1,000,001; accepted cap
1,000,000. Intervals retain original endpoints and null endpoints for review. This is
one overlapping-history snapshot; it is not implicitly executed with stock/index jobs.

## Proposed deadline schedule (all future acquisition stages need approval)

The assignment deadline is October 19, 2026 at 5 p.m.; the PDF does not specify a
timezone. Using the workspace's New York timezone for planning, about 18 hours remained
at this checkpoint (October 18, approximately 11 p.m.).

1. First 20-30 minutes after approval: extract/validate 2020 stock and index, check peak
   memory and re-estimate annual throughput. Review before approving another batch.
2. Next checkpoint: authorize the small French daily RF download and separate SIC snapshot.
   Without daily RF, production excess-return betas cannot be formed. Keep flag eligibility,
   minimum history, calendar/trading-day windows and Welch conventions explicit decisions.
3. Prioritize a recent batch with at least three preceding years, e.g. 2017-2025, to validate
   the entire analysis/report pipeline on a clearly labeled preliminary sample. Do not
   mistake this for the required full-sample answer or use OOS data for tuning.
4. Expand to July 1960-2016 in reviewed batches to support the full evaluation period's
   one/three-year estimators. Earlier initialization, July 1926-June 1960, is then needed
   for the genuinely full-available-history expanding estimator.
5. Reserve the final four hours for frozen-sample evaluation, checks and the self-contained
   report. Pilot B's 9-18-hour planning range for 120 million rows is tight against this
   deadline; do not automatically start every year or silently truncate history to fit.
   If measured 2020 timing makes the schedule infeasible, surface the coverage/extension
   decision for the user before committing to another large batch.

The data order is a scheduling proposal, not permission to execute any batch beyond 2020.

## Isolated OLS beta preparation

`src/ps2/betas.py` implements per-security one-year, three-year and expanding OLS
slopes with intercepts. Inputs must already be daily decimal excess returns with exact
same-day RF alignment. Beta equals centered stock/market cross-product divided by
centered market sum of squares; alpha equals mean stock excess minus beta times mean
market excess. The explicitly documented trailing calendar window is
`(as_of - DateOffset(years=n), as_of]`. The minimum valid-pair count must be supplied
by the caller; no research minimum or unverified flag filter is selected here.
Missing/nonfinite/unmatched pairs are excluded and counted; no forward filling occurs.
These are reference functions, not a complete optimized panel pipeline. Welch is not
implemented, and no empirical Q1 results are claimed.
