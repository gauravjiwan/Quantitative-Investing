"""Synthetic acquisition tests: no credentials, WRDS connections or research data."""
import contextlib
from datetime import date
from decimal import Decimal
import io as stdio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ps2_extract_daily as extraction
import ps2_pilot_b_wrds as pilot_b


def row(day=2, permno=1, ret="0.1", **changes):
    r = dict(permno=permno, dlycaldt=date(2020, 1, day),
             dlyret=Decimal(ret) if ret is not None else None,
             dlyretx=Decimal(ret) if ret is not None else None,
             dlyretmissflg="NA" if ret is not None else "MP",
             dlyretdurflg="D1", dlydelflg="N", dlyprevdt=date(2020, 1, day - 1))
    return dict(r, **changes)


def spec(cap=10):
    return extraction.request("stock", date(2020, 1, 1), date(2021, 1, 1), cap)


class ExtractionTests(unittest.TestCase):
    def test_2020_jobs_are_single_kind_and_exact_year(self):
        for kind in ("stock", "index"):
            jobs = extraction.selected_jobs(kind, year=2020, executing=True)
            self.assertEqual(len(jobs), 1)
            folder, query = jobs[0]
            self.assertEqual(folder.name, "2020")
            self.assertEqual(folder.parent.name, kind)
            self.assertEqual(query["kind"], kind)
            self.assertEqual(query["parameters"]["start_date"], date(2020, 1, 1))
            self.assertEqual(query["parameters"]["end_date"], date(2021, 1, 1))
            self.assertNotIn("stksecurityinfohist", query["sql"])

    def test_execution_needs_explicit_unambiguous_scope(self):
        for args in ({"kind": "stock"}, {"kind": "index", "first_year": 2020},
                     {"kind": "stock", "year": 2020, "first_year": 2020, "last_year": 2020},
                     {"kind": "sic", "year": 2020}, {"kind": "sic"},
                     {"kind": "stock", "year": 2020, "sic_start": extraction.START},
                     {"kind": "stock", "year": 2026}):
            with self.subTest(args=args), self.assertRaises(extraction.ExtractionError):
                extraction.selected_jobs(**args, executing=True)

    def test_sic_requires_own_dates_and_keeps_overlap_scope(self):
        jobs = extraction.selected_jobs("sic", sic_start=extraction.START,
                                         sic_end=extraction.END, executing=True)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0][1]["accepted_row_cap"], 1000000)
        self.assertEqual(jobs[0][1]["parameters"]["overflow_limit"], 1000001)
        self.assertEqual(jobs[0][1]["source"], "crsp.stksecurityinfohist")

    def test_cli_2020_execution_selects_only_one_job_offline(self):
        @contextlib.contextmanager
        def fake_connection():
            yield object()
        for kind in ("stock", "index"):
            with patch.object(sys, "argv", ["script", "--kind", kind, "--year", "2020", "--execute"]), patch.object(extraction, "verify_complete", return_value=None), patch.object(extraction, "connection", fake_connection), patch.object(extraction, "extract_partition") as extract:
                self.assertEqual(extraction.main(), 0)
                extract.assert_called_once()
                self.assertEqual(extract.call_args.args[2]["kind"], kind)
                self.assertEqual(extract.call_args.args[2]["parameters"]["start_date"], date(2020, 1, 1))

    def test_unscoped_execution_refused_before_authentication(self):
        with patch.object(sys, "argv", ["script", "--execute"]), patch.object(extraction, "connection", side_effect=AssertionError("no authentication")), contextlib.redirect_stdout(stdio.StringIO()):
            self.assertEqual(extraction.main(), 1)

    def test_peak_memory_instrumentation_and_manifest(self):
        memory = extraction.process_peak_memory()
        self.assertIn("method", memory)
        self.assertTrue(memory["peak_bytes"] is None or memory["peak_bytes"] > 0)
        with tempfile.TemporaryDirectory() as tmp, patch.object(extraction, "process_peak_memory", return_value={"peak_bytes": 1234, "method": "synthetic", "scope": "test"}):
            rec = extraction.save_partition(Path(tmp)/"job", spec(), [[row()]])
            self.assertEqual(rec["process_memory_after"]["peak_bytes"], 1234)

    def test_fetchmany_receives_bound_sql_and_parameters(self):
        class Empty:
            def mappings(self): return self
            def fetchmany(self, n): return []
            def close(self): pass
        from unittest.mock import MagicMock
        conn = MagicMock()
        conn.execution_options.return_value.execute.return_value = Empty()
        query = extraction.selected_jobs("stock", year=2020, executing=True)[0][1]
        list(extraction.batches(conn, query, 25000))
        statement, params = conn.execution_options.return_value.execute.call_args.args
        self.assertEqual(str(statement), extraction.STOCK_SQL)
        self.assertEqual(set(statement._bindparams), {"start_date", "end_date", "overflow_limit"})
        self.assertEqual(params, query["parameters"])

    def test_annual_half_open_boundaries_and_leap_year(self):
        windows = extraction.annual_windows()
        self.assertEqual(len(windows), 100)
        self.assertEqual(windows[0][1], date(1926, 7, 1))
        self.assertEqual(windows[-1][2], date(2026, 1, 1))
        self.assertTrue(all(a[2] == b[1] for a, b in zip(windows, windows[1:])))
        leap = extraction.annual_windows(2020, 2020)[0]
        self.assertEqual((leap[2] - leap[1]).days, 366)
        with self.assertRaises(extraction.ExtractionError):
            extraction.annual_windows(1925, 2025)

    def test_date_and_memory_bounds(self):
        st = extraction.Stats(spec())
        with self.assertRaises(extraction.ExtractionError):
            st.add([row(dlycaldt=date(2021, 1, 1))])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(extraction.ExtractionError):
                extraction.save_partition(Path(tmp)/"job", spec(), [[row(), row(3)]], 1)

    def test_duplicate_keys_across_chunk_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/"job"
            with self.assertRaises(extraction.ExtractionError):
                extraction.save_partition(folder, spec(), [[row()], [row()]], 1)
            self.assertFalse((folder/"manifest.json").exists())

    def test_order_error_and_null_key_prevent_completion(self):
        for rows in ([row(3), row(2)], [row(permno=None)]):
            with tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)/"job"
                with self.assertRaises(extraction.ExtractionError):
                    extraction.save_partition(folder, spec(), [rows])
                self.assertFalse((folder/"manifest.json").exists())

    def test_overflow_aborts_but_exact_cap_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/"overflow"
            with self.assertRaises(extraction.ExtractionError):
                extraction.save_partition(folder, spec(1), [[row()], [row(3)]], 1)
            self.assertFalse((folder/"manifest.json").exists())
            completed = extraction.save_partition(Path(tmp)/"exact", spec(2), [[row(), row(3)]])
            self.assertEqual(completed["validation"]["rows"], 2)

    def test_completed_restart_does_not_consume_query_or_overwrite(self):
        def forbidden():
            raise AssertionError("completed partition must not consume data")
            yield
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/"job"
            extraction.save_partition(folder, spec(), [[row()]])
            before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
            result = extraction.save_partition(folder, spec(), forbidden())
            self.assertEqual(result["validation"]["rows"], 1)
            self.assertEqual(before, {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()})

    def test_interrupted_restart_preserves_original_attempt(self):
        def interrupted():
            yield [row()]
            raise RuntimeError("synthetic interruption")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/"job"
            with self.assertRaises(RuntimeError):
                extraction.save_partition(folder, spec(), interrupted(), 1)
            original = next(folder.glob("attempt-*/part-*.parquet"))
            digest = extraction.sha256(original)
            extraction.save_partition(folder, spec(), [[row(), row(3)]])
            self.assertEqual(extraction.sha256(original), digest)
            self.assertEqual(len(list(folder.glob("attempt-*"))), 2)

    def test_checksum_corruption_and_incompatible_restart_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/"job"
            rec = extraction.save_partition(folder, spec(), [[row()]])
            with self.assertRaises(extraction.ExtractionError):
                extraction.verify_complete(folder, spec(20))
            path = folder/rec["files"][0]["file"]
            with path.open("ab") as stream:
                stream.write(b"corruption")
            with self.assertRaises(extraction.ExtractionError):
                extraction.verify_complete(folder, spec())

    def test_corrupt_manifest_and_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/"job"
            extraction.save_partition(folder, spec(), [[row()]])
            marker = folder/"manifest.json"
            data = json.loads(marker.read_text())
            data["files"][0]["file"] = "../../outside.parquet"
            marker.write_text(json.dumps(data))
            with self.assertRaises(extraction.ExtractionError):
                extraction.verify_complete(folder, spec())
            marker.write_text("not json")
            with self.assertRaises(extraction.ExtractionError):
                extraction.verify_complete(folder, spec())

    def test_all_null_chunk_then_decimal_chunk_preserves_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/"job"
            rec = extraction.save_partition(folder, spec(), [[row(ret=None)], [row(3, ret="0.123456789012345678")]], 1)
            tables = [extraction.pq.read_table(folder/f["file"]) for f in rec["files"]]
            self.assertEqual(tables[0].schema, tables[1].schema)
            self.assertIsNone(tables[0]["dlyret"][0].as_py())
            self.assertEqual(tables[1]["dlyret"][0].as_py(), Decimal("0.123456789012345678"))

    def test_decimal_not_silently_rounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/"job"
            with self.assertRaises(extraction.pa.ArrowInvalid):
                extraction.save_partition(folder, spec(), [[row(ret="0.1234567890123456789")]])
            self.assertFalse((folder/"manifest.json").exists())

    def test_streaming_moments_missing_and_flags_known_answers(self):
        st = extraction.Stats(spec())
        st.add([row(ret="0.1"), row(3, ret="-0.1")])
        st.add([row(4, ret=None), row(5, ret="0")])
        out = st.summary(); r = out["return_distributions"]["dlyret"]
        self.assertEqual(r["null"], 1)
        self.assertAlmostEqual(r["mean"], 0.)
        self.assertAlmostEqual(r["sd_sample"], .1)
        self.assertEqual(out["flags"]["dlyretmissflg"], {"NA": 3, "MP": 1})
        self.assertEqual(out["securities"], 1)
        json.dumps(out, allow_nan=False)

    def test_empty_coverage_is_explicit_not_assumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = extraction.save_partition(Path(tmp)/"job", spec(), [])
            self.assertTrue(rec["validation"]["empty_partition"])
            self.assertIsNone(rec["bytes_per_row"])
            self.assertEqual(rec["files"], [])

    def test_bounded_fetchmany_and_result_cleanup(self):
        class Result:
            calls = []
            closed = False
            def mappings(self): return self
            def fetchmany(self, n):
                self.calls.append(n)
                return [row()] if len(self.calls) == 1 else []
            def close(self): self.closed = True
        result = Result()
        class Connection:
            def execution_options(self, **kw):
                self.options = kw; return self
            def execute(self, query, params): return result
        conn = Connection()
        self.assertEqual(len(list(extraction.batches(conn, spec(), 2))), 1)
        self.assertEqual(result.calls, [2, 2])
        self.assertTrue(result.closed)
        self.assertTrue(conn.options["stream_results"])

    def test_pilot_b_combined_budget_and_fixed_windows(self):
        self.assertEqual(pilot_b.remaining_limit(199999), 1)
        with self.assertRaises(extraction.ExtractionError):
            pilot_b.remaining_limit(200000)
        label, start, end = pilot_b.WINDOWS[0]
        s = pilot_b.spec_for("stock", label, start, end, 199999)
        self.assertEqual(s["parameters"]["overflow_limit"], 2)
        index = pilot_b.spec_for("index", label, start, end)
        self.assertTrue(index["sql"].endswith("LIMIT 8"))
        with self.assertRaises(extraction.ExtractionError):
            pilot_b.spec_for("stock", label, start, date(1963, 7, 9))

    def test_preview_never_authenticates(self):
        for module in (extraction, pilot_b):
            with patch.object(sys, "argv", ["script"]), patch.object(extraction, "connection", side_effect=AssertionError("no authentication")), contextlib.redirect_stdout(stdio.StringIO()):
                self.assertEqual(module.main(), 0)

    def test_cost_extrapolation_known_measured_inputs(self):
        records = [{"stock": {"validation": {"rows": 100}, "elapsed_seconds": 10.,
                               "parquet_bytes": 1000},
                    "index": {"validation": {"date_counts": {"2020-01-02": 1}}}}]
        monthly = pd.DataFrame({"month": [date(2020, 1, 1)] * 2, "permno": [1, 2]})
        with patch.object(Path, "exists", return_value=True), patch.object(pilot_b.pd, "read_parquet", return_value=monthly):
            result = pilot_b.estimate_full(records)
        self.assertEqual(result["observed_period_row_proxy"], 42)
        self.assertEqual(result["measured_stock_rows_per_second"], 10.)
        self.assertEqual(result["measured_stock_parquet_bytes_per_row"], 10.)
        self.assertEqual(result["scenarios"][0]["parquet_bytes"], 1000000000)
        self.assertEqual(result["scenarios"][0]["seconds_at_pilot_rate"], 10000000)

    def test_error_output_does_not_echo_driver_secrets(self):
        self.assertNotIn("synthetic-secret", extraction.safe_failure(RuntimeError("synthetic-secret")))


if __name__ == "__main__":
    unittest.main()
