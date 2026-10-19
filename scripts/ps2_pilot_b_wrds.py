"""Pilot B only: three fixed windows, <=200000 stock-days; preview by default."""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import pandas as pd

import ps2_extract_daily as io

WINDOWS = (("1963-07", date(1963, 7, 1), date(1963, 7, 8)),
           ("2000-03", date(2000, 3, 6), date(2000, 3, 11)),
           ("2025-12", date(2025, 12, 1), date(2025, 12, 6)))
CAP = 200000
CHUNK_SIZE = 25000
FLAG_SOURCES = {
    "duration": "https://www.crsp.org/wp-content/uploads/appendix/FlagType_RD.html",
    "missingness": "https://www.crsp.org/wp-content/uploads/appendix/FlagType_RM.html",
    "delisting": "https://www.crsp.org/wp-content/uploads/guides/CRSP_US_Stock_%26_Indexes_Database_Guide_Flat_File_Format_2.0.pdf",
}
KNOWN = {"dlyretmissflg": {"DG", "DM", "DP", "GP", "MP", "MV", "NA", "NS", "NT", "RA"},
         "dlyretdurflg": {"D1", "D2", "D3", "D4", "DD", "DU", "MR"} | {f"P{i}" for i in range(1, 10)},
         "dlydelflg": {"Y", "N"}}


def remaining_limit(used):
    if not isinstance(used, int) or not 0 <= used < CAP:
        raise io.ExtractionError("Pilot B combined row budget exhausted or invalid; no next stock query.")
    return CAP - used


def spec_for(kind, label, start, end, used=0):
    if (label, start, end) not in WINDOWS or kind not in ("stock", "index"):
        raise io.ExtractionError("Request outside fixed Pilot B scope.")
    spec = io.request(kind, start, end, remaining_limit(used) if kind == "stock" else 7)
    if kind == "index":
        # Keep the exact displayed Pilot B index SQL, including its literal limit.
        spec["sql"] = io.INDEX_SQL.replace("LIMIT :overflow_limit", "LIMIT 8")
        spec["parameters"].pop("overflow_limit")
        spec.pop("fingerprint")
        spec["fingerprint"] = hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()
    return spec


def estimate_full(records):
    """Explicit extrapolation, never an asserted WRDS universe count."""
    p = io.ROOT / "data/processed/security_month.parquet"
    if not p.exists():
        return {"status": "No local monthly panel; extrapolation unavailable."}
    monthly = pd.read_parquet(p, columns=["month", "permno"])
    dates = pd.to_datetime(monthly.month)
    observed_months = int(dates.dt.to_period("M").nunique())
    calendar_days, stock_rows, seconds, size = 0, 0, 0., 0
    for item in records:
        stock, index = item["stock"], item["index"]
        stock_rows += stock["validation"]["rows"]
        calendar_days += len(index["validation"]["date_counts"])
        seconds += stock["elapsed_seconds"]
        size += stock["parquet_bytes"]
    if not stock_rows or not calendar_days or seconds <= 0:
        return {"status": "Insufficient measured observations for extrapolation."}
    # 21 sessions/month is a sizing assumption, not a historical calendar claim.
    base_rows = len(monthly) * 21
    rows_per_second, bytes_per_row = stock_rows / seconds, size / stock_rows
    return {"status": "Measured Pilot B throughput; assumed historical row count.",
            "local_monthly_rows": len(monthly), "local_months": observed_months,
            "assumed_sessions_per_month": 21, "observed_period_row_proxy": base_rows,
            "full_history_row_scenarios": [100000000, 120000000, 140000000],
            "pilot_stock_rows": stock_rows, "pilot_index_sessions": calendar_days,
            "measured_stock_rows_per_second": rows_per_second,
            "measured_stock_parquet_bytes_per_row": bytes_per_row,
            "scenarios": [{"rows": n, "parquet_bytes": n * bytes_per_row,
                           "seconds_at_pilot_rate": n / rows_per_second,
                           "planning_seconds_2x_to_4x": [2 * n / rows_per_second, 4 * n / rows_per_second]}
                          for n in (100000000, 120000000, 140000000)],
            "limitations": ["Pre-1963 daily row count not measured; scenarios are assumptions.",
                            "Small-window LIMIT/sort/cache performance may not predict annual-query performance.",
                            "Stock timing includes server execution, transfer, conversion, validation and initial checksums.",
                            "Connection/authentication, restart hash scans and final verification add time.",
                            "Storage excludes duplicate databases, backups and incomplete attempts; reserve 2-3x Parquet.",
                            "No annual query timing is established by this pilot."]}


def run():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = io.ROOT / "data/raw/ps2/pilot_b" / stamp
    report_path = io.ROOT / "outputs/ps2" / f"pilot_b_validation_{stamp}.json"
    records, used = [], 0
    status, error = "incomplete", None
    timer = time.perf_counter()
    try:
        with io.connection() as conn:
            for label, start, end in WINDOWS:
                stock_spec = spec_for("stock", label, start, end, used)
                stock = io.extract_partition(conn, folder / label / "stock", stock_spec, CHUNK_SIZE)
                used += stock["validation"]["rows"]
                index_spec = spec_for("index", label, start, end)
                index = io.extract_partition(conn, folder / label / "index", index_spec, CHUNK_SIZE)
                stock_dates = set(stock["validation"]["date_counts"])
                index_dates = set(index["validation"]["date_counts"])
                flags = stock["validation"]["flags"]
                records.append({"window": label, "stock": stock, "index": index,
                                "stock_dates_absent_from_index": sorted(stock_dates - index_dates),
                                "index_dates_without_any_stock": sorted(index_dates - stock_dates),
                                "unknown_flag_values": {k: sorted(set(v) - KNOWN[k]) for k, v in flags.items()}})
                if stock_dates - index_dates:
                    raise io.ExtractionError("Stock dates absent from index; preserve artifacts and stop for review.")
        status = "complete"
    except Exception as exc:
        error = io.safe_failure(exc)
    report = {"pilot": "B", "status": status, "error": error, "created_utc": io.utc(),
              "total_stock_rows": used, "stock_row_cap": CAP,
              "elapsed_seconds_including_connection": time.perf_counter() - timer,
              "windows": records, "flag_sources": FLAG_SOURCES,
              "full_extraction_estimate": estimate_full(records) if status == "complete" else {"status": "Not estimated: incomplete pilot."},
              "limitations": ["No RF downloaded or beta estimated.", "No monthly reconciliation: short windows are incomplete months.",
                              "Within-security chain mismatches and unknown flags are diagnostics, not automatic exclusions.",
                              "No per-security full-week coverage guarantee without listing histories.",
                              "All rows/flags retained; no economic filters or return corrections."]}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    io.dump_new(report_path, report)
    if status == "complete":
        io.dump_new(folder / "run_manifest.json", report)
    print("Pilot B", status, "stock rows", used, "report", report_path.relative_to(io.ROOT))
    if error:
        print("STOPPED:", error)
    return 0 if status == "complete" else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--execute", action="store_true")
    a = p.parse_args()
    if not a.execute:
        print("PREVIEW ONLY: no queries, authentication or writes. Execution awaits SQL approval.")
        for label, start, end in WINDOWS:
            for kind in ("stock", "index"):
                spec = spec_for(kind, label, start, end)
                print(label, kind, spec["sql"], spec["parameters"], sep="\n")
        print("Each stock limit is remaining combined allowance + 1; combined accepted stock cap=200000.")
        return 0
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
