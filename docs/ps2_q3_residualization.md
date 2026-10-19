Q3 foundations implemented in `src/ps2/residualization.py` follow assignment
pages 4--5, including footnotes 9--11. These are isolated one-month functions,
not an empirical Q3 result or a completed assignment answer.

The prescribed design contains standardized log market capitalization, log
book-to-market, profitability, investment and predicted Q1 market beta, together
with all represented FF12 industry indicators and no separate intercept.
Unrepresented FF12 categories are reported explicitly; their all-zero columns
carry no information and do not have separately identified coefficients.
Historical CRSP SIC must be mapped at each actual month-end, rather than using
French's annually assigned published industry portfolios (p. 4, footnote 9).
No SIC extraction or historical SIC join is implemented here.

Footnote 10 specifies the WLS objective as sum_i sqrt(ME_i,t) u_i,t+1^2.
Accordingly `q3_objective_weights` returns sqrt(ME); the least-squares row
multiplier is its square root, ME^(1/4). A common positive weight rescaling is
allowed numerically because it preserves the minimizer. `wls` uses the SVD
least-squares solver on the scaled rows, not inverse normal equations, and
reports coefficients, fitted values, residuals, weighted normal equations,
objective, rank, condition number and observation count. Rank deficiency raises.

For controls C and signal z, the joint projection is
a = argmin sum_i w_i (z_i - C_i a)^2, z_perp = z - C a.
It preserves original signal units and checks the constant lies in C's span.
The helper `q3_controls` adds an intercept when selected controls do not already
span one; a full set of represented industry dummies already spans it. Redundant
controls, including an intercept plus all industry dummies, raise rather than
silently choosing an unidentified coefficient vector.

`residualize` reports C' W z_perp and weighted centered R-squared:
1 - sum(w z_perp^2) / sum(w (z - weighted_mean(z))^2).
The R-squared is undefined (NaN) for a constant signal. Positive z_perp means a
signal above the controls' fitted value; it need not imply a positive future
return. Orthogonality concerns weighted linear exposure to the selected controls,
not every nonlinear risk or an economic causal effect.

`q3_fwl` fits both [C,z] and [1,z_perp] to the same future excess returns using
the exact same ordered stock keys and positive objective weights as the signal
projection. It checks the slope identity with absolute tolerance 1e-10 and
relative tolerance 1e-8. The equality follows from WLS Frisch--Waugh--Lovell and
the constant in C's span, conditional on an identified residual signal. It is
not evidence that the signal predicts returns. The fitted returns and return
residuals of these two regressions generally differ because only the first
contains the controls. Footnote 11 forbids restandardizing z_perp; this module
does not do so. An invertible affine change to a characteristic preserves
fitted values and residuals when the constant is spanned, and changes coefficient
units; omitting an economic control changes the comparison instead.

Every input must already be a matched cross section with unique, nonnull stock
keys. Missing/nonfinite values, reordered indices, unmatched keys, nonpositive
market capitalization or objective weights, nonpositive book-to-market before
logging, and missing/invalid FF12 codes raise. No observations are silently
dropped or reordered. The caller must explicitly choose and document the
intersection of usable outcomes, signal, controls, and weights before projection.
Return inputs are decimal next-month excess returns. Predictors, classifications
and ME must be available at actual month-end t. PS1 month-start labels identify
an observation month and never certify information availability. Timing joins
are outside these isolated functions and remain to be tested in integration.

Open research choices: equal-weight or objective-weighted monthly characteristic
standardization (the API requires an explicit choice; both use population
dispersion), the Q1 beta forecast selected for the design, the purification
signal and controls, and policy for unavailable historical SIC/accounting inputs.
Profitability and investment are supplied from validated PS1 definitions rather
than reinvented. Unit changes, such as one standard deviation versus one raw
log-BM unit, must be reported alongside average characteristic coefficients.
No PS1 files, raw data, or empirical outputs are changed by this implementation.

Validation actually run: `.\.venv\Scripts\python.exe -B -m unittest discover
-s tests -p test_ps2_residualization.py -v` passed 17 tests. Synthetic known-answer
checks recover WLS coefficients (0.003, 0.002, 0.004), projection weighted mean
3, and full/pure slope 0.004; an independent statsmodels WLS fit agrees. Tests
also cover weighted orthogonality, full/partial industry and intercept spans,
affine coefficient-unit changes, different-weight failures of the identity,
invalid or unmatched inputs, rank deficiency and constant characteristics.
