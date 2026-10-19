"""Offline synthetic tests for bounded extraction and reconciliation; no WRDS."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from decimal import Decimal

import pandas as pd

SPEC = importlib.util.spec_from_file_location(
    "ps2_pilot", Path(__file__).resolve().parents[1] / "scripts/ps2_pilot_wrds.py")
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


def fixture():
    dates = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-02-03", "2020-02-04"])
    previous = pd.to_datetime(["2019-12-31", "2020-01-02", "2020-01-03", "2020-02-03"])
    rows, history, monthly = [], [], []
    for p in pilot.IDS:
        for d, prev, ret in zip(dates, previous, [.1, -.05, .02, .03]):
            rows.append(dict(permno=p, dlycaldt=d, dlyprevdt=prev, dlyret=ret,
                             dlyretx=ret, dlyretmissflg=None, dlyretdurflg="TEST",
                             dlydelflg="N"))
        history.append(dict(permno=p, secinfostartdt=pd.Timestamp("2010-01-01"),
                            secinfoenddt=pd.Timestamp("2021-01-01"), siccd=3571))
        monthly.extend([dict(permno=p, month=pd.Timestamp("2020-01-31"), ret=.045),
                        dict(permno=p, month=pd.Timestamp("2020-02-29"), ret=.0506)])
    return {"stock": pd.DataFrame(rows),
            "index": pd.DataFrame(dict(dlycaldt=dates, vwretd=[.01, -.01, .02, 0.])),
            "sic": pd.DataFrame(history)}, pd.DataFrame(monthly)


class PilotTests(unittest.TestCase):
    def test_validation_report_is_json_serializable(self):
        frames, monthly = fixture()
        report = pilot.validate(frames, monthly)
        decoded = pilot.json.loads(pilot.json.dumps(report, allow_nan=False))
        self.assertTrue(decoded["reconciliation"][1]["comparable"])
        self.assertFalse(decoded["reconciliation"][0]["comparable"])

    def test_auth_preserves_existing_lookup(self):
        with patch.object(pilot, "_saved_wrds_username", return_value="synthetic_user"), patch.object(Path, "read_text", side_effect=AssertionError("unexpected passfile read")):
            self.assertEqual(pilot.local_auth(), ("synthetic_user", {}))

    def test_windows_auth_fallback_matches_target_and_does_not_return_password(self):
        content = ("# comment\nwronghost:9737:wrds:wrong:synthetic_secret\n"
                   "malformed\n*:9737:wrds:synthetic_user:synthetic_secret\n")
        with patch.object(pilot, "_saved_wrds_username", return_value=None), patch.dict(pilot.os.environ, {"APPDATA": "C:/synthetic"}, clear=True), patch.object(Path, "is_file", return_value=True), patch.object(Path, "read_text", return_value=content):
            username, options = pilot.local_auth()
            self.assertEqual(username, "synthetic_user")
            self.assertTrue(options["passfile"].endswith("pgpass.conf"))
            self.assertNotIn("synthetic_secret", repr((username, options)))

    def test_auth_never_replaces_explicit_passfile(self):
        with patch.object(pilot, "_saved_wrds_username", return_value=None), patch.dict(pilot.os.environ, {"PGPASSFILE": "explicit", "APPDATA": "C:/synthetic"}, clear=True), patch.object(Path, "read_text", side_effect=AssertionError("unexpected fallback")):
            self.assertEqual(pilot.local_auth(), (None, {}))

    def test_auth_missing_unmatched_and_unreadable_passfile(self):
        with patch.object(pilot, "_saved_wrds_username", return_value=None), patch.dict(pilot.os.environ, {"APPDATA": "C:/synthetic"}, clear=True):
            with patch.object(Path, "is_file", return_value=False):
                self.assertEqual(pilot.local_auth(), (None, {}))
            with patch.object(Path, "is_file", return_value=True), patch.object(Path, "read_text", return_value="wrong:9737:wrds:user:synthetic_secret"):
                self.assertEqual(pilot.local_auth(), (None, {}))
            with patch.object(Path, "is_file", return_value=True), patch.object(Path, "read_text", side_effect=PermissionError):
                self.assertEqual(pilot.local_auth(), (None, {}))

    def test_parquet_preserves_decimal_dates_and_null_flags(self):
        frame = pd.DataFrame({"ret": [Decimal("0.012345678901"), None],
                              "date": [pilot.date(2020, 1, 2), None],
                              "flag": ["UNUSUAL", None]})
        buffer = pilot.pa.BufferOutputStream()
        pilot.pq.write_table(pilot.pa.Table.from_pandas(frame, preserve_index=False), buffer)
        restored = pilot.pq.read_table(pilot.pa.BufferReader(buffer.getvalue())).to_pandas()
        self.assertEqual(restored.ret.iloc[0], Decimal("0.012345678901"))
        self.assertEqual(restored.date.iloc[0], pilot.date(2020, 1, 2))
        self.assertEqual(restored.flag.iloc[0], "UNUSUAL")
        self.assertTrue(pd.isna(restored.flag.iloc[1]))

    def test_compound_known_answer_and_total_loss(self):
        self.assertAlmostEqual(pilot.compound([.1, -.05]), .045)
        self.assertEqual(pilot.compound([-1., .2]), -1.)

    def test_missing_invalid_and_empty_never_skipped(self):
        for values in ([.1, None], [float("inf")], [-1.1], []):
            self.assertIsNone(pilot.compound(values))

    def test_guard_rejects_wider_ids_and_dates(self):
        pilot.guard_scope(pilot.PARAMS)
        for key, value in (("p1", 99999), ("end_date", pilot.date(2021, 1, 1))):
            with self.assertRaises(pilot.PilotError):
                pilot.guard_scope(dict(pilot.PARAMS, **{key: value}))

    def test_returned_scope_and_overflow(self):
        frames, _ = fixture()
        for name, f in frames.items():
            pilot.check_scope(name, f)
        for name in ("stock", "index", "sic"):
            with self.assertRaises(pilot.PilotError):
                pilot.check_scope(name, pd.concat([frames[name]] * 200, ignore_index=True))
        bad = frames["stock"].copy()
        bad.loc[0, "dlycaldt"] = pd.Timestamp("2020-03-01")
        with self.assertRaises(pilot.PilotError):
            pilot.check_scope("stock", bad)

    def test_reconciliation_labels_units_boundary_and_no_mutation(self):
        frames, monthly = fixture()
        original = frames["stock"].copy(deep=True)
        checks = pilot.validate(frames, monthly)
        self.assertEqual(len(checks["reconciliation"]), 6)
        jan, feb = checks["reconciliation"][:2]
        self.assertFalse(jan["comparable"])
        self.assertTrue(jan["boundary_unverified"])
        self.assertTrue(feb["comparable"])
        self.assertAlmostEqual(feb["gap"], 0., places=14)
        self.assertEqual(checks["flags"]["dlyretdurflg"], {"TEST": 12})
        pd.testing.assert_frame_equal(frames["stock"], original)

    def test_missing_and_duplicate_rows_are_reported(self):
        frames, monthly = fixture()
        frames["stock"].loc[0, "dlyret"] = None
        frames["stock"] = pd.concat([frames["stock"], frames["stock"].iloc[[1]]], ignore_index=True)
        checks = pilot.validate(frames, monthly)
        self.assertEqual(checks["stock"]["duplicate_keys"], 1)
        self.assertIsNone(checks["reconciliation"][0]["daily_compounded"])
        self.assertFalse(checks["reconciliation"][0]["calendar_complete"])

    def test_reconciliation_discrepancy_is_not_corrected(self):
        frames, monthly = fixture()
        monthly.loc[1, "ret"] = .2
        checks = pilot.validate(frames, monthly)
        self.assertAlmostEqual(checks["reconciliation"][1]["gap"], -.1494)
        self.assertTrue(checks["reconciliation"][1]["gap_above_1e_8"])
        self.assertEqual(monthly.loc[1, "ret"], .2)

    def test_missing_day_and_sic_overlap(self):
        frames, monthly = fixture()
        frames["stock"] = frames["stock"].drop(index=3)
        frames["sic"] = pd.concat([frames["sic"], frames["sic"].iloc[[0]]], ignore_index=True)
        checks = pilot.validate(frames, monthly)
        self.assertFalse(checks["reconciliation"][1]["calendar_complete"])
        self.assertEqual(checks["sic_overlap_pairs"], 1)
        self.assertEqual(checks["sic_month_end_matches"][0]["matches"], 2)

    def test_null_dates_and_broken_previous_chain(self):
        frames, monthly = fixture()
        frames["stock"].loc[0, "dlycaldt"] = pd.NaT
        frames["stock"].loc[3, "dlyprevdt"] = pd.Timestamp("2020-02-04")
        checks = pilot.validate(frames, monthly)
        self.assertEqual(checks["stock"]["null_key_rows"], 1)
        self.assertEqual(checks["previous_dates"]["not_before_current"], 1)
        self.assertFalse(checks["reconciliation"][1]["comparable"])


if __name__ == "__main__":
    unittest.main()
