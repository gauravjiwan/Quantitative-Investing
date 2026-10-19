"""Resumable PS2 acquisition. Preview by default; historical execution needs approval."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import time
import uuid
import sys

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from ps2_pilot_wrds import ROOT, WRDS_DATABASE, WRDS_HOST, WRDS_PORT, local_auth

START, END = date(1926, 7, 1), date(2026, 1, 1)
STOCK_SQL = """SELECT permno, dlycaldt, dlyret, dlyretx,
       dlyretmissflg, dlyretdurflg, dlydelflg, dlyprevdt
FROM crsp.stkdlysecuritydata
WHERE dlycaldt >= :start_date AND dlycaldt < :end_date
ORDER BY permno, dlycaldt
LIMIT :overflow_limit"""
INDEX_SQL = """SELECT dlycaldt, vwretd
FROM crsp.wrds_dailyindexret_query
WHERE dlycaldt >= :start_date AND dlycaldt < :end_date
ORDER BY dlycaldt
LIMIT :overflow_limit"""
SIC_SQL = """SELECT permno, permco, secinfostartdt, secinfoenddt,
       siccd, primaryexch, sharetype, securitytype,
       securitysubtype, usincflg, issuertype
FROM crsp.stksecurityinfohist
WHERE (secinfostartdt < :end_date OR secinfostartdt IS NULL)
  AND (secinfoenddt >= :start_date OR secinfoenddt IS NULL)
ORDER BY permno, secinfostartdt NULLS FIRST, secinfoenddt NULLS FIRST
LIMIT :overflow_limit"""

# Decimal storage is an encoding constraint, not a return filter. Arrow safe
# conversion rejects unrepresentable precision/scale rather than rounding.
DECIMAL = pa.decimal128(38, 18)
SCHEMAS = {
    "stock": pa.schema([("permno", pa.int32()), ("dlycaldt", pa.date32()),
                        ("dlyret", DECIMAL), ("dlyretx", DECIMAL),
                        ("dlyretmissflg", pa.string()), ("dlyretdurflg", pa.string()),
                        ("dlydelflg", pa.string()), ("dlyprevdt", pa.date32())]),
    "index": pa.schema([("dlycaldt", pa.date32()), ("vwretd", DECIMAL)]),
    "sic": pa.schema([("permno", pa.int32()), ("permco", pa.int32()),
                      ("secinfostartdt", pa.date32()), ("secinfoenddt", pa.date32()),
                      ("siccd", pa.int32()), ("primaryexch", pa.string()),
                      ("sharetype", pa.string()), ("securitytype", pa.string()),
                      ("securitysubtype", pa.string()), ("usincflg", pa.string()),
                      ("issuertype", pa.string())]),
}
SOURCES = {"stock": "crsp.stkdlysecuritydata", "index": "crsp.wrds_dailyindexret_query",
           "sic": "crsp.stksecurityinfohist"}
SQL = {"stock": STOCK_SQL, "index": INDEX_SQL, "sic": SIC_SQL}


class ExtractionError(RuntimeError):
    """Fixed diagnostic messages only; never driver text or credentials."""


def utc():
    return datetime.now(timezone.utc).isoformat()


def process_peak_memory():
    """OS process-lifetime high-water RSS, including imports; not Python-only heap."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            size = ctypes.c_size_t
            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (name, size) for name in ("PeakWorkingSetSize", "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                    "PagefileUsage", "PeakPagefileUsage")]
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            api = ctypes.WinDLL("psapi", use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            api.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            api.GetProcessMemoryInfo.restype = wintypes.BOOL
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            if not api.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                raise OSError("Process memory counter unavailable")
            peak, method = int(counters.PeakWorkingSetSize), "Windows PeakWorkingSetSize"
        else:
            import resource
            raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            peak, method = int(raw if sys.platform == "darwin" else raw * 1024), "getrusage ru_maxrss"
        return {"peak_bytes": peak, "method": method,
                "scope": "Process-lifetime resident-memory peak, including imports; not isolated partition increment."}
    except (OSError, ImportError, AttributeError, ValueError):
        return {"peak_bytes": None, "method": "unavailable",
                "scope": "OS process-lifetime peak unavailable; no measured memory claim."}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, default=str, allow_nan=False)
        stream.write("\n")


def annual_windows(first=1926, last=2025):
    if not 1926 <= first <= last <= 2025:
        raise ExtractionError("Years outside approved preparation range.")
    return [(str(y), max(START, date(y, 1, 1)), min(END, date(y + 1, 1, 1)))
            for y in range(first, last + 1)]


def request(kind, start, end, cap):
    if kind not in SQL or not START <= start < end <= END or cap < 1:
        raise ExtractionError("Invalid bounded request.")
    params = {"start_date": start, "end_date": end, "overflow_limit": cap + 1}
    spec = {"kind": kind, "source": SOURCES[kind], "sql": SQL[kind],
            "parameters": params, "accepted_row_cap": cap,
            "arrow_schema": str(SCHEMAS[kind]), "compression": "zstd"}
    spec["fingerprint"] = hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()
    return spec


@contextmanager
def connection():
    username, auth = local_auth()
    if not username:
        raise ExtractionError("No existing local username found; no connection attempted.")
    engine = create_engine(URL.create("postgresql+psycopg2", username=username,
                                     host=WRDS_HOST, port=int(WRDS_PORT), database=WRDS_DATABASE),
                           echo=False, hide_parameters=True, connect_args={
                               **auth, "connect_timeout": 15,
                               "application_name": "ps2_bounded_acquisition",
                               "options": "-c default_transaction_read_only=on -c statement_timeout=600000"})
    try:
        with engine.connect() as conn:
            yield conn
    finally:
        engine.dispose()


def batches(conn, spec, chunk_size=25000):
    if not 1 <= chunk_size <= 100000:
        raise ExtractionError("Chunk size must be between 1 and 100000.")
    result = conn.execution_options(stream_results=True, max_row_buffer=chunk_size).execute(
        text(spec["sql"]), spec["parameters"])
    try:
        mapped = result.mappings()
        while True:
            rows = mapped.fetchmany(chunk_size)
            if not rows:
                break
            yield [dict(r) for r in rows]
    finally:
        result.close()


class Stats:
    """O(chunk size + trading dates + flag codes) memory; no full-panel sets."""
    def __init__(self, spec):
        self.spec = spec
        self.rows = self.duplicates = self.null_keys = self.order_errors = 0
        self.previous = None
        self.security_count = 0
        self.dates, self.flags, self.nulls = Counter(), {}, Counter()
        self.returns = {}
        self.previous_dates = {"null": 0, "not_before_current": 0,
                               "within_security_chain_mismatch": 0}
        self.last_date = None
        self.invalid_sic_intervals = 0

    def add(self, rows):
        kind = self.spec["kind"]
        start, end = (self.spec["parameters"][k] for k in ("start_date", "end_date"))
        for r in rows:
            self.rows += 1
            if self.rows > self.spec["accepted_row_cap"]:
                raise ExtractionError("Overflow detected; incomplete attempt retained; no completion manifest.")
            self.nulls.update(k for k, v in r.items() if v is None)
            if kind == "sic":
                a, b = r["secinfostartdt"], r["secinfoenddt"]
                if (a is not None and a >= end) or (b is not None and b < start):
                    raise ExtractionError("SIC interval outside overlap scope.")
                self.invalid_sic_intervals += int(a is not None and b is not None and a > b)
                self.null_keys += int(r["permno"] is None)
                key = (r["permno"] if r["permno"] is not None else -1, a or date.min, b or date.min)
            else:
                d = r["dlycaldt"]
                self.null_keys += int(d is None or (kind == "stock" and r["permno"] is None))
                if d is not None:
                    if not start <= d < end:
                        raise ExtractionError("Daily date outside bounded request.")
                    self.dates[str(d)] += 1
                key = (r["permno"] if r["permno"] is not None else -1, d or date.min) if kind == "stock" else (d or date.min,)
                if kind == "stock":
                    prev = r["dlyprevdt"]
                    self.previous_dates["null"] += int(prev is None)
                    self.previous_dates["not_before_current"] += int(prev is not None and d is not None and prev >= d)
                    if self.previous is not None and key[0] == self.previous[0]:
                        self.previous_dates["within_security_chain_mismatch"] += int(prev != self.last_date)
                    self.last_date = d
            if kind != "index" and (self.previous is None or key[0] != self.previous[0]):
                self.security_count += 1
            if self.previous is not None:
                self.duplicates += int(key == self.previous)
                self.order_errors += int(key < self.previous)
            self.previous = key
            for col in ("dlyretmissflg", "dlyretdurflg", "dlydelflg"):
                if col in r:
                    self.flags.setdefault(col, Counter())[r[col] if r[col] is not None else "<NULL>"] += 1
        for col in ("dlyret", "dlyretx", "vwretd"):
            if rows and col in rows[0]:
                x = np.array([float(r[col]) if r[col] is not None else np.nan for r in rows])
                a = x[np.isfinite(x)]
                st = self.returns.setdefault(col, {"finite": 0, "null": 0, "nonfinite_nonnull": 0,
                    "below_minus_one": 0, "above_one": 0, "zero": 0,
                    "min": None, "max": None, "mean": 0., "m2": 0.})
                null = sum(r[col] is None for r in rows)
                st["null"] += null
                st["nonfinite_nonnull"] += int((~np.isfinite(x)).sum()) - null
                st["below_minus_one"] += int((x < -1).sum())
                st["above_one"] += int((x > 1).sum())
                st["zero"] += int((x == 0).sum())
                if len(a):
                    n, old = len(a), st["finite"]
                    mean = float(a.mean()); delta = mean - st["mean"]
                    st["mean"] += delta * n / (old + n)
                    st["m2"] += float(((a - mean) ** 2).sum()) + delta * delta * old * n / (old + n)
                    st["finite"] += n
                    st["min"] = min(st["min"], float(a.min())) if st["min"] is not None else float(a.min())
                    st["max"] = max(st["max"], float(a.max())) if st["max"] is not None else float(a.max())

    def summary(self):
        returns = {}
        for col, st in self.returns.items():
            returns[col] = {k: v for k, v in st.items() if k != "m2"}
            returns[col]["sd_sample"] = math.sqrt(max(0., st["m2"]) / (st["finite"] - 1)) if st["finite"] > 1 else None
            if not st["finite"]:
                returns[col]["mean"] = None
        return {"rows": self.rows, "duplicate_keys": self.duplicates, "null_key_rows": self.null_keys,
                "securities": self.security_count if self.spec["kind"] != "index" else None,
                "order_errors": self.order_errors, "date_counts": dict(sorted(self.dates.items())),
                "null_counts": dict(self.nulls), "flags": {k: dict(v) for k, v in self.flags.items()},
                "return_distributions": returns, "previous_dates": self.previous_dates,
                "invalid_sic_intervals": self.invalid_sic_intervals,
                "empty_partition": self.rows == 0,
                "units": "Raw fractional returns retained; no rescaling, imputation, clipping or extra delisting adjustment.",
                "distribution_method": "All finite values; chunk-combined mean and sample variance; no sampled quantiles."}


def verify_complete(folder, spec):
    folder = Path(folder)
    marker = folder / "manifest.json"
    if not marker.exists():
        return None
    try:
        rec = json.loads(marker.read_text(encoding="utf-8"))
        if rec["status"] != "complete" or rec["request"]["fingerprint"] != spec["fingerprint"]:
            raise ExtractionError("Existing completion manifest differs from requested partition.")
        total = 0
        for item in rec["files"]:
            path = (folder / item["file"]).resolve()
            if not path.is_relative_to(folder.resolve()):
                raise ExtractionError("Manifest file escapes partition directory.")
            if sha256(path) != item["sha256"] or pq.ParquetFile(path).metadata.num_rows != item["rows"]:
                raise ExtractionError("Partition checksum or row-count mismatch; refusing restart.")
            total += item["rows"]
        if total != rec["validation"]["rows"]:
            raise ExtractionError("Partition aggregate row count mismatch.")
        return rec
    except ExtractionError:
        raise
    except Exception:
        raise ExtractionError("Existing partition manifest missing/corrupt; refusing overwrite.") from None


def save_partition(folder, spec, chunks, chunk_size=25000):
    """Complete-marker commit; interrupted attempts remain untouched on restart."""
    folder = Path(folder)
    existing = verify_complete(folder, spec)
    if existing is not None:
        return existing
    folder.mkdir(parents=True, exist_ok=True)
    attempt = folder / ("attempt-" + uuid.uuid4().hex)
    attempt.mkdir(exist_ok=False)
    dump_new(attempt / "request.json", {"request": spec, "started_utc": utc()})
    started, timer = utc(), time.perf_counter()
    memory_before = process_peak_memory()
    stats, files = Stats(spec), []
    for number, rows in enumerate(chunks):
        if not rows:
            continue
        if len(rows) > chunk_size:
            raise ExtractionError("Incoming chunk exceeds bounded memory limit.")
        stats.add(rows)
        table = pa.Table.from_pylist(rows, schema=SCHEMAS[spec["kind"]])
        path = attempt / f"part-{number:06d}.parquet"
        with path.open("xb") as stream:
            pq.write_table(table, stream, compression="zstd")
        count = pq.ParquetFile(path).metadata.num_rows
        if count != len(rows):
            raise ExtractionError("Written chunk row-count mismatch.")
        files.append({"file": str(path.relative_to(folder)), "rows": count,
                      "bytes": path.stat().st_size, "sha256": sha256(path)})
    summary = stats.summary()
    if stats.duplicates or stats.null_keys or stats.order_errors:
        dump_new(attempt / "validation_failed.json", summary)
        raise ExtractionError("Key validation failed; raw attempt retained without completion marker.")
    elapsed = time.perf_counter() - timer
    size = sum(f["bytes"] for f in files)
    rec = {"status": "complete", "request": spec, "started_utc": started, "completed_utc": utc(),
           "files": files, "validation": summary, "elapsed_seconds": elapsed,
           "parquet_bytes": size, "bytes_per_row": size / stats.rows if stats.rows else None,
           "rows_per_second": stats.rows / elapsed if elapsed else None,
           "chunk_size": chunk_size,
           "process_memory_before": memory_before,
           "process_memory_after": process_peak_memory(),
           "coverage_note": "Observed dates only; an empty result is recorded, never interpreted as proof of provider coverage."}
    dump_new(folder / "manifest.json", rec)
    return verify_complete(folder, spec)


def extract_partition(conn, folder, spec, chunk_size):
    existing = verify_complete(folder, spec)
    if existing is not None:
        return existing
    timer = time.perf_counter()
    rec = save_partition(folder, spec, batches(conn, spec, chunk_size), chunk_size)
    # Server execution and first fetch occur while consuming the generator above.
    print(f"Completed {spec['kind']} {spec['parameters']['start_date']}: {rec['validation']['rows']} rows; "
          f"{time.perf_counter() - timer:.2f}s including local verification")
    return rec


def safe_failure(exc):
    if isinstance(exc, ExtractionError):
        return str(exc)
    state = getattr(getattr(exc, "orig", exc), "pgcode", None)
    state = state if isinstance(state, str) and len(state) == 5 and state.isalnum() else "unavailable"
    return f"{type(exc).__name__}; SQLSTATE={state}; driver text suppressed; no automatic retry"


def selected_jobs(kind, year=None, first_year=None, last_year=None,
                  sic_start=None, sic_end=None, executing=False):
    """Resolve one explicit scope; never infer all history from an omitted flag."""
    if kind not in SQL:
        raise ExtractionError("Unknown extraction kind.")
    if kind == "sic":
        if any(v is not None for v in (year, first_year, last_year)):
            raise ExtractionError("SIC rejects year flags; provide separately reviewed SIC start/end dates.")
        if (sic_start is None) != (sic_end is None):
            raise ExtractionError("Both SIC dates must be supplied together.")
        if executing and sic_start is None:
            raise ExtractionError("SIC execution requires explicit reviewed start/end dates.")
        start, end = (sic_start, sic_end) if sic_start is not None else (START, END)
        return [(ROOT / "data/raw/ps2/historical/sic/history", request("sic", start, end, 1000000))]
    if sic_start is not None or sic_end is not None:
        raise ExtractionError("SIC dates cannot be supplied for stock/index extraction.")
    if year is not None:
        if first_year is not None or last_year is not None:
            raise ExtractionError("Use either one year or an explicit first/last range.")
        first_year = last_year = year
    elif (first_year is None) != (last_year is None):
        raise ExtractionError("Both first-year and last-year are required for a range.")
    elif first_year is None:
        if executing:
            raise ExtractionError("Execution requires --year or explicit --first-year and --last-year.")
        first_year, last_year = 1926, 2025
    cap = {"stock": 10000000, "index": 366}[kind]
    return [(ROOT / "data/raw/ps2/historical" / kind / label,
             request(kind, start, end, cap)) for label, start, end in annual_windows(first_year, last_year)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kind", choices=SQL, default="stock")
    p.add_argument("--year", type=int, help="Exactly one stock/index calendar year")
    p.add_argument("--first-year", type=int)
    p.add_argument("--last-year", type=int)
    p.add_argument("--sic-start-date", type=date.fromisoformat)
    p.add_argument("--sic-end-date", type=date.fromisoformat, help="Exclusive SIC interval overlap cutoff")
    p.add_argument("--chunk-size", type=int, default=25000)
    p.add_argument("--execute", action="store_true")
    a = p.parse_args()
    try:
        if not 1 <= a.chunk_size <= 100000:
            raise ExtractionError("Chunk size outside bounded range.")
        jobs = selected_jobs(a.kind, a.year, a.first_year, a.last_year,
                             a.sic_start_date, a.sic_end_date, a.execute)
        if not a.execute:
            print("PREVIEW ONLY: no connection or writes. Historical execution requires separate approval.")
            print(SQL[a.kind]); print(f"{len(jobs)} partitions; chunks <= {a.chunk_size}; cap/partition={jobs[0][1]['accepted_row_cap']}")
            print("First:", jobs[0][1]["parameters"], "Last:", jobs[-1][1]["parameters"])
            return 0
        for folder, spec in jobs:
            if verify_complete(folder, spec) is not None:
                print("Verified existing partition:", folder.relative_to(ROOT))
                continue
            with connection() as conn:
                extract_partition(conn, folder, spec, a.chunk_size)
        return 0
    except Exception as exc:
        print("STOPPED:", safe_failure(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
