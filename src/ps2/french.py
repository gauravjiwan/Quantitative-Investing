"""Strict official French daily-file parsing and inclusive FF12 SIC ranges.

Source factor/RF values are percentages; output decimal return = source / 100.
No RF shifting, forward filling, resampling or replacement of CRSP vwretd occurs.
The FF12 source's rangeless category 12 (Other) is treated as the residual for
well-formed integer SICs 0100--9999. Missing/invalid SICs remain unclassified.
"""
import csv
from decimal import Decimal, InvalidOperation
import io
import re

import numpy as np
import pandas as pd

FACTOR_COLUMNS = ["Mkt-RF", "SMB", "HML", "RF"]
SENTINELS = {Decimal("-99.99"), Decimal("-999")}


def parse_daily(content):
    """Read the single eight-digit daily block; retain missing cells as NaN."""
    rows = list(csv.reader(io.StringIO(content)))
    headers = [i for i, row in enumerate(rows)
               if [c.strip() for c in row] == [""] + FACTOR_COLUMNS]
    if len(headers) != 1:
        raise ValueError("Expected exactly one official daily factor header")
    records = []
    ended = False
    for row in rows[headers[0] + 1:]:
        if row and re.fullmatch(r"\d{8}", row[0].strip()):
            if ended or len(row) != 5:
                raise ValueError("Unexpected additional/malformed daily block")
            record = {"date": pd.to_datetime(row[0].strip(), format="%Y%m%d", errors="raise")}
            for col, cell in zip(FACTOR_COLUMNS, row[1:]):
                try:
                    value = Decimal(cell.strip()) if cell.strip() else None
                except InvalidOperation:
                    raise ValueError("Nonnumeric French return cell") from None
                if value is not None and not value.is_finite():
                    raise ValueError("Nonfinite French source value")
                record[col] = float(value / 100) if value is not None and value not in SENTINELS else np.nan
            records.append(record)
        elif records:
            ended = True
    if not records:
        raise ValueError("No daily observations")
    frame = pd.DataFrame(records)
    if frame.date.isna().any() or frame.date.duplicated().any() or not frame.date.is_monotonic_increasing:
        raise ValueError("Null, duplicate or unsorted daily dates")
    return frame


def parse_ff12(content):
    """Parse provider headings and inclusive four-digit ranges; reject overlaps."""
    categories, ranges = [], []
    current = None
    for line in content.splitlines():
        if not line.strip():
            continue
        interval = re.fullmatch(r"\s*(\d{4})\s*-\s*(\d{4})\s*", line)
        heading = re.fullmatch(r"\s*(\d{1,2})\s+(\S+)\s+(.+?)\s*", line)
        if interval:
            if current is None:
                raise ValueError("SIC range precedes category")
            lo, hi = map(int, interval.groups())
            if not 100 <= lo <= hi <= 9999:
                raise ValueError("Invalid SIC range")
            ranges.append({"ff12": current, "sic_start": lo, "sic_end": hi})
        elif heading:
            current = int(heading[1])
            categories.append({"ff12": current, "label": heading[2], "description": heading[3]})
        else:
            raise ValueError("Unrecognized line in industry definition file")
    cat = pd.DataFrame(categories)
    intervals = pd.DataFrame(ranges, columns=["ff12", "sic_start", "sic_end"])
    if len(cat) != 12 or set(cat.ff12) != set(range(1, 13)) or cat.ff12.duplicated().any():
        raise ValueError("Expected twelve unique FF12 categories")
    if cat.loc[cat.ff12.eq(12), "label"].iloc[0] != "Other" or intervals.ff12.eq(12).any():
        raise ValueError("Residual Other convention needs review after source-format change")
    if set(intervals.ff12) != set(range(1, 12)):
        raise ValueError("An industry from 1--11 has no ranges")
    ordered = intervals.sort_values(["sic_start", "sic_end"])
    if any(a >= b for a, b in zip(ordered.sic_end.iloc[:-1], ordered.sic_start.iloc[1:])):
        raise ValueError("Overlapping FF12 SIC ranges")
    return cat, intervals


def classify_sic(sic, intervals):
    """Return FF12 and assignment status without imputing missing/invalid SICs."""
    sic = pd.Series(sic).copy()
    numeric = pd.to_numeric(sic, errors="coerce")
    valid = numeric.notna() & np.isfinite(numeric) & numeric.between(100, 9999) & numeric.eq(np.floor(numeric))
    # Booleans are not SIC identifiers, even if their numeric value were in range.
    valid &= ~sic.map(lambda x: isinstance(x, (bool, np.bool_)))
    result = pd.DataFrame({"ff12": pd.Series(pd.NA, index=sic.index, dtype="Int64"),
                           "assignment": "missing_or_invalid"}, index=sic.index)
    result.loc[valid, "ff12"] = 12
    result.loc[valid, "assignment"] = "residual_other"
    for row in intervals.itertuples(index=False):
        matches = valid & numeric.between(row.sic_start, row.sic_end)
        result.loc[matches, "ff12"] = row.ff12
        result.loc[matches, "assignment"] = "explicit_range"
    return result


def align_daily_rf(index, french):
    """Exact-date join only; no observation or RF value is silently dropped."""
    idx = index[["dlycaldt", "vwretd"]].copy()
    idx["dlycaldt"] = pd.to_datetime(idx.dlycaldt, errors="raise")
    if idx.dlycaldt.isna().any() or idx.dlycaldt.duplicated().any():
        raise ValueError("CRSP index has null/duplicate dates")
    if french.date.isna().any() or french.date.duplicated().any():
        raise ValueError("French data has null/duplicate dates")
    joined = idx.merge(french, left_on="dlycaldt", right_on="date", how="left", validate="one_to_one", indicator=True)
    dates = joined.loc[joined._merge.ne("both"), "dlycaldt"]
    report = {"index_rows": len(idx), "matched_dates": int(joined._merge.eq("both").sum()),
              "missing_french_dates": [str(x.date()) for x in dates],
              "null_RF_on_index_dates": int(joined.RF.isna().sum()),
              "null_other_factors_on_index_dates": {c: int(joined[c].isna().sum()) for c in FACTOR_COLUMNS[:-1]}}
    span = french[french.date.between(idx.dlycaldt.min(), idx.dlycaldt.max())]
    report["french_dates_not_in_index_within_span"] = [str(d.date()) for d in span.date if d not in set(idx.dlycaldt)]
    return joined.drop(columns="_merge"), report
