# Proposed 1960–2025 staged CRSP acquisition

Prepared for approval. No commands below have been executed for the new rollout.

## Explicit scope and sequencing

Calendar years 1960 through 2025 inclusive: 66 stock jobs and 66 index jobs.
Existing 2020 stock (1,950,357 rows, 79 Parquet files) and index (253 rows,
one Parquet file) were reverified locally before this plan. Both must verify
again before the existing extractor skips them. There are 65 new partitions
per kind. Half-open total scope: 1960-01-01 <= dlycaldt < 2026-01-01.
Each invocation below requests exactly one calendar year and exactly one kind.
Neither SIC nor 1926–1959 can be selected by these commands.

Execute ONE invocation at a time, inspect its verified manifest, and advance
only after its checks pass. These are a reviewable command list, not an
unattended batch script. Run stock then index for a year before advancing.
No parallel queries. Do not paste the entire list into an unattended terminal.
Use the unchanged tested extractor and working local authentication. No
installation, SQL changes, imputation, filtering or financial adjustments.

## Unchanged SQL and bounds

Stock:

```sql
SELECT permno, dlycaldt, dlyret, dlyretx,
       dlyretmissflg, dlyretdurflg, dlydelflg, dlyprevdt
FROM crsp.stkdlysecuritydata
WHERE dlycaldt >= :start_date AND dlycaldt < :end_date
ORDER BY permno, dlycaldt
LIMIT :overflow_limit
```

Index:

```sql
SELECT dlycaldt, vwretd
FROM crsp.wrds_dailyindexret_query
WHERE dlycaldt >= :start_date AND dlycaldt < :end_date
ORDER BY dlycaldt
LIMIT :overflow_limit
```

For year Y, bind start_date=Y-01-01 and end_date=(Y+1)-01-01.
Stock overflow_limit=10,000,001, accepted cap=10,000,000.
Index overflow_limit=367, accepted cap=366. Fetch size=25,000.
These are caps, not expected row counts. A sentinel row aborts; a truncated
result is never marked complete. Named server-side cursors and compressed
chunk files preserve bounded client memory.

## Mandatory gates and progress

The existing extractor automatically aborts overflow, invalid scope, duplicate
or null keys, ordering errors, write/count/checksum failure, or incompatible
completed manifests. Its completion marker alone is not a comprehensive
economic-quality approval: empty results and return/flag diagnostics are
recorded rather than automatically rejected. Therefore inspect each annual
manifest before launching the next invocation, without altering its SQL.

At every annual gate report rows, observed dates, key checks, missing returns,
return extrema/nonfinite/below-minus-one counts, all raw flag frequencies,
previous-date diagnostics, elapsed time, bytes, bytes/row, rows/second, and
measured process-lifetime peak memory. Reject an empty partition as adequate
coverage; stop for review on unexplained coverage gaps, unrecognized flags,
nonfinite nonnull returns, or unusual distributions. Do not discard or
automatically repair observations. Stock and index observed calendars should
be compared, and index dates aligned exactly with the preserved French file.
On validation failure or an unexpected issue stop before the next query;
retain incomplete attempts and do not overwrite completed data.

After the first five NEW stock years (1960–1964), report per-year and aggregate
throughput/storage, maximum measured process peak, all quality results and any
failure. Continue to 1965 only if the results remain within the tested design
and no unexpected issues arise. Report stock-year progress immediately, even
before the corresponding index completes. Peak memory is the OS process
high-water mark including imports, not a server memory measurement.

## Exact sequential commands

```powershell
# 1960
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1960 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1960 --chunk-size 25000 --execute

# 1961
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1961 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1961 --chunk-size 25000 --execute

# 1962
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1962 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1962 --chunk-size 25000 --execute

# 1963
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1963 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1963 --chunk-size 25000 --execute

# 1964
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1964 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1964 --chunk-size 25000 --execute

# FIRST-FIVE CHECKPOINT: report five new stock partitions before advancing.

# 1965
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1965 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1965 --chunk-size 25000 --execute

# 1966
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1966 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1966 --chunk-size 25000 --execute

# 1967
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1967 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1967 --chunk-size 25000 --execute

# 1968
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1968 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1968 --chunk-size 25000 --execute

# 1969
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1969 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1969 --chunk-size 25000 --execute

# 1970
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1970 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1970 --chunk-size 25000 --execute

# 1971
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1971 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1971 --chunk-size 25000 --execute

# 1972
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1972 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1972 --chunk-size 25000 --execute

# 1973
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1973 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1973 --chunk-size 25000 --execute

# 1974
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1974 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1974 --chunk-size 25000 --execute

# 1975
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1975 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1975 --chunk-size 25000 --execute

# 1976
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1976 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1976 --chunk-size 25000 --execute

# 1977
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1977 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1977 --chunk-size 25000 --execute

# 1978
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1978 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1978 --chunk-size 25000 --execute

# 1979
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1979 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1979 --chunk-size 25000 --execute

# 1980
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1980 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1980 --chunk-size 25000 --execute

# 1981
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1981 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1981 --chunk-size 25000 --execute

# 1982
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1982 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1982 --chunk-size 25000 --execute

# 1983
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1983 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1983 --chunk-size 25000 --execute

# 1984
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1984 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1984 --chunk-size 25000 --execute

# 1985
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1985 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1985 --chunk-size 25000 --execute

# 1986
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1986 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1986 --chunk-size 25000 --execute

# 1987
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1987 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1987 --chunk-size 25000 --execute

# 1988
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1988 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1988 --chunk-size 25000 --execute

# 1989
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1989 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1989 --chunk-size 25000 --execute

# 1990
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1990 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1990 --chunk-size 25000 --execute

# 1991
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1991 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1991 --chunk-size 25000 --execute

# 1992
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1992 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1992 --chunk-size 25000 --execute

# 1993
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1993 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1993 --chunk-size 25000 --execute

# 1994
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1994 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1994 --chunk-size 25000 --execute

# 1995
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1995 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1995 --chunk-size 25000 --execute

# 1996
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1996 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1996 --chunk-size 25000 --execute

# 1997
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1997 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1997 --chunk-size 25000 --execute

# 1998
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1998 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1998 --chunk-size 25000 --execute

# 1999
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 1999 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 1999 --chunk-size 25000 --execute

# 2000
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2000 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2000 --chunk-size 25000 --execute

# 2001
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2001 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2001 --chunk-size 25000 --execute

# 2002
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2002 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2002 --chunk-size 25000 --execute

# 2003
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2003 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2003 --chunk-size 25000 --execute

# 2004
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2004 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2004 --chunk-size 25000 --execute

# 2005
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2005 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2005 --chunk-size 25000 --execute

# 2006
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2006 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2006 --chunk-size 25000 --execute

# 2007
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2007 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2007 --chunk-size 25000 --execute

# 2008
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2008 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2008 --chunk-size 25000 --execute

# 2009
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2009 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2009 --chunk-size 25000 --execute

# 2010
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2010 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2010 --chunk-size 25000 --execute

# 2011
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2011 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2011 --chunk-size 25000 --execute

# 2012
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2012 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2012 --chunk-size 25000 --execute

# 2013
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2013 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2013 --chunk-size 25000 --execute

# 2014
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2014 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2014 --chunk-size 25000 --execute

# 2015
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2015 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2015 --chunk-size 25000 --execute

# 2016
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2016 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2016 --chunk-size 25000 --execute

# 2017
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2017 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2017 --chunk-size 25000 --execute

# 2018
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2018 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2018 --chunk-size 25000 --execute

# 2019
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2019 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2019 --chunk-size 25000 --execute

# 2020 — existing stock and index must verify and skip; no query
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2020 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2020 --chunk-size 25000 --execute

# 2021
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2021 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2021 --chunk-size 25000 --execute

# 2022
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2022 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2022 --chunk-size 25000 --execute

# 2023
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2023 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2023 --chunk-size 25000 --execute

# 2024
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2024 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2024 --chunk-size 25000 --execute

# 2025
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2025 --chunk-size 25000 --execute
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2025 --chunk-size 25000 --execute

```

## Official French acquisition completed independently

Raw snapshot:
data/raw/ps2/french/20261019T032509174438Z/
contains original daily FF3 and FF12 ZIPs, individual metadata JSONs, and a
combined manifest with official URLs, UTC retrieval times, sizes and SHA-256.

Daily source:
https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip

Industry source:
https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Siccodes12.zip

Raw daily archive: 26,317 rows, 1926-07-01 through 2026-08-31 (202608 CRSP
vintage stated in the header). Parsed research data is restricted to
1960–2025: 16,610 rows, 1960-01-04 through 2025-12-31. All four source
percentage series (Mkt-RF, SMB, HML, RF) are divided by 100 once. Missing
sentinels/blank values remain missing, never zero-filled. No RF shifting or
forward filling; no replacement of CRSP vwretd by French Mkt-RF.
Duplicate dates and missing values in this research output: zero.

All 253 existing 2020 CRSP index dates match exactly, with no missing RF or
other factors and no extra French dates within that observed span. Full
1960–2025 CRSP alignment remains pending acquisition.

FF12: 12 categories, 49 inclusive SIC ranges, 98 source endpoints checked;
all 9,900 integer SIC codes 0100–9999 enumerated (5,450 explicit-range
assignments; 4,450 residual Other assignments). Valid integer codes outside
categories 1–11 map to residual Other=12. Missing, malformed and out-of-range
codes remain unclassified and counted. No historical SIC observations have
been extracted or joined. Other's residual treatment is explicit; it is not
an invented interval in the source file.

The raw RF header states that daily RF compounds over trading days to the
one-month T-bill rate, using Ibbotson through 202405 and ICE BofA from 202406.
Retain source precision; do not force monthly identities from rounded values.

Parsed outputs and checksum manifest:
data/processed/ps2/french/20261019T032947505510Z/

Detailed validation:
outputs/ps2/french_validation_20261019T032947505510Z.json

Tests actually run:
.\\.venv\\Scripts\\python.exe -B -m unittest discover -s tests -v
70 tests passed, including 9 new authentication-free French tests and existing
streaming, parameter binding, annual boundary, overflow, restart and checksum
tests. No new WRDS observations were requested in preparing this plan.

## Files created in this preparation step

No existing extractor, PS1 source, pilot dataset or completed CRSP partition was changed.

```text
docs/ps2_1960_2025_acquisition_plan.md
scripts/ps2_fetch_french.py
scripts/ps2_prepare_french.py
src/ps2/french.py
tests/test_ps2_french.py
data/raw/ps2/french/20261019T032509174438Z/F-F_Research_Data_Factors_daily_CSV.zip
data/raw/ps2/french/20261019T032509174438Z/F-F_Research_Data_Factors_daily_CSV.json
data/raw/ps2/french/20261019T032509174438Z/Siccodes12.zip
data/raw/ps2/french/20261019T032509174438Z/Siccodes12.json
data/raw/ps2/french/20261019T032509174438Z/manifest.json
data/processed/ps2/french/20261019T032947505510Z/ff3_daily_decimal.parquet
data/processed/ps2/french/20261019T032947505510Z/ff12_categories.parquet
data/processed/ps2/french/20261019T032947505510Z/ff12_ranges.parquet
data/processed/ps2/french/20261019T032947505510Z/manifest.json
outputs/ps2/french_validation_20261019T032947505510Z.json
```

The first French network attempt failed in the sandbox without creating a
snapshot; the authorized retry outside the sandbox succeeded. Local Git is
unavailable, so no Git-based diff claim is made. Integrity verification used
the actual Parquet manifests, file checksums and row counts.

