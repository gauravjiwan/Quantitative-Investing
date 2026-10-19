"""Known-answer Q2 tests; no authentication, downloads or research data."""
import unittest

import numpy as np
import pandas as pd

from ps2.factor_forecasts import (
    FACTORS, evaluate_loss_periods, expanding_mean_forecast,
    expanding_predictive_forecast, joint_factor_exposure,
    matched_monthly_losses, paired_loss_inference, stock_return_forecasts,
)


class FactorForecastTests(unittest.TestCase):
    def setUp(self):
        self.months = pd.period_range("2000-01", periods=8, freq="M")
        self.factors = pd.DataFrame({
            "Mkt-RF": [-.03, -.02, -.01, 0, .01, .02, .03, .04],
            "HML": [-.03, -.01, -.03, .01, 0, .04, .02, .05],
            "SMB": [.01, -.02, .03, -.04, .02, .01, -.01, .03],
        }, index=self.months)
        self.beta = np.array([1.5, -.7, .4])
        self.stock = .003 + self.factors @ self.beta
        self.cutoff = self.months[-1]

    def exposure(self, **kwargs):
        options = dict(as_of=self.cutoff, min_observations=4, window_months=None, fit_intercept=True)
        options.update(kwargs)
        return joint_factor_exposure(self.stock, self.factors, **options)

    def test_joint_exposure_known_answer_and_univariate_distinction(self):
        result = self.exposure()
        self.assertEqual(result.status, "ok")
        np.testing.assert_allclose(result.beta, self.beta, atol=1e-13)
        self.assertAlmostEqual(result.alpha, .003)
        self.assertEqual(result.n_observations, 8)
        univariate = self.stock.cov(self.factors["Mkt-RF"])/self.factors["Mkt-RF"].var()
        self.assertGreater(abs(univariate-result.beta["Mkt-RF"]), .1)
        benchmark = np.linalg.lstsq(np.column_stack([np.ones(8), self.factors]), self.stock, rcond=None)[0]
        np.testing.assert_allclose(np.r_[result.alpha, result.beta], benchmark, atol=1e-13)

    def test_explicit_no_intercept_exposure(self):
        result = joint_factor_exposure(self.factors@self.beta, self.factors, as_of=self.cutoff,
                                       min_observations=3, window_months=None, fit_intercept=False)
        self.assertEqual(result.alpha, 0)
        np.testing.assert_allclose(result.beta, self.beta, atol=1e-13)

    def test_window_boundary_missingness_and_rank_failure(self):
        result = self.exposure(window_months=4)
        self.assertEqual(result.n_window_months, 4)
        self.assertEqual(result.first_used_month, self.months[-4])
        factors = self.factors.copy()
        factors.iloc[0, 0] = np.inf
        stock = self.stock.drop(self.months[1])
        missing = joint_factor_exposure(stock, factors, as_of=self.cutoff, min_observations=4,
                                        window_months=None, fit_intercept=True)
        self.assertEqual((missing.n_observations, missing.n_incomplete), (6, 2))
        factors["SMB"] = factors["HML"]
        rank = joint_factor_exposure(self.stock, factors, as_of=self.cutoff, min_observations=4,
                                     window_months=None, fit_intercept=True)
        self.assertEqual(rank.status, "rank_deficient")
        self.assertTrue(rank.beta.isna().all())
        self.assertEqual(self.exposure(min_observations=9).status, "insufficient_history")

    def test_future_perturbation_never_changes_beta_or_premium_forecast(self):
        cutoff = self.months[5]
        before_beta = self.exposure(as_of=cutoff)
        before_mean = expanding_mean_forecast(self.factors, as_of=cutoff, min_observations=2)
        altered = self.factors.copy()
        altered.loc[altered.index > cutoff] = 999999.
        stock = self.stock.copy()
        stock.loc[stock.index > cutoff] = -999999.
        after_beta = joint_factor_exposure(stock, altered, as_of=cutoff, min_observations=4,
                                          window_months=None, fit_intercept=True)
        after_mean = expanding_mean_forecast(altered, as_of=cutoff, min_observations=2)
        pd.testing.assert_series_equal(before_beta.beta, after_beta.beta)
        pd.testing.assert_series_equal(before_mean.value, after_mean.value)
        self.assertEqual(after_beta.last_used_month, cutoff)
        self.assertEqual(after_mean.target_month, cutoff+1)

    def test_expanding_mean_decimal_units_common_complete_months(self):
        frame = self.factors.copy()
        frame.iloc[1, 1] = np.nan
        result = expanding_mean_forecast(frame, as_of=self.months[3], min_observations=3)
        self.assertEqual((result.n_candidates, result.n_observations, result.n_incomplete), (4, 3, 1))
        np.testing.assert_allclose(result.value, frame.iloc[[0, 2, 3]].mean())
        self.assertEqual(result.last_outcome_month, self.months[3])
        insufficient = expanding_mean_forecast(frame, as_of=self.months[3], min_observations=4)
        self.assertEqual(insufficient.status, "insufficient_history")
        self.assertTrue(insufficient.value.isna().all())

    def predictive_data(self):
        origins = pd.period_range("1999-12", periods=10, freq="M")
        z = pd.DataFrame({"value_spread": np.arange(10)/10}, index=origins)
        outcomes = pd.DataFrame(np.array([.01, -.02, .003])+z.to_numpy()*np.array([.02, .01, -.01]),
                                index=origins+1, columns=FACTORS)
        return z, outcomes

    def test_predictive_ols_known_answer_excludes_current_target(self):
        z, outcomes = self.predictive_data()
        cutoff = pd.Period("2000-07", "M")
        before = expanding_predictive_forecast(outcomes, z, as_of=cutoff, min_observations=3)
        np.testing.assert_allclose(before.value, [.01, -.02, .003]+z.loc[cutoff].iloc[0]*np.array([.02, .01, -.01]))
        self.assertEqual(before.last_outcome_month, cutoff)
        outcomes.loc[outcomes.index > cutoff] = np.inf
        z.loc[z.index > cutoff] = np.nan
        after = expanding_predictive_forecast(outcomes, z, as_of=cutoff, min_observations=3)
        pd.testing.assert_series_equal(before.value, after.value)

    def test_predictive_calendar_gaps_use_exact_next_month_not_next_row(self):
        z, outcomes = self.predictive_data()
        z = z.drop(pd.Period("2000-02", "M"))
        outcomes = outcomes.drop(pd.Period("2000-05", "M"))
        cutoff = pd.Period("2000-07", "M")
        result = expanding_predictive_forecast(outcomes, z, as_of=cutoff, min_observations=3)
        self.assertEqual(result.n_observations, 5)
        np.testing.assert_allclose(result.value, [.024, -.013, -.004], atol=1e-14)
        self.assertEqual(result.n_incomplete, 2)

    def test_predictive_rank_minimum_and_missing_current(self):
        z, outcomes = self.predictive_data()
        z.iloc[:] = 1.
        rank = expanding_predictive_forecast(outcomes, z, as_of=self.cutoff, min_observations=2)
        self.assertEqual(rank.status, "rank_deficient")
        z.loc[self.cutoff] = np.nan
        missing = expanding_predictive_forecast(outcomes, z, as_of=self.cutoff, min_observations=2)
        self.assertEqual(missing.status, "missing_current_predictors")
        self.assertTrue(missing.value.isna().all())

    def test_stock_forecasts_fixed_joint_betas_and_no_alpha(self):
        premium = expanding_mean_forecast(self.factors, as_of=self.cutoff, min_observations=4)
        other = expanding_mean_forecast(2*self.factors, as_of=self.cutoff, min_observations=4)
        market = expanding_mean_forecast(self.factors["Mkt-RF"], as_of=self.cutoff, min_observations=4)
        beta = self.exposure()
        original = beta.beta.copy()
        forecasts = stock_return_forecasts({123: beta, 456: beta}, {"mean": premium, "candidate": other}, market)
        np.testing.assert_allclose(forecasts["mean"], self.beta@premium.value)
        np.testing.assert_allclose(forecasts.candidate, 2*forecasts["mean"])
        np.testing.assert_allclose(forecasts.crsp_mean, market.value.iloc[0])
        pd.testing.assert_series_equal(original, beta.beta)
        self.assertTrue((forecasts.month == self.cutoff+1).all())
        early = expanding_mean_forecast(self.factors, as_of=self.cutoff-1, min_observations=4)
        with self.assertRaises(ValueError):
            stock_return_forecasts({123: beta}, {"early": early}, market)

    def loss_panel(self):
        return pd.DataFrame({"security": [1, 2, 3, 1], "month": [self.months[0]]*3+[self.months[1]],
                             "actual": [0., 0., 0., 0.], "baseline": [1., 3., 100., 2.],
                             "candidate": [0., 1., np.nan, 1.], "weight": [1., 3., 100., 1.]})

    def test_matched_monthly_weighted_mse_then_equal_month_mean(self):
        panel = self.loss_panel()
        losses = matched_monthly_losses(panel, forecast_columns=["baseline", "candidate"],
                                        actual_column="actual", weight_column="weight")
        np.testing.assert_allclose(losses.baseline, [7., 4.])
        np.testing.assert_allclose(losses.candidate, [.75, 1.])
        self.assertEqual(list(losses.n_matched), [2, 1])
        self.assertEqual(list(losses.n_excluded), [1, 0])
        ew = matched_monthly_losses(panel, forecast_columns=["baseline", "candidate"],
                                    actual_column="actual", weight_column=None)
        self.assertEqual(ew.baseline.iloc[0], 5)
        summary = evaluate_loss_periods(losses, model_columns=["baseline", "candidate"],
                                       benchmark="baseline", first_oos_month=self.months[0])
        row = summary[(summary.period == "out_of_sample") & (summary.model == "candidate")].iloc[0]
        self.assertEqual(row.mse, .875)
        self.assertAlmostEqual(row.pseudo_r2, 1-.875/5.5)
        # Unequal stock counts must not implicitly overweight the first month.
        self.assertEqual(row.n_months, 2)

    def test_loss_zero_benchmark_and_split(self):
        losses = pd.DataFrame({"month": self.months[:3], "baseline": [4., 0., 0.], "candidate": [1., 2., 2.]})
        result = evaluate_loss_periods(losses, model_columns=["baseline", "candidate"],
                                      benchmark="baseline", first_oos_month=self.months[1])
        inside = result[(result.period == "in_sample") & (result.model == "candidate")].iloc[0]
        self.assertEqual(inside.pseudo_r2, .75)
        outside = result[result.period == "out_of_sample"]
        self.assertTrue(outside.pseudo_r2.isna().all())
        self.assertTrue((outside.status == "zero_benchmark_mse").all())

    def test_duplicate_null_keys_and_invalid_weights_raise(self):
        panel = self.loss_panel()
        opts = dict(forecast_columns=["baseline", "candidate"], actual_column="actual", weight_column="weight")
        with self.assertRaises(ValueError):
            matched_monthly_losses(pd.concat([panel, panel.iloc[:1]]), **opts)
        panel.loc[0, "weight"] = 0.
        with self.assertRaises(ValueError):
            matched_monthly_losses(panel, **opts)
        panel.loc[0, "security"] = np.nan
        with self.assertRaises(ValueError):
            matched_monthly_losses(panel, **opts)

    def test_all_missing_month_retained_in_counts(self):
        panel = self.loss_panel()
        panel.loc[panel.month == self.months[1], "candidate"] = np.nan
        losses = matched_monthly_losses(panel, forecast_columns=["baseline", "candidate"],
                                        actual_column="actual", weight_column=None)
        self.assertEqual(losses.n_matched.iloc[1], 0)
        self.assertTrue(losses[["baseline", "candidate"]].iloc[1].isna().all())

    def test_newey_west_known_answer_and_independent_statsmodels(self):
        losses = pd.DataFrame({"month": self.months[:4], "candidate": [1., 2., 3., 4.], "baseline": 0.})
        result = paired_loss_inference(losses, model="candidate", benchmark="baseline", newey_west_lags=1)
        self.assertEqual(result["mean_loss_difference"], 2.5)
        self.assertAlmostEqual(result["standard_error"], .625)
        self.assertAlmostEqual(result["t_statistic"], 4.)
        import statsmodels.api as sm
        fit = sm.OLS(losses.candidate, np.ones((4, 1))).fit(cov_type="HAC", cov_kwds={"maxlags": 1, "use_correction": False})
        self.assertAlmostEqual(result["standard_error"], fit.bse.iloc[0])
        with self.assertRaises(ValueError):
            paired_loss_inference(losses.drop(index=1), model="candidate", benchmark="baseline", newey_west_lags=1)

    def test_date_labels_require_explicit_month_semantics(self):
        timestamp_factors = self.factors.copy()
        timestamp_factors.index = timestamp_factors.index.to_timestamp()
        with self.assertRaises(ValueError):
            expanding_mean_forecast(timestamp_factors, as_of=self.cutoff, min_observations=2)
        with self.assertRaises(ValueError):
            self.exposure(as_of=pd.Timestamp("2000-08-01"))
        duplicate = pd.concat([self.factors, self.factors.iloc[:1]])
        with self.assertRaises(ValueError):
            expanding_mean_forecast(duplicate, as_of=self.cutoff, min_observations=2)
        with self.assertRaises(ValueError):
            self.exposure(min_observations=3)
        with self.assertRaises(ValueError):
            self.exposure(window_months=0)


if __name__ == "__main__":
    unittest.main()
