"""Small, non-persisting PyWRDS connection helpers."""

from __future__ import annotations

import os
from pathlib import Path


WRDS_HOST = "wrds-pgdata.wharton.upenn.edu"
WRDS_PORT = "9737"
WRDS_DATABASE = "wrds"


def _saved_wrds_username() -> str | None:
    """Find the username for WRDS without reading or returning the password."""
    username = os.environ.get("WRDS_USERNAME") or os.environ.get("PGUSER")
    if username:
        return username

    pgpass = Path(os.environ.get("PGPASSFILE", Path.home() / ".pgpass"))
    if not pgpass.is_file():
        return None

    try:
        for line in pgpass.read_text().splitlines():
            if not line or line.startswith("#"):
                continue
            fields = line.split(":", 4)
            if len(fields) != 5:
                continue
            host, port, database, username, _password = fields
            if (
                host in ("*", WRDS_HOST)
                and port in ("*", WRDS_PORT)
                and database in ("*", WRDS_DATABASE)
                and username
            ):
                return username
    except OSError:
        return None
    return None


def connect():
    """Open an interactive PyWRDS connection using PyWRDS' normal auth flow.

    No credential is read from project files or written by this helper. PyWRDS
    may offer to create the user's ~/.pgpass after a successful login; the user
    makes that choice in the interactive terminal.
    """
    try:
        import wrds
    except ImportError as exc:
        raise RuntimeError(
            "PyWRDS is not installed. Run scripts/setup_env.sh first."
        ) from exc

    username = _saved_wrds_username()
    if username:
        return wrds.Connection(wrds_username=username)
    return wrds.Connection()


def relevant_libraries(connection) -> list[str]:
    """Return only library names likely needed for this assignment."""
    libraries = connection.list_libraries()
    preferred = {"crsp_a_stock", "crsp_a_ccm", "crsp_a_indexes", "comp_na_daily_all"}
    matched = sorted(name for name in libraries if name.lower() in preferred)
    if matched:
        return matched
    keywords = ("crsp", "comp", "ccm")
    return sorted(name for name in libraries if any(k in name.lower() for k in keywords))


def relevant_tables(connection, library: str) -> list[str]:
    """Return likely CIZ, Compustat, or link tables without reading observations."""
    tables = connection.list_tables(library=library)
    keywords = ("mth", "monthly", "security", "issuer", "name", "link", "funda", "annual")
    return sorted(name for name in tables if any(k in name.lower() for k in keywords))
