#!/usr/bin/env python3
"""Interactively verify WRDS authentication and inspect relevant table names."""

from __future__ import annotations

import sys

from ps1.wrds_client import connect, relevant_libraries, relevant_tables


def main() -> int:
    print("Opening WRDS connection. Credentials are entered only in this terminal.")
    print("If PyWRDS asks to create ~/.pgpass, choose n for a one-time connection.")
    connection = None
    try:
        connection = connect()
        libraries = relevant_libraries(connection)
        print("Relevant accessible libraries:")
        for library in libraries:
            print(f"  {library}")
            for table in relevant_tables(connection, library):
                print(f"    {table}")
        if not libraries:
            print("Connected, but no CRSP/Compustat/CCM libraries were listed.")
            return 2
        return 0
    except KeyboardInterrupt:
        print("Cancelled before completing WRDS authentication; no data was downloaded.")
        return 130
    except Exception as exc:  # avoid echoing connection strings or credential details
        print(f"WRDS check failed ({type(exc).__name__}).", file=sys.stderr)
        print("Check account access, network/VPN requirements, and PyWRDS setup.", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
