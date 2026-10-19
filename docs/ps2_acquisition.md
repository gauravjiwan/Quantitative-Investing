# PS2 acquisition checkpoint

Pilot B execution requires approval after review of its exact SQL. Full historical
execution requires separate approval. Both new scripts default to preview mode.
PS1 and Pilot A files are read-only inputs and are never rewritten.

## Authoritative flag definitions

CRSP sources checked during preparation:

- [Duration dictionary](https://www.crsp.org/wp-content/uploads/appendix/FlagType_RD.html)
- [Missing-return dictionary](https://www.crsp.org/wp-content/uploads/appendix/FlagType_RM.html)
- [CIZ guide, daily security fields, page 16](https://www.crsp.org/wp-content/uploads/guides/CRSP_US_Stock_%26_Indexes_Database_Guide_Flat_File_Format_2.0.pdf)

`D1`/`D2`/`D3`/`D4` each span one trading period and respectively one/two/three/four
calendar days. `DU` spans one trading period and at least five calendar days.
`DD` denotes other daily delisting-return duration; `MR` a missing return.
`P1` through `P9` denote respectively two through ten trading periods.
These definitions do not justify filtering out weekend or holiday intervals.

Missing-return codes: `DG` distant delisting price; `DM` missing delisting price/amount;
`DP` pending delisting; `GP` excessive price gap; `MP` missing price; `MV` missing
corporate-action value; `NA` not applicable (return available); `NS` new security;
`NT` not tracked; `RA` return after a not-tracked period.

`DlyDelFlg=Y` denotes a delisting return, `N` a non-delisting return. `DlyRetx` excludes
ordinary dividends; it should not be interpreted as excluding every distribution.
Raw flags are retained, with unknown codes reported rather than interpreted or dropped.
The dictionaries are provider definitions, not estimation-sample eligibility rules.

## Storage and restart design

`scripts/ps2_extract_daily.py` prepares independent stock and index annual partitions
from 1926-07-01 inclusive to 2026-01-01 exclusive. SIC is a separate overlapping-interval
snapshot over that span, avoiding repeated history records in annual files.
The PostgreSQL schema names/fields come from the successful local schema report.
Default caps are 10 million stock rows/year, 366 index rows/year and 1 million SIC
intervals/snapshot, each with a one-row overflow sentinel. No request is unbounded in dates.
These caps are operational abort thresholds, not claimed source counts.

The default 25,000-row server-side cursor batches are converted directly to Zstandard
Parquet chunks. Stock/index dates and identifiers are never month-normalized. Numeric
returns use decimal128(38,18); unrepresentable values cause a conversion failure rather
than silent rounding. No returns are winsorized, filled, rescaled or delisting-adjusted.
Flag values and all missing nonkey values remain in the raw files.

Every attempt has a unique directory. Completed partitions have an exclusive-create
manifest with request fingerprint, source/SQL/parameters, UTC timestamps, chunk counts,
SHA-256 hashes, validation and measured timing/bytes. A restart rechecks hashes and counts
before skipping a completed partition. Interrupted partitions restart from the beginning
in a new attempt, preserving all old chunks. A partial attempt is never treated as complete.
A corrupt/incompatible completion manifest stops the run rather than replacing files.
Do not run concurrent acquisition processes for the same partition.

Empty historical results are recorded explicitly, not treated as evidence of complete
provider coverage. Date counts expose partial coverage within nonempty partitions.
Daily market dates must later be reconciled to stock dates; this preparation does not
assert uniform early coverage across exchanges or securities.

## Validation and performance estimates

Sorted keys allow uniqueness/order checks within and across chunk boundaries without
loading an annual panel. Null keys, duplicate keys and out-of-scope rows prevent a
completion marker. Missing returns, unusual flags, implausible returns, previous-date
chain mismatches and invalid SIC intervals are retained and reported for review.
Finite-return distributions use all observations, with chunk-combined moments; no
sampled quantiles are represented as exact quantiles. Previous-date chain comparisons
are confined to each partition and do not certify its first return interval.

Pilot B will record query/transfer/serialization/initial-hashing time and compressed
bytes per row by window. Estimated historical rows remain scenarios (100/120/140 million)
because pre-1963 stock-day counts are not known locally. Rates and bytes/row must come
from measured Pilot B results, not invented benchmarks. Report direct extrapolation
and 2-4 times elapsed-time scenarios; annual sorting, network/cache changes, authentication
and verification may make these inaccurate. Reserve 2-3 times compressed storage for
working copies/interrupted attempts. No measured Pilot B estimate exists before execution.

Reviewed scope previews (no authentication, queries or output writes):

```powershell
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind stock --year 2020
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind index --year 2020
.\.venv\Scripts\python.exe -B scripts/ps2_extract_daily.py --kind sic --sic-start-date 1926-07-01 --sic-end-date 2026-01-01
```

Append `--execute` only after approval for that exact scope. Execution without an
explicit year or complete first/last-year range is rejected. `--year` cannot be
combined with range flags. SIC rejects all year flags and requires its own start/end
dates for execution. Stock/index kinds reject SIC dates. A 2020 command therefore
cannot implicitly select other years or execute SIC extraction.

Manifests now also record OS process-lifetime peak resident memory (Windows
PeakWorkingSetSize or Unix ru_maxrss), including imports. This is not Python-only
heap size or a measurement of PostgreSQL server-side sort memory. See
`docs/ps2_2020_rollout.md` for the staged approval checkpoint.
