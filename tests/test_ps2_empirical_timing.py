from pathlib import Path
import sys,unittest
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ps2.empirical_timing import formation_year_at_origin,assert_month_end_information


class TimingTests(unittest.TestCase):
    def test_june_end_new_formation_not_return_month_vintage(self):
        self.assertEqual(formation_year_at_origin('2000-05-01'),1999)
        self.assertEqual(formation_year_at_origin('2000-06-01'),2000)
        self.assertEqual(formation_year_at_origin('2000-07-01'),2000)
        self.assertEqual(formation_year_at_origin('2001-01-01'),2000)

    def test_month_start_label_does_not_imply_availability(self):
        self.assertEqual(assert_month_end_information('2000-02-01','2000-02-29'),pd.Timestamp('2000-02-29'))
        with self.assertRaises(ValueError):assert_month_end_information('2000-02-01','2000-03-01')
