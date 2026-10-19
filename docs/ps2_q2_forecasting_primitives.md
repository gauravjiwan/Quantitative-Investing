# Q2 forecasting primitives: implementation checkpoint

The exact assignment requirements are in `docs/ps2.pdf`, printed pages 3--4.
This implementation provides isolated synthetic-tested functions; it does not
claim that the empirical question is complete or select a successful model.

`src/ps2/factor_forecasts.py` implements:

- Joint monthly OLS exposures to traded `Mkt-RF`, `HML`, and `SMB`, with a
  mandatory explicit window, minimum history, and intercept choice. With an
  intercept, coefficients solve `min ||y - alpha - F beta||^2`. An intercept
  can absorb mean residual returns in estimation but is excluded from the
  assignment forecast `beta' lambda`. Joint market loadings can differ from
  Q1 single-factor betas because correlated omitted HML/SMB exposures enter
  the single-factor market slope.
- Expanding arithmetic means of factors, and a separate expanding mean of
  monthly CRSP value-weighted excess returns. The latter is a constant-across-
  stocks benchmark, not an own-stock average. RF subtraction must be done
  upstream in the same monthly units. Daily arithmetic averages are not
  substituted for expected monthly returns.
- A configurable alternative premium forecast: expanding predictive OLS
  `F[s+1] = a + B Z[s] + error`, with outcome months no later than `t` when
  forecasting `t+1`. This is machinery for an economically motivated candidate
  such as a point-in-time valuation spread, not an empirically tuned selection.
  The feature definitions and their release timing remain caller choices.
- Stock predictions using one immutable exposure snapshot for all premium
  methods. No alpha, RF addition, missing-value fill or alternative exposure
  estimator is inserted to improve a comparison.
- Common stock-month matching and monthly MSE with either equal weights or
  explicitly supplied positive weights. Weights are normalized in each month;
  monthly MSEs are then averaged equally over evaluation months, rather than
  pooling observations and overweighting months with more stocks. IS/OOS
  pseudo-R2 is `1 - MSE_model/MSE_benchmark` on identical observations. A zero
  benchmark MSE yields undefined pseudo-R2 with an explicit status.
- Paired monthly loss-difference uncertainty with Bartlett Newey--West
  standard errors, an explicit bandwidth and no finite-sample correction.
  The implementation requires complete contiguous monthly losses, so a lag
  cannot accidentally bridge a calendar gap. Report IS and OOS separately.
  This descriptive HAC comparison is not a special nested-model adjustment.

Month labels use a monthly `PeriodIndex`, with an explicit `as_of` month.
The forecast origin is the **end** of that month. PS1 month-start timestamps
must first be understood as observation-month labels; they do not establish
availability on the first day of that month. Predictive features must already
respect their release dates. These functions cannot infer or repair data
vintages and release lags. Calendar matching is exact `s + 1`, never the next
available row when an intervening month is absent.

Returns are decimals (`0.01 = 1%`); no annualization occurs. Security keys are
passed through without changing PERMNO to company identifiers or aggregating
share classes. Missing, infinite, unmatched or unusable histories are counted.
Joint factor means use common complete factor months; joint regressions use
common complete dependent-variable/factor rows. Insufficient history and rank
deficiency preserve missing forecasts with explicit statuses. Evaluation uses
the common sample across every supplied forecast, retaining excluded counts
and completely unmatched months. Missing weights are excluded and counted;
finite nonpositive weights and duplicate/null keys are errors.

Decisions still needed before empirical execution:

1. Exposure frequency and window, minimum usable history and intercept policy.
   This engine implements monthly joint regressions; daily joint regressions
   would require a separate explicit frequency and aggregation decision.
2. Traded factor source (PS1 versus official French), CRSP benchmark source and
   matched monthly RF construction. French `Mkt-RF` does not replace the CRSP
   baseline automatically.
3. Security/share-class universe, return flags and beginning-of-period market
   capitalization definition for value-weighted evaluations.
4. Initial estimation history, preselected IS/OOS split, minimum training
   history, predictive features, release lags and in-sample tuning rules.
5. Newey--West bandwidth and whether additional nested-model uncertainty
   analysis is desired. The current function never chooses bandwidth from OOS
   performance.

The offline test suite covers known joint slopes/intercepts, independent NumPy
least-squares and statsmodels HAC benchmarks, joint-versus-univariate market
loadings, exact calendar gaps, future perturbations, common-sample missingness,
singular designs, fixed beta snapshots, exclusion of alpha from forecasts,
weighted/equal-weight monthly loss identities, explicit split timing, zero-MSE
benchmarks and rejection of timestamp labels as information dates. No WRDS
queries, downloads, installations or empirical panel computations are needed.
