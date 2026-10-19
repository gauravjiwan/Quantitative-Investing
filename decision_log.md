# PS1 methodology decision log

Locked on 2026-09-27 before inspecting Q3 portfolio results. The sample and Q3 hypotheses were authorized in the implementation plan. All accounting, share-class and inference limitations are retained in the final report.

| Decision | Chosen rule | Reason / alternative | Questions |
|---|---|---|---|
| CIZ tables | CRSP `msf_v2`, `stksecurityinfohist`, `wrds_monthlyindexret_query`; Compustat `funda`; CCM `ccmxpf_linktable` | Verified in authenticated account metadata; do not use legacy SIZ `msf` | All |
| Common stocks | NS / EQTY / COM / US-incorporated Y / ACOR or CORP / exchanges N,A,Q | WRDS CIZ webinar common-stock mapping, historical rows; no current-survivor filter | All |
| Historical trading status | Do not require current or historical active flag for return inclusion | Preserve valid terminal/delisting-month returns; valid numeric return and historical stock classification required | Q1–Q3 |
| Raw window | CRSP Dec 1962–Dec 2025; Compustat calendar fiscal-end years 1961–2024 | Dec 1962 B/M denominator and two asset years are required for first formation | All |
| Return treatment | Use CIZ MthRet once; no extra dividend/split/delisting adjustment | CIZ incorporates distributions; missing returns excluded, not zeroed | All |
| Market equity | Same-date raw price × raw thousands of shares / 1000, USD millions | Apple and 1962 pilot reconcile typical price × shares to CIZ cap; flag rounding/corporate-action gaps | All |
| Split adjustment | Price / cumulative price factor; shares × cumulative share factor | Preserve comparable price/share series; ME remains same-date raw product | All |
| Lag | Exact previous calendar month | Never shift across missing months | All |
| Multiple classes | Q1 securities; Q2–Q4 PERMCO companies; eligible listed classes only | Q1 EW counts each class; company fundamentals used once; no private class imputation | All |
| Company return | Lag-cap weighted available class returns; record coverage fraction | Renormalize valid class weights; representative-class variant measured separately | Q2–Q4 |
| Company exchange | Exchange of representative eligible class: largest prior-month cap, fallback current cap | Stable deterministic assignment; mixed-exchange firms use this disclosed rule | Q2–Q4 |
| CCM | LC/LU and P/C links valid on statement date, then match associated security to June | Prefer P then C; LC then LU; class size breaks within-company duplicates; conflicting GVKEYs preserved in audit and resolved by primary/confirmed priority then largest June class; no financial summation | Q2–Q4 |
| Accounting format | INDL / STD / D / C / USD, last fiscal-end date in prior calendar year | Ignore fiscal-year label when aligning; avoid currency mismatch | Q2–Q4 |
| BE | SEQ; fallback CEQ+PSTK; fallback AT−LT; minus preferred redemption/liquidation/par value; add TXDITC only before 1993 | Current French changes; no FASB106 adjustment; missing preferred stock and deferred tax zero | Q2–Q4 |
| OP missing expenses | SALE observed and >=1 of COGS/XSGA/XINT observed; remaining expenses zero; MIB missing zero | French eligibility; strict-expense sensitivity provided | Q2–Q4 |
| Annual timing | June forms July–June holding year; previous calendar fiscal-end year financials | No later statement backfill; restated historical data are not full point-in-time archive | Q2–Q4 |
| Size breakpoints | NYSE June median/quintiles/deciles; same size points across 2x3 characteristic sorts | Avoid changing size construction when characteristic coverage changes | Q1–Q3 |
| Characteristic breakpoints | Independent NYSE 30/70 (2x3) and 20/40/60/80 (5x5); equality enters lower group | Not conditional quintiles inside size groups | Q2–Q3 |
| Holding/weights | Annual membership; monthly EW reset or month-start ME VW | IPOs wait for annual sorted formation; market benchmark updates monthly | Q1–Q3 |
| RF | French monthly FF5 RF, percent converted to decimal | Long-only Sharpe uses excess returns; factor spreads/FMP do not subtract RF again | All |
| Collateralized 5x5 strategy | RF + high B/M − low B/M, weights 1,1,−1, monthly capital compounding | Initial capital $1 at June 1963 end; stop if capital exhausted | Q2 |
| Q3 hypotheses | EP = IB / prior-December ME; GP = (SALE−COGS)/AT | Earnings versus book equity; gross profitability/assets versus equity-denominator OP | Q3 |
| Q3 split | July 2000; IS 444 months / OOS 306 months | Aligned with annual formation and fixed before looking at results | Q3 |
| Q3 fairness | Full Q2 baseline plus matched original/modified company sample; unchanged size points | Separate missing-data sample effect from signal change; negative earnings retained | Q3 |
| Regression features | Log month-start ME, log available June BM, available June OP, intercept | Monthly cross-section, no pooled regression | Q4 |
| Regression standardization | Equal-weight monthly mean and population SD for both OLS and WLS | Isolate weighting from standardization; same company sample in four specifications | Q4 |
| Outliers | No winsorization in main result; max OP, matrix condition and gross FMP exposure reported | Avoid quietly changing specified characteristic | Q4 |
| Inference | Ordinary FM t plus 12-lag Newey–West; annual SR uses sqrt(12) | Ordinary t/SR identity numerically verified; HAC differs | Q4 |
| Submission | English report and code/results package; licensed raw data remain local | Add team names; use actual Canvas format; no automatic course submission | All |

## Live-data resolution

102 PERMCO/formation-year groups had multiple distinct linked GVKEYs (228 candidate rows). These include tracking stocks/business entities, so financial statements cannot be blindly summed. After the uniqueness gate exposed this, the production rule selects P before C, LC before LU, then the largest June eligible class. All alternatives and the selected flag are saved in financial_link_resolutions.csv. This is a disclosed company-accounting approximation; the report must not claim PERMCO always represents identical consolidated financials.
