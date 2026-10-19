# Empirical checkpoint ready for review

Authoritative results are in `outputs/ps2/empirical_20261019T054917302234Z`.
The self-contained report is four pages; individual CSVs and PNGs contain the
assignment tables and figures. Actual computed products, sample exclusions,
test logs, source hashes and restart files are retained.

|Question|Matched stock-months|Evaluation months|Computed conclusion|
|---|---:|---:|---|
|Q1|3,397,913|750|Welch OOS VW RMSE0.571855 vs one-year OLS0.584072; IS shrinkage selects k=1, no improvement.|
|Q2|2,774,383|689|VAR OOS VW stock pseudo-R2 -0.7904% vs factor means; NW t2.08884 for VAR-minus-mean loss.|
|Q3|2,668,791|750|Average value slope0.00152658 per SD/month, NW t3.41624; OOS slope0.000781384, t1.11613.|

SIC:128,895 intervals; no overlap/multiple match;17,248 candidate origins without
an interval and84,793 with invalid nonnull SIC. These are retained in SIC products
and explicitly excluded from matched Q3 regressions.

Weighted FWL maximum slope error4.27e-16; scaled orthogonality error8.95e-15;
average control-projection weighted R2=31.69%. These are conditional identities
and cross-sectional variation statistics, not evidence that the signal earns a
premium. All145 synthetic tests passed.

No new daily WRDS extraction was performed. The bounded approved SIC acquisition
was the only new WRDS acquisition. Final verification rehashed all4,181 accepted
daily Parquets, totaling102,076,552 stock-plus-index rows, without changing them.
PS1 security-month SHA still equals its recorded pre-processing fingerprint.

Remaining limits are disclosed: expanding starts1960 by user approval; Q2 uses
July1963 onward PS1 factors and initializes untilAugust1968; accounting uses
PS1 June formation with prior-calendar-year statements, without release-vintage
data; Welch rho and missing-session age ambiguity are covered by sensitivities.
The attempted alternatives did not improve the requested OOS objectives.

No further broad acquisition, model selection using OOS outcomes, or automatic
submission is planned. This is a review checkpoint, not a claim that economic
performance follows from passing tests.
