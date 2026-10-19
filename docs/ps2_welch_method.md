# Welch beta kernel: verified evidence and explicit research policies

## Empirical-stage resolution (2026-10-19)

The following text records the earlier kernel audit. Production empirical results
now exist in `outputs/ps2/empirical_20261019T054917302234Z`. The user approved
the explicitly labeled expanding-since-1960 benchmark, without pre-1960 data.
The main reported policy is Appendix exponential rho=2/256 with calendar-session
aging; rho=2/252 and valid-pair aging are computed sensitivities on a common
sample. Minimum historical pairs are 20; the current session is required for
Welch. The realized monthly target requires max(10,ceil(half the market sessions)),
with higher-history/target-count sensitivities. These are disclosed analysis
policies, not claims that the paper uniquely specifies missing-session aging or
the assignment uniquely specifies realized-target eligibility. The original
audit's future-tense statements below remain as a record of the earlier stage.

The assignment's Q1 (pages 1–3, especially page 2 and footnotes 1–4) requires
daily excess returns, CRSP value-weighted total market returns, same-day French RF,
an age-weighted slope-winsorized benchmark and next-month realized OLS targets.
Predictors stop at actual month-end information cutoffs; PS1 month-start labels
must first be interpreted as observation-month labels.

## Original-source verification

[Welch (2022), original journal PDF](https://cfr.ivo-welch.info/published/papers/welch2022simply.pdf)
was read directly from the journal on 2026-10-19 UTC without installing a PDF
reader. The URL redirected to the journal's `.org/forthcoming/papers/` host; the
retrieved PDF has the published page numbers 37–64. Search-index excerpts were
checked against the actual PDF content, including its Appendix.

| Page | Verified convention |
|---|---|
| 38 | Clip each stock return between the smaller and larger of −2 times and +4 times the contemporaneous market return. |
| 48 | Both series are excess returns using the same RF. General eligibility requires at least 20 stock-return days and a valid return on the final trading day. Later tables impose different thresholds. |
| 46–48 | BSWA uses age decay and all available stock history rather than a fixed rolling block. |
| 63, Appendix A | Fit an intercept and market slope to clipped returns using WLS objective weights `exp(-rho*j)`, where chronological rows have `j=n,...,1`; Appendix BSWA sets `rho=2/256`, BSW sets zero. |
| 39 versus 47 and 63 | The introduction says `2/252`, while the later discussion and executable Appendix use `2/256`. The discussion's reciprocal-power approximation also differs slightly from the Appendix exponential formula. |

## Isolated implementation

New files are `src/ps2/welch.py`, `tests/test_ps2_welch.py` and this document.
Existing OLS functions and all raw data remain unchanged. No empirical betas
have been produced. The source discrepancy is exposed rather than silently
selected: every weight, kernel and historical-adapter call requires explicit
`rho`. `APPENDIX_RHO` merely names the verified reference value.

The kernel computes weighted means, then

`beta = sum(w*(x-xbar)*(clipped_y-ybar)) / sum(w*(x-xbar)^2)`

and `alpha = ybar - beta*xbar`. These `w` are objective weights; an independent
least-squares verification scales design rows and responses by `sqrt(w)`.
Clipping changes the dependent observations, not the fitted slope directly.
In particular, a nonzero fitted intercept is permitted, and a fitted slope is
not post-clipped to a prespecified interval. Zero market returns imply a
zero clipped response under the stated algebra.

The array kernel rejects missing/nonfinite input pairs. Its two-pair mathematical
minimum is not a research eligibility rule. The dated adapter counts unusable
returns, removes incomplete pairs without filling, retains all supplied history,
sorts daily keys and ignores inputs after `as_of`. A supplied trading calendar
identifies the final session before a weekend month-end. Duplicate, null,
timezone-aware or intraday keys and observation dates absent from that calendar
are rejected. Insufficient history, absent current return and constant market
returns produce explicit statuses and NaN coefficients.

## Decisions still required before production estimation

1. Select the decay version, explicitly acknowledging the original paper's
   internal inconsistency. Appendix replication means `rho=2/256` with
   exponential weights, not a hard-coded 90-day half-life or reciprocal power.
2. Select `age_basis`: `valid_pairs` ages complete regression rows;
   `market_calendar` ages all supplied trading sessions across missing rows.
   Both coincide on complete data. The Appendix orders supplied rows but does
   not settle how preprocessing of missing sessions should change elapsed age.
3. Choose a common minimum history for all compared methods and the realized
   next-month target. The adapter requires explicit `min_observations` and
   `require_current_return`; requesting 20 and True reproduces the stated
   general eligibility rule, without assuming every later table uses it.
4. Approve CRSP flag/duration eligibility separately. No flags are interpreted
   here. Full-history initialisation remains incomplete until separately
   authorized pre-1960 acquisition; the adapter cannot reconstruct absent data.

The synthetic tests verify clipping signs and endpoints, exact weights, known
slopes/intercepts, independent WLS, OLS compatibility, missing-date aging,
future poisoning, current-session eligibility and invalid-key rejection.
They establish numerical correctness of these functions, not Q1 empirical
predictive superiority or assignment completion.
