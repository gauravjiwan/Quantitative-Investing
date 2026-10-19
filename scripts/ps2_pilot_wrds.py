"""Preview or execute only PS2 Pilot A. Default mode never connects or writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ps1.wrds_client import WRDS_DATABASE, WRDS_HOST, WRDS_PORT, _saved_wrds_username

IDS = (10107, 12490, 14593)
START, END = date(2020, 1, 1), date(2020, 3, 1)
PARAMS = {"p1": IDS[0], "p2": IDS[1], "p3": IDS[2],
          "start_date": START, "end_date": END}
QUERIES = {
    "stock": ("crsp.stkdlysecuritydata", 180, """SELECT permno, dlycaldt, dlyret, dlyretx,
       dlyretmissflg, dlyretdurflg, dlydelflg, dlyprevdt
FROM crsp.stkdlysecuritydata
WHERE permno IN (:p1, :p2, :p3)
  AND dlycaldt >= :start_date AND dlycaldt < :end_date
ORDER BY permno, dlycaldt
LIMIT 181"""),
    "index": ("crsp.wrds_dailyindexret_query", 60, """SELECT dlycaldt, vwretd
FROM crsp.wrds_dailyindexret_query
WHERE dlycaldt >= :start_date AND dlycaldt < :end_date
ORDER BY dlycaldt
LIMIT 61"""),
    "sic": ("crsp.stksecurityinfohist", 100, """SELECT permno, permco, secinfostartdt, secinfoenddt,
       siccd, primaryexch, sharetype, securitytype,
       securitysubtype, usincflg, issuertype
FROM crsp.stksecurityinfohist
WHERE permno IN (:p1, :p2, :p3)
  AND (secinfostartdt < :end_date OR secinfostartdt IS NULL)
  AND (secinfoenddt >= :start_date OR secinfoenddt IS NULL)
ORDER BY permno, secinfostartdt, secinfoenddt
LIMIT 101"""),
}


class PilotError(RuntimeError):
    """Only fixed, noncredential error messages may be used here."""


def local_auth():
    """Preserve PS1 precedence; support libpq's Windows default passfile."""
    username = _saved_wrds_username()
    if username:
        return username, {}
    # An explicit passfile must never be silently replaced by another one.
    if os.environ.get("PGPASSFILE") or os.name != "nt" or not os.environ.get("APPDATA"):
        return None, {}
    path = Path(os.environ["APPDATA"]) / "postgresql" / "pgpass.conf"
    try:
        if path.is_file():
            for line in path.read_text().splitlines():
                if not line or line.startswith("#"):
                    continue
                fields = line.split(":", 4)
                if (len(fields) == 5 and fields[0] in ("*", WRDS_HOST)
                        and fields[1] in ("*", WRDS_PORT)
                        and fields[2] in ("*", WRDS_DATABASE) and fields[3]):
                    return fields[3], {"passfile": str(path)}
    except (OSError, UnicodeError):
        pass
    return None, {}


def guard_scope(params):
    if params != {"p1": 10107, "p2": 12490, "p3": 14593,
                  "start_date": date(2020, 1, 1), "end_date": date(2020, 3, 1)}:
        raise PilotError("Scope differs from approved Pilot A; stopped before querying.")


def check_scope(name, frame):
    if len(frame) > QUERIES[name][1]:
        raise PilotError("Pilot row cap exceeded; results not accepted or truncated.")
    if name != "index" and (frame.permno.isna().any() or not frame.permno.isin(IDS).all()):
        raise PilotError("Unexpected security identifier; pilot stopped.")
    if name in ("stock", "index"):
        d = pd.to_datetime(frame.dlycaldt)
        # Null dates are retained for reporting; nonnull dates must stay in scope.
        if not d.dropna().between(pd.Timestamp(START), pd.Timestamp(END), inclusive="left").all():
            raise PilotError("Daily date outside approved scope; pilot stopped.")
    else:
        a, b = pd.to_datetime(frame.secinfostartdt), pd.to_datetime(frame.secinfoenddt)
        if not ((a.isna() | a.lt(pd.Timestamp(END))) &
                (b.isna() | b.ge(pd.Timestamp(START)))).all():
            raise PilotError("SIC interval does not overlap approved dates; pilot stopped.")


def compound(values):
    a = np.asarray(pd.to_numeric(pd.Series(values), errors="raise"), dtype=float)
    if not len(a) or not np.isfinite(a).all() or (a < -1).any():
        return None
    return float(np.prod(1 + a) - 1)


def validate(frames, monthly):
    """Validate copies; retain every raw observation and flag unchanged."""
    s, idx, h = (frames[k].copy() for k in ("stock", "index", "sic"))
    for f, cols in ((s, ["dlycaldt", "dlyprevdt"]), (idx, ["dlycaldt"]),
                    (h, ["secinfostartdt", "secinfoenddt"])):
        for col in cols:
            f[col] = pd.to_datetime(f[col])
    issues, checks = [], {}
    for name, f, keys in (("stock", s, ["permno", "dlycaldt"]),
                           ("index", idx, ["dlycaldt"]),
                           ("sic", h, ["permno", "secinfostartdt", "secinfoenddt"])):
        checks[name] = {"rows": len(f), "duplicate_keys": int(f.duplicated(keys).sum()),
                        "null_key_rows": int(f[keys].isna().any(axis=1).sum())}
        if f.empty or checks[name]["duplicate_keys"] or checks[name]["null_key_rows"]:
            issues.append(f"{name}: empty data, duplicate keys or null keys; inspect counts")
    calendar = pd.DatetimeIndex(idx.dlycaldt.dropna().unique()).sort_values()
    checks["index_dates"] = [str(d.date()) for d in calendar]
    checks["distributions"] = {}
    for name, f, cols in (("stock", s, ["dlyret", "dlyretx"]), ("index", idx, ["vwretd"])):
        for col in cols:
            a = pd.to_numeric(f[col], errors="raise").astype(float)
            finite = a[np.isfinite(a)]
            checks["distributions"][name + "." + col] = {
                "null": int(a.isna().sum()), "nonfinite": int((~np.isfinite(a)).sum()),
                "below_minus_one": int(a.lt(-1).sum()), "above_one": int(a.gt(1).sum()),
                "quantiles": {str(q): float(finite.quantile(q)) for q in (0, .01, .5, .99, 1)} if len(finite) else {},
            }
            if a.isna().any() or (~np.isfinite(a)).any() or a.lt(-1).any():
                issues.append(f"{name}.{col}: missing/nonfinite or below -1 returns; retained")
    checks["flags"] = {c: {str(k): int(v) for k, v in
                              s[c].fillna("<NULL>").value_counts(dropna=False).items()}
                       for c in ("dlyretmissflg", "dlyretdurflg", "dlydelflg")}
    checks["flag_semantics"] = "Codes retained and counted; no undocumented flag exclusions."
    checks["previous_dates"] = {"null": int(s.dlyprevdt.isna().sum()),
                                "not_before_current": int(s.dlyprevdt.ge(s.dlycaldt).sum())}
    if any(checks["previous_dates"].values()):
        issues.append("Previous-observation dates missing or not earlier than current date")
    checks["sic_missing"] = int(h.siccd.isna().sum())
    checks["sic_invalid_intervals"] = int(h.secinfostartdt.gt(h.secinfoenddt).sum())
    matches = []
    for p in IDS:
        for d in (pd.Timestamp("2020-01-31"), pd.Timestamp("2020-02-29")):
            hh = h[h.permno.eq(p) & h.secinfostartdt.le(d) & h.secinfoenddt.ge(d)]
            matches.append({"permno": p, "month_end": str(d.date()), "matches": len(hh),
                            "sic": [None if pd.isna(v) else int(v) for v in hh.siccd]})
    checks["sic_month_end_matches"] = matches
    if checks["sic_missing"] or checks["sic_invalid_intervals"] or any(x["matches"] != 1 for x in matches):
        issues.append("SIC missingness, interval validity or month-end matching requires review")
    checks["sic_overlap_pairs"] = 0
    for _, g in h.groupby("permno"):
        rows = list(g.itertuples())
        for j, a in enumerate(rows):
            for b in rows[j + 1:]:
                if pd.notna(a.secinfostartdt) and pd.notna(a.secinfoenddt) and pd.notna(b.secinfostartdt) and pd.notna(b.secinfoenddt):
                    checks["sic_overlap_pairs"] += int(max(a.secinfostartdt, b.secinfostartdt) <= min(a.secinfoenddt, b.secinfoenddt))
    if checks["sic_overlap_pairs"]:
        issues.append("Overlapping SIC intervals retained")
    m = monthly.copy()
    m["month"] = pd.to_datetime(m.month).dt.to_period("M")
    checks["ps1_monthly_duplicate_keys"] = int(m.duplicated(["permno", "month"]).sum())
    comparisons = []
    for p in IDS:
        for mon in pd.period_range("2020-01", "2020-02", freq="M"):
            g = s[s.permno.eq(p) & s.dlycaldt.dt.to_period("M").eq(mon)].sort_values("dlycaldt")
            expected = calendar[calendar.to_period("M") == mon]
            actual = pd.DatetimeIndex(g.dlycaldt.dropna().unique()).sort_values()
            coverage = bool(len(expected) > 0 and actual.equals(expected) and not g.dlycaldt.duplicated().any() and g.dlycaldt.notna().all())
            prev = pd.Series(calendar[:-1], index=calendar[1:])
            boundary_unknown = any(d not in prev.index for d in g.dlycaldt.dropna())
            chain_ok = all(pd.notna(r.dlyprevdt) and r.dlycaldt in prev.index and r.dlyprevdt == prev[r.dlycaldt] for r in g.itertuples()) and len(g) > 0
            daily = compound(g.dlyret)
            mm = m[m.permno.eq(p) & m.month.eq(mon)]
            monthly_ret = float(mm.ret.iloc[0]) if len(mm) == 1 and pd.notna(mm.ret.iloc[0]) and np.isfinite(float(mm.ret.iloc[0])) else None
            comparable = coverage and chain_ok and daily is not None and monthly_ret is not None
            gap = daily - monthly_ret if daily is not None and monthly_ret is not None else None
            comparisons.append({"permno": p, "observation_month": str(mon), "daily_rows": len(g),
                                "index_days": len(expected), "missing_dates": [str(d.date()) for d in expected.difference(actual)],
                                "extra_dates": [str(d.date()) for d in actual.difference(expected)],
                                "calendar_complete": coverage, "boundary_unverified": boundary_unknown,
                                "previous_date_chain_verified": chain_ok, "comparable": comparable,
                                "daily_compounded": daily, "ps1_monthly": monthly_ret, "gap": gap,
                                "gap_above_1e_8": abs(gap) > 1e-8 if gap is not None else None})
            if not comparable or (gap is not None and abs(gap) > 1e-8):
                issues.append(f"{p}/{mon}: qualified comparison or reconciliation gap; see details")
    checks["reconciliation"] = comparisons
    checks["notes"] = [
        "Raw decimal returns are not rescaled, winsorized, filled or delisting-adjusted.",
        "Comparison = product(1 + daily total return) - 1 minus PS1 monthly total return.",
        "A missing/nonfinite/less-than-minus-one return prevents compounding, never skipna.",
        "Completeness uses the fetched CRSP index calendar, not an independently verified exchange calendar.",
        "January first-day previous interval cannot be certified without a pre-pilot calendar.",
        "Comparable requires full observed calendar and exact previous-trading-date chain; flag semantics remain separately unverified.",
        "Month-start PS1 dates are observation-month labels, never information-availability dates.",
        "1e-8 is a reporting tolerance, not permission to alter data. Different source vintages may differ.",
    ]
    checks["issues"] = issues
    return checks


def execute():
    guard_scope(PARAMS)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = ROOT / "data/raw/ps2/pilot" / stamp
    report_path = ROOT / "outputs/ps2" / f"pilot_a_validation_{stamp}.txt"
    monthly_path = ROOT / "data/raw/crsp_monthly/2020.parquet"
    # Verify the existing benchmark before contacting WRDS; never rebuild PS1.
    meta = json.loads(monthly_path.with_suffix(".json").read_text(encoding="utf-8"))
    if hashlib.sha256(monthly_path.read_bytes()).hexdigest() != meta["sha256"]:
        raise PilotError("PS1 monthly benchmark checksum mismatch; stopped before connecting.")
    monthly = pd.read_parquet(monthly_path, columns=["permno", "month", "ret"])
    monthly = monthly[monthly.permno.isin(IDS) & pd.to_datetime(monthly.month).lt("2020-03-01") & pd.to_datetime(monthly.month).ge("2020-01-01")]
    username, auth_options = local_auth()
    if not username:
        raise PilotError("PS1 lookup and Windows passfile fallback found no username; no connection attempted.")
    engine = create_engine(URL.create("postgresql+psycopg2", username=username,
                                     host=WRDS_HOST, port=int(WRDS_PORT), database=WRDS_DATABASE),
                           echo=False, hide_parameters=True, connect_args={
                               **auth_options,
                               "connect_timeout": 15, "application_name": "ps2_pilot_a",
                               "options": "-c default_transaction_read_only=on -c statement_timeout=60000"})
    frames, records = {}, []
    try:
        with engine.connect() as connection:
            for name, (source, cap, sql) in QUERIES.items():
                guard_scope(PARAMS)
                started = datetime.now(timezone.utc).isoformat()
                result = connection.execute(text(sql), PARAMS)
                keys = list(result.keys())
                rows = [dict(r) for r in result.mappings()]
                frames[name] = pd.DataFrame(rows, columns=keys)
                check_scope(name, frames[name])
                records.append({"name": name, "source": source, "query": sql,
                                "parameters": PARAMS, "rows": len(rows), "row_cap": cap,
                                "started_utc": started, "completed_utc": datetime.now(timezone.utc).isoformat()})
    finally:
        engine.dispose()
    # All queries are complete, in scope and connections closed before writes.
    folder.mkdir(parents=True, exist_ok=False)
    for record in records:
        name = record["name"]
        path = folder / f"{name}.parquet"
        # Decimal/date values from PostgreSQL remain decimal/date in raw Parquet.
        frame = frames[name]
        arrow = pa.Table.from_pandas(frame, preserve_index=False)
        with path.open("xb") as stream:
            pq.write_table(arrow, stream, compression="snappy")
        record.update(file=str(path.relative_to(ROOT)), bytes=path.stat().st_size,
                      sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      arrow_schema=str(arrow.schema))
    manifest = {"pilot": "A", "created_utc": datetime.now(timezone.utc).isoformat(),
                "files": records, "benchmark": {"file": str(monthly_path.relative_to(ROOT)),
                "sha256": meta["sha256"], "retrieved_utc": meta.get("retrieved_utc")},
                "scope": "Three fixed PERMNOs; daily dates [2020-01-01,2020-03-01); overlapping SIC intervals retain original endpoints."}
    with (folder / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, default=str)
        stream.write("\n")
    checks = validate(frames, monthly)
    for record in records:
        p = ROOT / record["file"]
        if pq.ParquetFile(p).metadata.num_rows != record["rows"] or hashlib.sha256(p.read_bytes()).hexdigest() != record["sha256"]:
            raise PilotError("Saved Parquet count/checksum mismatch; retain artifacts for review.")
    checks["saved_file_checks"] = "All three Parquet row counts and SHA-256 checksums verified."
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as stream:
        stream.write("PS2 Pilot A validation\n")
        stream.write("Rows: " + str({k: len(v) for k, v in frames.items()}) + "\n")
        stream.write("Review issues: " + str(len(checks["issues"])) + "\n")
        stream.write("PERMNO | month | comparable | compounded daily | PS1 monthly | difference\n")
        for r in checks["reconciliation"]:
            stream.write(f"{r['permno']} | {r['observation_month']} | {r['comparable']} | "
                         f"{r['daily_compounded']} | {r['ps1_monthly']} | {r['gap']}\n")
        stream.write("\nFull local diagnostics:\n" + json.dumps(checks, indent=2, allow_nan=False) + "\n")
    print("Pilot A saved:", folder.relative_to(ROOT))
    print("Validation report:", report_path.relative_to(ROOT))
    print("Rows:", {k: len(v) for k, v in frames.items()})
    print("Review issues:", len(checks["issues"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Connect only after explicit execution approval")
    args = parser.parse_args()
    if not args.execute:
        print("PREVIEW ONLY: no connection, queries, downloads or output files.")
        print("Parameters:", json.dumps(PARAMS, default=str))
        for name, (source, cap, sql) in QUERIES.items():
            print(f"\n{name}: {source}; accepted cap={cap}; one extra row detects overflow\n{sql}")
        return 0
    try:
        execute()
        return 0
    except PilotError as exc:
        print("STOPPED:", str(exc))
    except Exception as exc:
        original = getattr(exc, "orig", exc)
        state = getattr(original, "pgcode", None)
        state = state if isinstance(state, str) and len(state) == 5 and state.isalnum() else "unavailable"
        print(f"STOPPED: {type(exc).__name__}; SQLSTATE={state}; error details suppressed to protect credentials. No automatic retry.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
