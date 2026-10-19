"""Inspect only approved WRDS metadata; never fetch research observations."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from ps1.wrds_client import (
    WRDS_DATABASE, WRDS_HOST, WRDS_PORT, _saved_wrds_username,
)

REPORT = ROOT / "outputs/ps2/wrds_schema_report.txt"
PARAMS = dict(schema="crsp", stock="stkdlysecuritydata",
              index="wrds_dailyindexret_query", history="stksecurityinfohist",
              fallback="dsf_v2")
TABLE_SQL = """
SELECT table_schema, table_name, table_type,
       pg_catalog.has_table_privilege(
           pg_catalog.format('%I.%I', table_schema, table_name),
           'SELECT') AS can_select
FROM information_schema.tables
WHERE table_schema = :schema
  AND table_name IN (:stock, :index, :history, :fallback)
ORDER BY table_name
"""
COLUMN_SQL = """
SELECT table_schema, table_name, ordinal_position, column_name,
       data_type, udt_schema, udt_name, is_nullable
FROM information_schema.columns
WHERE table_schema = :schema
  AND table_name IN (:stock, :index, :history, :fallback)
ORDER BY table_name, ordinal_position
"""
EXPECTED = {
    "stkdlysecuritydata": (
        "permno", "dlycaldt", "dlyret", "dlyretx", "dlyretmissflg",
        "dlyretdurflg", "dlydelflg", "dlyprevdt", "dlyprc", "dlycap"),
    "wrds_dailyindexret_query": ("dlycaldt", "vwretd"),
    "stksecurityinfohist": (
        "permno", "permco", "secinfostartdt", "secinfoenddt", "siccd",
        "primaryexch", "sharetype", "securitytype", "securitysubtype",
        "usincflg", "issuertype"),
    "dsf_v2": ("permno", "dlycaldt", "dlyret"),
}


def safe_error(exc: Exception) -> str:
    """Use fixed classifications: driver messages may contain credentials."""
    if type(exc) is RuntimeError and exc.args == ("No locally configured WRDS username",):
        return "RuntimeError: existing PS1 authentication lookup found no WRDS username; connection not attempted"
    original = getattr(exc, "orig", exc)
    code = getattr(original, "pgcode", None)
    reasons = {
        "28P01": "password authentication failed",
        "28000": "authentication or authorization rejected",
        "42501": "insufficient privilege",
        "57014": "statement cancelled or timed out",
        "08001": "connection could not be established",
        "08006": "connection failure",
    }
    reason = reasons.get(code, "connection/metadata operation failed; driver text suppressed")
    state = code if isinstance(code, str) and len(code) == 5 and code.isalnum() else "unavailable"
    return f"{type(exc).__name__}: {reason}; SQLSTATE={state}"


def render(tables, columns) -> tuple[str, str]:
    lines = ["PS2 WRDS schema inspection", datetime.now(timezone.utc).isoformat(),
             "Scope: metadata and SELECT privileges only; no observations queried.",
             "Absent metadata means unavailable or invisible, not proven nonexistent.",
             "dsf_v2 is a fallback candidate only.", ""]
    visible = {r["table_name"]: r for r in tables}
    summary = []
    for name, expected in EXPECTED.items():
        rows = [r for r in columns if r["table_name"] == name]
        table = visible.get(name)
        if table is None:
            status = "not visible in information_schema.tables; availability/SELECT unconfirmed"
        else:
            status = f"{table['table_type']}; SELECT={table['can_select']}"
        found = {r["column_name"] for r in rows}
        missing = sorted(set(expected) - found)
        summary.append(f"crsp.{name}: {status}; columns={len(rows)}; missing expected={','.join(missing) or 'none'}")
        lines.extend([f"crsp.{name}: {status}",
                      "Expected fields absent/invisible: " + (", ".join(missing) or "none"),
                      "ordinal | column | PostgreSQL type | underlying type | nullable"])
        for r in rows:
            lines.append(f"{r['ordinal_position']} | {r['column_name']} | {r['data_type']} | "
                         f"{r['udt_schema']}.{r['udt_name']} | {r['is_nullable']}")
        lines.append("")
    lines.extend(["Executed SQL (bound parameters listed below):", TABLE_SQL.strip(),
                  COLUMN_SQL.strip(), repr(PARAMS)])
    return "\n".join(lines) + "\n", "\n".join(summary)


def main() -> int:
    if REPORT.exists():
        print("Stopped: report already exists; refusing to overwrite it.")
        return 2
    engine = None
    connection = None
    report = ""
    summary = ""
    result = 0
    try:
        username = _saved_wrds_username()
        if not username:
            raise RuntimeError("No locally configured WRDS username")
        # No password is copied into the URL. libpq uses existing local auth.
        url = URL.create("postgresql+psycopg2", username=username,
                         host=WRDS_HOST, port=int(WRDS_PORT), database=WRDS_DATABASE)
        engine = create_engine(url, echo=False, hide_parameters=True, connect_args={
            "connect_timeout": 15,
            "application_name": "ps2_metadata_inspection",
            "options": "-c default_transaction_read_only=on -c statement_timeout=30000",
        })
        connection = engine.connect()
        tables = list(connection.execute(text(TABLE_SQL), PARAMS).mappings())
        columns = list(connection.execute(text(COLUMN_SQL), PARAMS).mappings())
        report, summary = render(tables, columns)
    except Exception as exc:
        summary = "STOPPED: " + safe_error(exc)
        report = ("PS2 WRDS metadata inspection FAILED\n" +
                  datetime.now(timezone.utc).isoformat() + "\n" + summary +
                  "\nNo research observations queried. No automatic retry.\n")
        result = 1
    finally:
        cleanup_failed = False
        if connection is not None:
            try:
                connection.close()
            except Exception:
                cleanup_failed = True
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            report += "WARNING: connection cleanup reported an error; details suppressed.\n"
            summary += "\nWARNING: connection cleanup reported an error."
            result = 1
    try:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        with REPORT.open("x", encoding="utf-8") as stream:
            stream.write(report)
    except OSError:
        print(summary)
        print("Could not create the report; filesystem error details suppressed.")
        return 2
    print(summary)
    print("Report: outputs/ps2/wrds_schema_report.txt")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
