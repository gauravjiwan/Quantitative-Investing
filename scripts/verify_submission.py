"""Check the saved course package with Python's standard library only."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"


def rows(name: str) -> list[dict[str, str]]:
    with (OUT / "tables" / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def months() -> set[str]:
    return {f"{year:04d}-{month:02d}-01" for year in range(1963, 2026)
            for month in range(1, 13)
            if (year, month) >= (1963, 7) and (year, month) <= (2025, 12)}


def verify() -> None:
    expected = months()
    assert len(expected) == 750
    report = (OUT / "ps1_report.md").read_text(encoding="utf-8")
    for heading in ("## Question 1", "## Question 2", "## Question 3", "## Question 4", "## AI assistance"):
        assert heading in report, f"Missing report section: {heading}"
    assert not any("\u4e00" <= char <= "\u9fff" for char in report), "Report contains Chinese text"
    assert "Yuming Yang" not in report, "Report still contains a personal byline"
    assert (OUT / "ps1_report.pdf").is_file(), "Answer PDF is missing from the code package"
    for csv_name in set(re.findall(r"[A-Za-z0-9_]+\.csv", report)):
        assert (OUT / "tables" / csv_name).is_file(), f"Report references a missing table: {csv_name}"
    for image_name in set(re.findall(r"figures/([A-Za-z0-9_]+\.png)", report)):
        assert (OUT / "figures" / image_name).is_file(), f"Report references a missing figure: {image_name}"
    for figure in (OUT / "figures").glob("*.png"):
        assert figure.stat().st_size > 0, f"Empty chart: {figure}"
    assert len(list((OUT / "figures").glob("*.png"))) == 4

    market = rows("q1_market_monthly.csv")
    assert len(market) == 1_500
    for weighting in ("EW", "VW"):
        assert {row["month"] for row in market if row["weighting"] == weighting} == expected

    size = rows("q1_size_monthly.csv")
    assert len(size) == 15_000
    for decile in range(1, 11):
        for weighting in ("EW", "VW"):
            assert {row["month"] for row in size
                    if row["portfolio"] == f"D{decile:02d}" and row["weighting"] == weighting} == expected

    factors = rows("q2_factors.csv")
    assert len(factors) == 750 and {row["month"] for row in factors} == expected
    q3 = rows("q3_statistics.csv")
    assert len(q3) == 12 and {row["months"] for row in q3} == {"444", "306"}
    regressions = rows("q4_statistics.csv")
    assert len(regressions) == 12 and all(row["months"] == "750" for row in regressions)
    raw_years = {
        "crsp_monthly": range(1962, 2026),
        "crsp_index": range(1963, 2026),
        "compustat_annual": range(1961, 2025),
        "crsp_names": ("history",),
        "ccm_link": ("history",),
    }
    for kind, years in raw_years.items():
        for year in years:
            data = ROOT / "data" / "raw" / kind / f"{year}.parquet"
            record = data.with_suffix(".json")
            assert data.is_file() and record.is_file(), f"Missing raw snapshot: {data}"
            metadata = json.loads(record.read_text(encoding="utf-8"))
            assert metadata["rows"] > 0 and hashlib.sha256(data.read_bytes()).hexdigest() == metadata["sha256"], f"Invalid raw snapshot: {data}"
    for kind in ("ff5", "size", "bm25", "bm6", "op6", "inv6"):
        archive = ROOT / "data" / "raw" / "french" / f"{kind}.zip"
        manifest = json.loads(archive.with_suffix(".json").read_text(encoding="utf-8"))
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest["sha256"]
    print("Verified: English Q1–Q4 report, four charts, 750-month returns, 12 FMP summaries, and all bundled WRDS/French snapshot checksums.")


if __name__ == "__main__":
    verify()
