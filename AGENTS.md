# PS2 Research and Coding Rules

## Mission
Complete Quantitative Investing Problem Set 2 by extending the existing, validated PS1 repository. The authoritative specification is `docs/ps2.pdf`.

## Safety
- Never modify the original PS1 folder.
- Do not delete, overwrite, or move raw data, snapshots, or existing outputs without approval.
- Do not execute WRDS queries, install or upgrade dependencies, or access external services without approval.
- Do not modify existing PS1 code unless necessary and explicitly approved.
- Do not make large changes without first presenting a plan.
- Do not invent data, empirical results, variable names, references, or test results.
- If evidence is missing, state exactly what is missing.

## Research methodology
- Read the exact assignment requirement before implementing it.
- Prevent look-ahead bias and preserve month-end information timing.
- Explicitly document return units, risk-free-rate alignment, security identifiers, market-cap definitions, and missing-data rules.
- Keep estimation and evaluation samples separate.
- Use matched stock-month observations and identical weights for model comparisons.
- Implement published methods faithfully, not approximately without disclosure.
- Distinguish mathematically guaranteed identities from empirical hypotheses.

## Testing
For every new calculation:
1. Write synthetic unit tests with known answers.
2. Check observation counts, keys, dates, and missingness.
3. Check numerical identities and units.
4. Check that all predictors use only historical information.
5. Compare results against independent benchmarks when possible.
6. Run the relevant tests and report their actual outputs.
7. Identify any unresolved warnings.

## Question-specific requirements
Q1: Verify Welch estimator details against the original paper; compare beta estimators on matched samples; use monthly weighted MSE before taking RMSE; apply Newey-West inference to monthly paired losses.

Q2: Estimate joint three-factor exposures; separate beta forecasts from factor-premium forecasts; use expanding historical averages and a genuinely out-of-sample comparison.

Q3: Use FF12 industry dummies and the prescribed characteristics; distinguish WLS objective weights from row-scaling factors; verify weighted orthogonality and Frisch-Waugh-Lovell identities.

## Reporting
After every implementation task, report:
- Files created or changed
- Methods and formulas used
- Tests actually run
- Numerical sanity checks
- Assumptions and unresolved issues
- Proposed next step

Stop at each major checkpoint for review. Do not declare an assignment question complete solely because the code executes.