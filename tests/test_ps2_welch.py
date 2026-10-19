"""Authentication-free tests with synthetic, known-answer returns."""

import unittest

import numpy as np
import pandas as pd

from ps2.betas import ols_market_beta
from ps2.welch import (
    APPENDIX_RHO, appendix_weights, historical_welch_beta,
    slope_winsorize, welch_from_pairs,
)


class WelchTests(unittest.TestCase):
    def test_clips_positive_negative_zero_market_and_exact_bounds(self):
        np.testing.assert_allclose(
            slope_winsorize([.30, -.30, .30, -.30, .10, -.02, .04],
                            [.05, .05, -.05, -.05, 0., .01, .01]),
            [.20, -.10, .10, -.20, 0., -.02, .04],
        )

    def test_appendix_exact_exponential_objective_weights(self):
        self.assertEqual(APPENDIX_RHO, 2 / 256)
        np.testing.assert_allclose(appendix_weights(3, rho=APPENDIX_RHO),
                                   np.exp(-2 / 256 * np.array([3, 2, 1])))
        self.assertAlmostEqual(appendix_weights(91, rho=APPENDIX_RHO)[0] / appendix_weights(91, rho=APPENDIX_RHO)[-1],
                               np.exp(-90 * 2 / 256))
        self.assertGreater(appendix_weights(3, rho=APPENDIX_RHO)[-1], appendix_weights(3, rho=APPENDIX_RHO)[0])

    def test_known_no_outlier_slope_and_nonzero_intercept(self):
        x = np.array([-.03, -.01, .02, .04])
        y = .001 + 1.5 * x
        for aged in (False, True):
            result = welch_from_pairs(y, x, rho=APPENDIX_RHO if aged else 0.)
            self.assertEqual(result.status, "ok")
            self.assertAlmostEqual(result.beta, 1.5)
            self.assertAlmostEqual(result.alpha, .001)
            self.assertEqual(result.n_clipped, 0)

    def test_exact_clipped_answer(self):
        # After clipping: x=(-.02,-.01,.01,.02), y=(-.08,-.04,.04,.08).
        result = welch_from_pairs([-.9, -.9, .9, .9], [-.02, -.01, .01, .02], rho=APPENDIX_RHO)
        self.assertAlmostEqual(result.beta, 4.)
        self.assertAlmostEqual(result.alpha, 0.)
        self.assertEqual(result.n_clipped, 4)

    def test_against_independent_sqrt_weighted_lstsq(self):
        x = np.array([-.04, -.01, .02, .05, -.02])
        y = np.array([.03, -.08, .10, -.03, .02])
        clipped = np.array([.03, -.04, .08, -.03, .02])
        for aged in (True, False):
            w = appendix_weights(len(x), rho=APPENDIX_RHO) if aged else np.ones(len(x))
            design = np.column_stack([np.ones(len(x)), x])
            expected = np.linalg.lstsq(design * np.sqrt(w)[:, None], clipped * np.sqrt(w), rcond=None)[0]
            result = welch_from_pairs(y, x, rho=APPENDIX_RHO if aged else 0.)
            np.testing.assert_allclose([result.alpha, result.beta], expected, atol=1e-14)

    def test_unaged_unclipped_matches_existing_ols(self):
        dates = pd.date_range("2020-01-01", periods=4)
        x = pd.Series([-.03, -.01, .02, .04], dates)
        y = .001 + 1.5 * x
        ols = ols_market_beta(y, x, as_of=dates[-1], min_observations=2)
        result = welch_from_pairs(y, x, rho=0.)
        self.assertAlmostEqual(result.beta, ols.beta)
        self.assertAlmostEqual(result.alpha, ols.alpha)

    def test_kernel_rejects_bad_pairs_and_configuration(self):
        for y, x in [([1], [1, 2]), ([[1, 2]], [[1, 2]]), ([np.nan], [0]), ([0], [np.inf])]:
            with self.assertRaises(ValueError):
                welch_from_pairs(y, x, rho=APPENDIX_RHO)
        for n in (-1, True, 1.1):
            with self.assertRaises(ValueError):
                appendix_weights(n, rho=APPENDIX_RHO)
        with self.assertRaises(ValueError):
            welch_from_pairs([0, .1], [0, .1], rho="yes")

    def test_degenerate_samples_return_explicit_status(self):
        self.assertEqual(welch_from_pairs([], [], rho=APPENDIX_RHO).status, "insufficient_history")
        self.assertEqual(welch_from_pairs([.1], [.1], rho=APPENDIX_RHO).status, "insufficient_history")
        result = welch_from_pairs([.1, .2, .3], [.1, .1, .1], rho=APPENDIX_RHO)
        self.assertEqual(result.status, "zero_market_variance")
        self.assertTrue(np.isnan(result.beta))

    def test_underflowed_weight_sum_returns_numerical_failure(self):
        result = welch_from_pairs([-.01, .02], [-.01, .02], rho=1e6)
        self.assertEqual(result.status, "numerical_failure")
        self.assertEqual(result.weight_sum, 0.)
        self.assertTrue(np.isnan(result.alpha))
        self.assertTrue(np.isnan(result.beta))

    def setUp(self):
        self.dates = pd.bdate_range("2020-01-01", periods=6)
        self.x = pd.Series([-.03, -.01, .02, .04, -.02, .03], self.dates)
        self.y = pd.Series([.01, -.02, .02, .04, -.03, .02], self.dates)
        self.kw = dict(as_of=self.dates[-1], trading_calendar=self.dates,
                       min_observations=2, require_current_return=True, age_basis="valid_pairs", rho=APPENDIX_RHO)

    def test_complete_history_adapter_matches_appendix(self):
        result = historical_welch_beta(self.y, self.x, **self.kw)
        core = welch_from_pairs(self.y, self.x, rho=APPENDIX_RHO)
        self.assertEqual(result.fit, core)
        self.assertEqual(result.n_unusable_stock, 0)
        self.assertTrue(result.current_return_available)

    def test_future_poison_and_order_do_not_change_historical_result(self):
        kw = dict(self.kw, as_of=self.dates[-2])
        original = historical_welch_beta(self.y, self.x, **kw)
        poisoned = self.y.copy()
        poisoned.iloc[-1] = 1e6
        result = historical_welch_beta(poisoned.iloc[::-1], self.x.iloc[::-1], **kw)
        self.assertEqual(original, result)
        self.assertLessEqual(result.last_used_date, kw["as_of"])

    def test_gapped_calendar_aging_is_explicit_and_independently_verified(self):
        y = self.y.copy()
        y.iloc[1:3] = np.nan
        paired = historical_welch_beta(y, self.x, **self.kw)
        calendar = historical_welch_beta(y, self.x, **dict(self.kw, age_basis="market_calendar"))
        self.assertEqual(calendar.n_unusable_stock, 2)
        self.assertNotAlmostEqual(paired.fit.beta, calendar.fit.beta, places=7)
        keep = y.notna()
        x = self.x[keep].to_numpy()
        w = appendix_weights(6, rho=APPENDIX_RHO)[keep]
        design = np.column_stack([np.ones(len(x)), x])
        expected = np.linalg.lstsq(design * np.sqrt(w)[:, None], y[keep] * np.sqrt(w), rcond=None)[0]
        np.testing.assert_allclose([calendar.fit.alpha, calendar.fit.beta], expected)

    def test_paper_minimum_and_current_day_can_be_requested_explicitly(self):
        result = historical_welch_beta(self.y, self.x, **dict(self.kw, min_observations=20))
        self.assertEqual(result.fit.status, "insufficient_history")
        y = self.y.copy()
        y.iloc[-1] = np.nan
        result = historical_welch_beta(y, self.x, **self.kw)
        self.assertEqual(result.fit.status, "missing_current_return")
        result = historical_welch_beta(y, self.x, **dict(self.kw, require_current_return=False))
        self.assertEqual(result.fit.status, "ok")

    def test_last_session_not_weekend_cutoff(self):
        dates = pd.to_datetime(["2020-01-29", "2020-01-30", "2020-01-31"])
        x = pd.Series([-.01, .01, .02], dates)
        result = historical_welch_beta(x, x, **dict(self.kw, as_of="2020-02-02", trading_calendar=dates))
        self.assertEqual(result.last_market_date, pd.Timestamp("2020-01-31"))
        self.assertTrue(result.current_return_available)

    def test_invalid_dates_missing_calendar_and_bad_policies_rejected(self):
        for update in [dict(min_observations=True), dict(require_current_return=1),
                       dict(age_basis="guess"), dict(as_of="2020-01-01 12:00"),
                       dict(trading_calendar=self.dates[:-1]),
                       dict(trading_calendar=self.dates.append(self.dates[-1:]))]:
            with self.assertRaises(ValueError):
                historical_welch_beta(self.y, self.x, **dict(self.kw, **update))
        duplicate = pd.concat([self.y, self.y.iloc[-1:]])
        with self.assertRaises(ValueError):
            historical_welch_beta(duplicate, self.x, **self.kw)


if __name__ == "__main__":
    unittest.main()
