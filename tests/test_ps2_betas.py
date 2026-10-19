"""Offline, synthetic tests only: no WRDS authentication or research data."""
import unittest

import numpy as np
import pandas as pd

from ps2.betas import expanding_beta, ols_market_beta, one_year_beta, three_year_beta


class BetaTests(unittest.TestCase):
    def setUp(self):
        self.dates = pd.date_range("2020-01-01", periods=5)
        self.x = pd.Series([-.02, -.01, 0., .01, .03], index=self.dates)
        self.y = .001 + 1.5 * self.x
        self.options = dict(as_of="2020-01-31", min_observations=2)

    def test_known_slope_intercept_and_decimal_units(self):
        for estimator in (one_year_beta, three_year_beta, expanding_beta):
            result = estimator(self.y, self.x, **self.options)
            self.assertEqual(result.status, "ok")
            self.assertAlmostEqual(result.beta, 1.5)
            self.assertAlmostEqual(result.alpha, .001)
            self.assertEqual(result.n_observations, 5)
            self.assertAlmostEqual(result.market_variance, self.x.var(ddof=1))
        # Joint unit scaling leaves beta invariant but changes intercept units.
        percent = expanding_beta(100*self.y, 100*self.x, **self.options)
        self.assertAlmostEqual(percent.beta, 1.5)
        self.assertAlmostEqual(percent.alpha, .1)

    def test_independent_lstsq_and_covariance_benchmarks(self):
        y = self.y + pd.Series([.002, -.001, .003, -.002, .001], index=self.dates)
        result = expanding_beta(y, self.x, **self.options)
        expected = np.linalg.lstsq(np.column_stack([np.ones(5), self.x]), y, rcond=None)[0]
        np.testing.assert_allclose([result.alpha, result.beta], expected, atol=1e-14)
        self.assertAlmostEqual(result.beta, y.cov(self.x)/self.x.var())

    def test_one_year_calendar_boundary_and_leap_day(self):
        dates = pd.to_datetime(["2019-02-28", "2019-03-01", "2020-02-28", "2020-02-29", "2020-03-01"])
        x = pd.Series([100, -.02, .01, .03, 999], index=dates)
        y = .002 + 2*x
        y.iloc[0] = -1000
        result = one_year_beta(y, x, as_of="2020-02-29", min_observations=3)
        self.assertEqual(result.window_start_exclusive, pd.Timestamp("2019-02-28"))
        self.assertEqual(result.n_window_dates, 3)
        self.assertEqual(result.first_used_date, pd.Timestamp("2019-03-01"))
        self.assertEqual(result.last_used_date, pd.Timestamp("2020-02-29"))
        self.assertAlmostEqual(result.beta, 2)

    def test_three_year_and_expanding_history_are_distinct(self):
        dates = pd.to_datetime(["2016-12-30", "2017-01-31", "2017-02-01", "2020-01-30", "2020-01-31"])
        x = pd.Series([-.02, -.01, 0, .01, .03], index=dates)
        y = .002 + 2*x
        trailing = three_year_beta(y, x, **self.options)
        full = expanding_beta(y, x, **self.options)
        self.assertEqual(trailing.n_observations, 3)
        self.assertEqual(full.n_observations, 5)
        self.assertIsNone(full.window_start_exclusive)

    def test_future_perturbations_do_not_change_estimate(self):
        for estimator in (one_year_beta, three_year_beta, expanding_beta):
            before = estimator(self.y, self.x, **self.options)
            x = pd.concat([self.x, pd.Series([np.inf, 10000], index=pd.to_datetime(["2020-02-01", "2021-01-01"]))])
            y = pd.concat([self.y, pd.Series([np.nan, -10000], index=pd.to_datetime(["2020-02-01", "2021-01-01"]))])
            self.assertEqual(before, estimator(y, x, **self.options))

    def test_exact_date_pairing_missingness_and_nonfinite_counts(self):
        x = self.x.copy()
        x.iloc[0] = np.inf
        y = self.y.drop(self.dates[1])
        y.loc[pd.Timestamp("2020-01-06")] = .08
        result = expanding_beta(y, x, **self.options)
        self.assertEqual(result.n_window_dates, 6)
        self.assertEqual(result.n_observations, 3)
        self.assertEqual(result.n_unusable_stock, 1)
        self.assertEqual(result.n_unusable_market, 2)
        self.assertAlmostEqual(result.beta, 1.5)

    def test_unsorted_inputs_and_no_mutation(self):
        y = self.y.iloc[::-1].copy()
        original = y.copy()
        result = expanding_beta(y, self.x, **self.options)
        self.assertAlmostEqual(result.beta, 1.5)
        pd.testing.assert_series_equal(y, original)

    def test_insufficient_history_retains_diagnostics(self):
        result = expanding_beta(self.y, self.x, as_of="2020-01-01", min_observations=2)
        self.assertEqual(result.status, "insufficient_history")
        self.assertEqual(result.n_observations, 1)
        self.assertEqual(result.last_used_date, self.dates[0])
        self.assertTrue(np.isnan(result.beta))
        empty = expanding_beta(self.y, self.x, as_of="2019-12-31", min_observations=2)
        self.assertEqual(empty.n_window_dates, 0)
        self.assertIsNone(empty.first_used_date)

    def test_zero_variance_rejected_but_constant_stock_allowed(self):
        flat_market = pd.Series(0., index=self.dates)
        result = expanding_beta(self.y, flat_market, **self.options)
        self.assertEqual(result.status, "zero_market_variance")
        self.assertTrue(np.isnan(result.alpha))
        dates = pd.date_range("2020-01-01", periods=6)
        flat_nonzero = pd.Series(.1, index=dates)
        result = expanding_beta(pd.Series(range(6), index=dates), flat_nonzero, **self.options)
        self.assertEqual(result.status, "zero_market_variance")
        flat_stock = pd.Series(.01, index=self.dates)
        result = expanding_beta(flat_stock, self.x, **self.options)
        self.assertEqual(result.status, "ok")
        self.assertAlmostEqual(result.beta, 0.)
        self.assertAlmostEqual(result.alpha, .01)

    def test_invalid_dates_and_duplicate_keys(self):
        indices = [pd.Index(range(5)),
                   pd.to_datetime(["2020-01-01"]*5),
                   pd.to_datetime([None, "2020-01-02", "2020-01-03", "2020-01-04", "2020-01-05"]),
                   self.dates.tz_localize("UTC"),
                   pd.date_range("2020-01-01 01:00", periods=5)]
        for dates in indices:
            bad = pd.Series(self.x.to_numpy(), index=dates)
            with self.subTest(dates=dates):
                with self.assertRaises((ValueError, TypeError)):
                    expanding_beta(self.y, bad, **self.options)
                with self.assertRaises((ValueError, TypeError)):
                    expanding_beta(bad, self.x, **self.options)

    def test_configuration_requires_explicit_research_minimum(self):
        for minimum in [0, 1, True, 2.5, None]:
            with self.assertRaises(ValueError):
                expanding_beta(self.y, self.x, as_of="2020-01-31", min_observations=minimum)
        with self.assertRaises(TypeError):
            expanding_beta(self.y, self.x, as_of="2020-01-31")
        for cutoff in [None, pd.NaT, "2020-01-31 01:00", "2020-01-31T00:00Z"]:
            with self.assertRaises(ValueError):
                expanding_beta(self.y, self.x, as_of=cutoff, min_observations=2)
        for years in [0, 2, 1.0, True]:
            with self.assertRaises(ValueError):
                ols_market_beta(self.y, self.x, years=years, **self.options)


if __name__ == "__main__":
    unittest.main()
