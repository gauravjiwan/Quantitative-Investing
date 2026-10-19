"""Synthetic French parsing/units/range/alignment tests; no network or credentials."""
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ps2.french import parse_daily, parse_ff12, classify_sic, align_daily_rf


def definitions():
    return "\n".join([f"{i} Test{i} Synthetic category\n {100*i:04d}-{100*i+9:04d}" for i in range(1, 12)] + ["12 Other Residual category"])


class FrenchTests(unittest.TestCase):
    def test_daily_percentage_conversion_and_missing_sentinels(self):
        data = parse_daily("Header\n,Mkt-RF,SMB,HML,RF\n20200102,1,-2,-99.99,0.01\n20200103,0,3,-999,0\n\n2020,1,2,3,4\n")
        self.assertEqual(len(data), 2)
        self.assertEqual(data.loc[0, "Mkt-RF"], .01)
        self.assertEqual(data.loc[0, "SMB"], -.02)
        self.assertEqual(data.loc[0, "RF"], .0001)
        self.assertEqual(int(data.HML.isna().sum()), 2)

    def test_daily_bad_dates_duplicates_and_order_rejected(self):
        for rows in ("20200230,1,2,3,4", "20200102,1,2,3,4\n20200102,1,2,3,4",
                     "20200103,1,2,3,4\n20200102,1,2,3,4"):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                parse_daily(",Mkt-RF,SMB,HML,RF\n" + rows)

    def test_missing_header_nonfinite_and_malformed_rows_rejected(self):
        for source in ("no header", ",Mkt-RF,SMB,HML,RF\n20200102,inf,2,3,4",
                       ",Mkt-RF,SMB,HML,RF\n20200102,abc,2,3,4",
                       ",Mkt-RF,SMB,HML,RF\n20200102,1,2,3"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                parse_daily(source)

    def test_ff12_all_synthetic_endpoints_and_neighbors(self):
        cat, rules = parse_ff12(definitions())
        self.assertEqual(len(cat), 12)
        for row in rules.itertuples(index=False):
            result = classify_sic([row.sic_start, row.sic_end, row.sic_end+1], rules)
            self.assertEqual(result.ff12.iloc[0], row.ff12)
            self.assertEqual(result.ff12.iloc[1], row.ff12)
            self.assertEqual(result.ff12.iloc[2], 12)

    def test_ff12_residual_and_invalid_codes_distinguished(self):
        _, rules = parse_ff12(definitions())
        out = classify_sic(pd.Series(["0100", 9999, None, "bad", 0, -1, 10000, 100.5, np.inf]), rules)
        self.assertEqual(out.ff12.iloc[0], 1)
        self.assertEqual(out.assignment.iloc[0], "explicit_range")
        self.assertEqual(out.ff12.iloc[1], 12)
        self.assertEqual(out.assignment.iloc[1], "residual_other")
        self.assertTrue(out.ff12.iloc[2:].isna().all())

    def test_ff12_overlaps_unknown_lines_and_changed_other_fail(self):
        for content in (definitions()+"\n 0100-0101", definitions()+"\nunknown text",
                        definitions().replace("12 Other", "12 Changed")):
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_ff12(content)

    def test_rf_alignment_uses_exact_dates_without_fill(self):
        daily = parse_daily(",Mkt-RF,SMB,HML,RF\n20200102,1,2,3,0.01\n20200103,1,2,3,0.01\n")
        index = pd.DataFrame({"dlycaldt": pd.to_datetime(["2020-01-02", "2020-01-04"]), "vwretd": [.01, -.01]})
        joined, report = align_daily_rf(index, daily)
        self.assertEqual(len(joined), 2)
        self.assertEqual(report["matched_dates"], 1)
        self.assertEqual(report["missing_french_dates"], ["2020-01-04"])
        self.assertEqual(report["french_dates_not_in_index_within_span"], ["2020-01-03"])
        self.assertTrue(pd.isna(joined.RF.iloc[1]))

    def test_rf_alignment_rejects_duplicate_dates(self):
        daily = parse_daily(",Mkt-RF,SMB,HML,RF\n20200102,1,2,3,0.01\n")
        index = pd.DataFrame({"dlycaldt": pd.to_datetime(["2020-01-02", "2020-01-02"]), "vwretd": [.01, .01]})
        with self.assertRaises(ValueError):
            align_daily_rf(index, daily)

    def test_official_link_selection_no_guessed_or_external_fallback(self):
        path = Path(__file__).resolve().parents[1]/"scripts/ps2_fetch_french.py"
        spec = importlib.util.spec_from_file_location("fetch_french_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        page = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html"
        link = module.official_link(page, '<a href="ftp/example.zip">CSV</a>', "example.zip")
        self.assertEqual(link, "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/example.zip")
        for html in ("", '<a href="https://example.com/example.zip">CSV</a>'):
            with self.assertRaises(ValueError):
                module.official_link(page, html, "example.zip")


if __name__ == "__main__":
    unittest.main()
