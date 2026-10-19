"""Q3 synthetic calculations only; no authentication or empirical data."""
import unittest

import numpy as np
import pandas as pd
import statsmodels.api as sm

from ps2.residualization import (
    CHARACTERISTICS, q3_controls, q3_design, q3_fwl, q3_objective_weights,
    residualize, wls,
)


class ResidualizationTests(unittest.TestCase):
    def setUp(self):
        self.index = pd.Index(range(12), name="permno")
        self.s = lambda x: pd.Series(x, index=self.index, dtype=float)
        self.x = self.s([-2, -1, 0, 1, 2, 3, -3, 4, .5, 2.5, -1.5, 1.5])
        self.weights = self.s([1, 4, 2, 5, 3, 7, 2, 8, 1, 3, 6, 2])
        self.controls = pd.DataFrame({"constant": 1., "x": self.x})
        self.z = self.s([1, -1, 3, 2, 0, 8, 2, 5, -2, 6, -3, 4])
        self.y = .003 + .002*self.x + .004*self.z

    def test_objective_weights_are_sqrt_me_and_row_scales_fourth_root(self):
        me = self.s(np.arange(1, 13)**4)
        weights = q3_objective_weights(me)
        np.testing.assert_allclose(weights, np.arange(1, 13)**2)
        np.testing.assert_allclose(np.sqrt(weights), np.arange(1, 13))

    def test_known_coefficients_and_weighted_normal_equations(self):
        design = self.controls.assign(z=self.z)
        result = wls(self.y, design, self.weights)
        np.testing.assert_allclose(result.coefficients, [.003, .002, .004], atol=1e-15)
        np.testing.assert_allclose(result.residuals, 0, atol=1e-15)
        np.testing.assert_allclose(result.weighted_normal_equations, 0, atol=1e-14)
        self.assertEqual(result.n_observations, 12)
        self.assertEqual(result.rank, 3)

    def test_independent_statsmodels_and_explicit_objective(self):
        noisy = self.y + self.s([.01, 0, -.01, .02, 0, -.03, 0, .01, .03, 0, -.01, .02])
        design = self.controls.assign(z=self.z)
        fit = wls(noisy, design, self.weights)
        benchmark = sm.WLS(noisy, design, weights=self.weights).fit()
        np.testing.assert_allclose(fit.coefficients, benchmark.params, atol=1e-14)
        self.assertAlmostEqual(fit.objective, (self.weights*fit.residuals**2).sum())
        # Passing sqrt(w) to WLS would solve a different objective.
        wrong = sm.WLS(noisy, design, weights=np.sqrt(self.weights)).fit()
        self.assertGreater(np.max(np.abs(fit.coefficients - wrong.params)), 1e-4)

    def test_weighted_intercept_only_projection_known_answer(self):
        weights = self.s([1]*11 + [3])
        z = self.s([0]*11 + [14])
        controls = pd.DataFrame({"intercept": 1.}, index=self.index)
        result = residualize(z, controls, weights)
        self.assertAlmostEqual(result.fit.coefficients.iloc[0], 3.)
        self.assertAlmostEqual(result.weighted_r_squared, 0.)
        self.assertAlmostEqual(float(weights @ result.fit.residuals), 0.)
        # Mean is weighted, not ordinary mean.
        self.assertGreater(abs(result.fit.residuals.mean()), .1)

    def test_projection_orthogonality_and_explained_weighted_variation(self):
        result = residualize(self.z, self.controls, self.weights)
        np.testing.assert_allclose(self.controls.T @ (self.weights*result.fit.residuals), 0, atol=1e-12)
        expected = sm.WLS(self.z, self.controls, weights=self.weights).fit()
        self.assertAlmostEqual(result.weighted_r_squared, expected.rsquared)
        self.assertTrue(0 <= result.weighted_r_squared <= 1)

    def test_fwl_known_slope_and_independent_partial_both_sides(self):
        result = q3_fwl(self.y, self.z, self.controls, self.weights)
        self.assertAlmostEqual(result.full.coefficients["__signal__"], .004)
        self.assertAlmostEqual(result.pure.coefficients["__signal__"], .004)
        self.assertAlmostEqual(result.slope_difference, 0., places=14)
        partial_y = residualize(self.y, self.controls, self.weights).fit.residuals
        partial_z = result.projection.fit.residuals
        partial_slope = (self.weights*partial_z*partial_y).sum() / (self.weights*partial_z**2).sum()
        self.assertAlmostEqual(partial_slope, .004)
        # Slope equality does not imply return fitted-value equality.
        self.assertGreater(np.max(abs(result.full.fitted-result.pure.fitted)), .001)

    def test_full_industry_dummy_span_and_no_separate_intercept(self):
        industries = pd.DataFrame({"industry_1": [1]*6+[0]*6,
                                   "industry_2": [0]*6+[1]*6}, index=self.index)
        controls = industries.assign(x=self.x)
        chosen = q3_controls(controls, controls.columns, self.weights)
        self.assertEqual(list(chosen), list(controls))
        y = .01*industries.industry_1 + .03*industries.industry_2 + .002*self.x + .004*self.z
        result = q3_fwl(y, self.z, chosen, self.weights)
        self.assertAlmostEqual(result.slope_difference, 0, places=14)
        np.testing.assert_allclose(chosen.T @ (self.weights*result.projection.fit.residuals), 0, atol=1e-12)

    def test_changing_weights_or_residual_units_breaks_the_prescribed_identity(self):
        noisy = self.y + self.s([.01, 0, -.01, .02, 0, -.03, 0, .01, .03, 0, -.01, .02])
        correct = q3_fwl(noisy, self.z, self.controls, self.weights)
        pure_design = pd.DataFrame({"intercept": 1., "z": correct.projection.fit.residuals})
        wrong = wls(noisy, pure_design, self.s(np.ones(12)))
        self.assertGreater(abs(wrong.coefficients.z-correct.full.coefficients["__signal__"]), 1e-5)
        pure_design.z = 2*pure_design.z
        scaled = wls(noisy, pure_design, self.weights)
        self.assertAlmostEqual(scaled.coefficients.z, correct.full.coefficients["__signal__"] / 2)

    def test_controls_add_intercept_for_partial_or_no_industries(self):
        design = self.controls.assign(industry_1=[1]*6+[0]*6)
        for names in [[], ["x"], ["industry_1", "x"]]:
            chosen = q3_controls(design, names, self.weights)
            self.assertIn("__intercept__", chosen)
            result = q3_fwl(self.y, self.z, chosen, self.weights)
            self.assertAlmostEqual(result.slope_difference, 0, places=14)

    def test_intercept_span_and_rank_failures_explicit(self):
        with self.assertRaisesRegex(ValueError, "constant|intercept"):
            residualize(self.z, self.controls[["x"]], self.weights)
        duplicate_constant = self.controls.assign(other_constant=1.)
        with self.assertRaisesRegex(ValueError, "rank-deficient"):
            wls(self.y, duplicate_constant, self.weights)
        with self.assertRaisesRegex(ValueError, "rank-deficient"):
            q3_fwl(self.y, self.x, self.controls, self.weights)
        with self.assertRaisesRegex(ValueError, "unique"):
            q3_controls(self.controls, ["x", "x"], self.weights)

    def test_affine_reexpression_preserves_fit_and_changes_coefficient_units(self):
        original = wls(self.y, self.controls.assign(z=self.z), self.weights)
        changed = wls(self.y, self.controls.assign(z=7+2*self.z), self.weights)
        np.testing.assert_allclose(original.fitted, changed.fitted, atol=1e-14)
        np.testing.assert_allclose(original.residuals, changed.residuals, atol=1e-14)
        self.assertAlmostEqual(changed.coefficients.z, original.coefficients.z / 2)
        self.assertAlmostEqual(changed.coefficients.constant, original.coefficients.constant-7*original.coefficients.z/2)

    def test_identical_keys_order_no_hidden_dropping(self):
        cases = [self.z.iloc[::-1], self.z.iloc[:-1], self.z.set_axis([0]*12)]
        for bad in cases:
            with self.subTest(index=list(bad.index)):
                with self.assertRaises(ValueError):
                    q3_fwl(self.y, bad, self.controls, self.weights)
        for name in ["y", "z", "w", "c"]:
            y, z, w, c = self.y.copy(), self.z.copy(), self.weights.copy(), self.controls.copy()
            if name == "c":
                c.iloc[0, 1] = np.nan
            else:
                {"y": y, "z": z, "w": w}[name].iloc[0] = np.nan
            with self.assertRaisesRegex(ValueError, "missing|nonfinite"):
                q3_fwl(y, z, c, w)

    def test_invalid_weights_and_nonfinite_values_rejected(self):
        for value in [0, -1, np.inf, np.nan]:
            w = self.weights.copy()
            w.iloc[0] = value
            with self.assertRaises(ValueError):
                wls(self.y, self.controls, w)
            with self.assertRaises(ValueError):
                q3_objective_weights(w)
        bad = self.y.copy()
        bad.iloc[0] = np.inf
        with self.assertRaises(ValueError):
            wls(bad, self.controls, self.weights)
        with self.assertRaises(ValueError):
            wls(self.y, pd.DataFrame(index=self.index), self.weights)

    def test_constant_signal_has_undefined_centered_r_squared(self):
        result = residualize(self.s(np.ones(12)), self.controls, self.weights)
        self.assertEqual(result.weighted_signal_variation, 0)
        self.assertTrue(np.isnan(result.weighted_r_squared))

    def test_common_weight_rescaling_and_input_preservation(self):
        old = [x.copy(deep=True) for x in [self.y, self.z, self.controls, self.weights]]
        first = q3_fwl(self.y, self.z, self.controls, self.weights)
        second = q3_fwl(self.y, self.z, self.controls, self.weights*100)
        np.testing.assert_allclose(first.full.coefficients, second.full.coefficients, atol=1e-14)
        self.assertAlmostEqual(second.full.objective, 100*first.full.objective, places=20)
        for previous, current in zip(old, [self.y, self.z, self.controls, self.weights]):
            if isinstance(current, pd.DataFrame):
                pd.testing.assert_frame_equal(previous, current)
            else:
                pd.testing.assert_series_equal(previous, current)

    def test_design_prescribed_characteristics_normalization_and_missing_industries(self):
        for method in ["equal", "objective_weighted"]:
            design = q3_design(self.weights**2, np.exp(self.x), self.z,
                               self.x**2, self.z**2, self.s([1]*6+[12]*6), standardization=method)
            self.assertEqual(list(design.matrix), ["ff12_01", "ff12_12", *CHARACTERISTICS])
            self.assertEqual(design.unrepresented_industries, tuple(range(2, 12)))
            self.assertNotIn("intercept", design.matrix)
            a = np.ones(12) if method == "equal" else self.weights.to_numpy()
            a = a/a.sum()
            standardized = design.matrix[list(CHARACTERISTICS)]
            np.testing.assert_allclose(standardized.mul(a, axis=0).sum(), 0, atol=1e-14)
            np.testing.assert_allclose(standardized.pow(2).mul(a, axis=0).sum(), 1, atol=1e-14)
            np.testing.assert_allclose(standardized*design.scales+design.centers,
                                       np.column_stack([np.log(self.weights**2), self.x, self.z, self.x**2, self.z**2]), atol=1e-14)

    def test_design_rejects_unknown_standardization_invalid_sic_logs_and_constants(self):
        args = [self.weights**2, np.exp(self.x), self.z, self.x**2, self.z**2, self.s([1]*12)]
        with self.assertRaises(TypeError):
            q3_design(*args)
        with self.assertRaises(ValueError):
            q3_design(*args, standardization="unverified")
        for position, value in [(0, 0), (1, -1), (5, 13), (5, 1.5), (5, np.nan)]:
            bad = [x.copy() for x in args]
            bad[position].iloc[0] = value
            with self.assertRaises(ValueError):
                q3_design(*bad, standardization="equal")
        for constant in [1., .1]:
            args[2] = self.s([constant]*12)
            with self.assertRaisesRegex(ValueError, "dispersion"):
                q3_design(*args, standardization="equal")


if __name__ == "__main__":
    unittest.main()
