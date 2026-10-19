"""Offline parsing/validation of checksum-protected French snapshots; no network."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import zipfile
import sys

import pandas as pd

from ps2_extract_daily import ROOT, dump_new, sha256, verify_complete, selected_jobs
sys.path.insert(0, str(ROOT / "src"))
from ps2.french import parse_daily, parse_ff12, classify_sic, align_daily_rf, FACTOR_COLUMNS


def zip_text(path, suffix):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(suffix)]
        if len(names) != 1:
            raise ValueError("Ambiguous source archive member")
        return z.read(names[0]).decode("utf-8-sig")


def prepare(folder):
    folder = Path(folder).resolve()
    if not folder.is_relative_to((ROOT / "data/raw/ps2/french").resolve()):
        raise ValueError("Input must be a preserved PS2 French snapshot")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    records = {Path(r["file"]).name: r for r in manifest["files"]}
    for name, record in records.items():
        if sha256(folder / name) != record["sha256"]:
            raise ValueError("Raw French checksum mismatch")
    daily_text = zip_text(folder / "F-F_Research_Data_Factors_daily_CSV.zip", ".csv")
    all_daily = parse_daily(daily_text)
    daily = all_daily[all_daily.date.between("1960-01-01", "2025-12-31")].copy()
    cat, intervals = parse_ff12(zip_text(folder / "Siccodes12.zip", ".txt"))
    boundary_failures = []
    for row in intervals.itertuples(index=False):
        mapped = classify_sic([row.sic_start, row.sic_end], intervals)
        if not mapped.ff12.eq(row.ff12).all():
            boundary_failures.append(row._asdict())
    if boundary_failures:
        raise ValueError("Official FF12 endpoint check failed")
    enumerated = classify_sic(range(100, 10000), intervals)
    if enumerated.ff12.isna().any() or not enumerated.ff12.between(1, 12).all():
        raise ValueError("FF12 valid-range coverage failure")
    alignments = []
    # Validate only locally completed index partitions. No WRDS query or new scope.
    for marker in sorted((ROOT / "data/raw/ps2/historical/index").glob("*/manifest.json")):
        year = int(marker.parent.name)
        part, spec = selected_jobs("index", year=year, executing=True)[0]
        rec = verify_complete(part, spec)
        idx = pd.concat([pd.read_parquet(part / f["file"]) for f in rec["files"]], ignore_index=True)
        _, report = align_daily_rf(idx, daily)
        report["year"] = year
        alignments.append(report)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = ROOT / "data/processed/ps2/french" / stamp
    out.mkdir(parents=True, exist_ok=False)
    outputs = []
    for name, frame in (("ff3_daily_decimal", daily), ("ff12_categories", cat), ("ff12_ranges", intervals)):
        path = out / f"{name}.parquet"
        with path.open("xb") as stream:
            frame.to_parquet(stream, index=False, compression="zstd")
        outputs.append({"file": str(path.relative_to(ROOT)), "rows": len(frame), "sha256": sha256(path)})
    report = {"source_manifest": str((folder / "manifest.json").relative_to(ROOT)),
              "raw_checksums_verified": True, "source_header": daily_text.splitlines()[:4],
              "units": "Source percentages; all four daily series divided by 100 once to obtain decimal returns.",
              "raw_daily_rows": len(all_daily), "raw_first_date": str(all_daily.date.min().date()),
              "raw_last_date": str(all_daily.date.max().date()), "research_daily_rows": len(daily),
              "research_first_date": str(daily.date.min().date()), "research_last_date": str(daily.date.max().date()),
              "duplicate_dates": int(daily.date.duplicated().sum()),
              "null_counts": {c: int(daily[c].isna().sum()) for c in FACTOR_COLUMNS},
              "decimal_ranges": {c: {"min": float(daily[c].min()), "max": float(daily[c].max())} for c in FACTOR_COLUMNS},
              "crsp_index_alignment": alignments, "ff12_categories": len(cat), "ff12_ranges": len(intervals),
              "official_range_endpoints_tested": 2 * len(intervals),
              "integer_SICs_enumerated": len(enumerated),
              "SIC_assignment_counts": {str(k): int(v) for k, v in enumerated.assignment.value_counts().items()},
              "unmatched_policy": "Valid integer SIC 0100--9999 not in an explicit 1--11 interval maps to source residual Other=12. Missing/malformed/out-of-range SIC stays nullable, is counted and must not be silently imputed or dropped.",
              "outputs": outputs,
              "limitations": ["Full 1960--2025 CRSP calendar validation awaits approved index extraction.",
                              "No historical SIC observations downloaded or joined.",
                              "French Mkt-RF is retained as its own factor; it does not replace CRSP vwretd.",
                              "Raw archive includes source dates outside assignment scope; parsed research output is restricted to 1960--2025.",
                              "Source daily precision is retained; no attempt is made to reconstruct unrounded RF or force monthly compounding equality."]}
    dump_new(out / "manifest.json", report)
    report_path = ROOT / "outputs/ps2" / f"french_validation_{stamp}.json"
    dump_new(report_path, report)
    print(json.dumps({k: report[k] for k in ("raw_daily_rows", "raw_first_date", "raw_last_date", "research_daily_rows", "research_first_date", "research_last_date", "duplicate_dates", "null_counts", "crsp_index_alignment", "ff12_categories", "ff12_ranges", "official_range_endpoints_tested")}, indent=2))
    print("Report:", report_path.relative_to(ROOT))
    print("Parsed output:", out.relative_to(ROOT))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot", type=Path)
    a = p.parse_args()
    prepare(a.snapshot)


if __name__ == "__main__":
    main()
