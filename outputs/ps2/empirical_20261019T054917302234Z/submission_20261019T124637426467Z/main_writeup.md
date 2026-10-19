# Quantitative Investing — Problem Set2

## Q1 · Predicting market betas

Historical beta forecasts contain information about subsequent exposure, but one-month realized betas remain noisy. Welch's slope-winsorized estimator has lower out-of-sample (OOS) error than the OLS benchmarks on both weighting schemes. The proposed shrinkage rule does not improve on Welch (Tables 1–3; Figures A–B).

### Historical estimation and predictive calibration

Using the PS1 common-stock universe, I estimate intercept market models from daily stock excess returns and CRSP value-weighted total market excess returns, subtracting the same-date French risk-free rate. Forecasts use observations through actual month-end t; realized beta is intercept OLS over month t+1. PS1 month-start dates are observation-month labels, not information-availability dates. The historical OLS windows are one year, three years and expanding since 1960. The last is an explicitly approved approximation to the assignment's full-available-history benchmark; pre-1960 returns are unavailable here.

r<sup>e</sup><sub>i,d</sub> = α<sub>i</sub> + β<sub>i</sub> r<sup>e</sup><sub>m,d</sub> + ε<sub>i,d</sub>

Welch clips each excess stock return to the interval between −2x and 4x, where x is the contemporaneous market excess return, and estimates an intercept and slope with exponential age weights exp(−ρj). The Appendix value ρ=2/256 is primary; 2/252, stated in the paper's introduction, and valid-pair versus market-calendar aging are sensitivities (Table 3). The main specification ages market sessions. Histories require 20 valid daily pairs; Welch also requires a valid final-session return. Realized targets require at least max(10, half the month's market sessions rounded up).

β<sup>real</sup><sub>i,t+1</sub> = γ<sub>0</sub> + γ<sub>1</sub> b<sub>i,t</sub> + u<sub>i,t+1</sub>

The primary calibration is pooled OLS on matched stock-months (Table 1). OOS Welch has intercept −0.0262, slope 1.0911 and R²=0.1335; one-year OLS has slope 0.7267 and R²=0.1110. Figure B contrasts saved decile averages with the pooled fitted line and a 45-degree reference. Noisy historical regressors can attenuate predictive slopes, while noisy future-beta targets reduce explanatory power. Changing business mix, leverage and market conditions can also make old exposures stale; calibration is not a claim that true beta is constant.

### Forecast accuracy and the proposed improvement

The common sample has 3,397,913 stock-months over July 1963–December 2025. EW weights are equal within month; VW weights use positive month-end-t market capitalization. Monthly MSEs are averaged equally before taking their square root. Table 2 and Figure A show OOS VW RMSE of 0.5719 for Welch, versus 0.5841, 0.6047 and 0.6539 for one-year, three-year and expanding OLS; EW Welch RMSE is 1.3794 versus 1.4074 for one-year OLS. Larger EW errors are consistent with greater influence from volatile small stocks.

RMSE = [ T<sup>−1</sup> ∑<sub>t</sub> ∑<sub>i</sub> ω<sub>i,t</sub> (β<sup>real</sup><sub>i,t+1</sub> − b<sub>i,t</sub>)<sup>2</sup> ]<sup>1/2</sup>

I divide outcomes at July 2000, retaining the pre-existing PS1 split rather than selecting a favorable break: 444 IS months and 306 OOS months. Shrinkage b*=1+k(b<sup>Welch</sup>−1), 0≤k≤1, is motivated by measurement error and possible mean reversion in market exposure. Minimizing IS monthly VW loss selects k=1 (Table 3). Frozen OOS, the rule equals Welch and has no improvement. Its exact paired loss difference and variance are zero, so its t-statistic is undefined; the saved roundoff-scale differences are not statistical evidence. No replacement was tuned on OOS outcomes.

## Q2 · Forecasting factor and stock returns

Improving forecasts of one factor premium need not improve stock-return forecasts. In this sample, an expanding VAR(1) modestly improves OOS HML forecasts but worsens market and SMB forecasts. The resulting stock predictions have higher OOS MSE than expanding factor means, with a positive Newey–West paired-loss statistic (Tables 4–5; Figure C).

### Joint exposures and historical-average benchmarks

Joint three-factor OLS uses the preceding 36 calendar months of stock excess returns and PS1 traded Mkt−RF, HML and SMB, with an intercept, 24 complete months and full rank. Forecasts use slopes available at t, excluding alpha. Correlated size/value factors explain why joint market exposure can differ from Q1's single-factor beta.

r<sup>e</sup><sub>i,s</sub> = α<sub>i,t</sub> + b′<sub>i,t</sub> F<sub>s</sub> + ε<sub>i,s</sub> ;     forecast r<sup>e</sup><sub>i,t+1</sub> = b′<sub>i,t</sub> λ<sub>t+1|t</sub>

The first benchmark assigns every stock the expanding mean CRSP VW excess return. The second multiplies each exposure vector by expanding factor means, using observations through t only. The two factor-model forecasts share betas, samples and weights, isolating the contribution of premium forecasts.

### An alternative forecast of the three premia

F<sub>s+1</sub> = a + A F<sub>s</sub> + η<sub>s+1</sub> ;     λ<sub>t+1|t</sub> = a<sub>t</sub> + A<sub>t</sub> F<sub>t</sub>

The expanding VAR(1) uses lagged factor returns to capture persistence, reversals and cross-factor adjustment, although their signal may be weak. Its specification is fixed before OOS; coefficients update only with completed outcomes through t. This is not a valuation-spread model. Requiring 60 completed lagged training pairs with factors starting in July 1963 delays common evaluation to August 1968.

### Matched IS/OOS results and uncertainty

The matched comparison contains 2,774,383 stock-months over 689 months: 383 IS and 306 OOS. Table 4 reports factor MSE and pseudo-R² relative to each expanding mean. OOS VAR pseudo-R² is −1.073% for the market, −2.046% for SMB and +1.038% for HML. The HML improvement is modest and should not be interpreted as strong evidence of a reliable premium forecast.

Pseudo-R² = 1 − MSE<sub>model</sub> / MSE<sub>benchmark</sub>

Table 5 reports stock outcomes on identical stocks, exposure snapshots and origin-ME weights. OOS VW MSE is 0.00850759 for the market mean, 0.00851672 for factor means and 0.00858404 for VAR premia, in squared decimal monthly returns. Factor means themselves trail the market-mean benchmark slightly. VAR's pseudo-R² is −0.790% against factor means and −0.899% against the market mean. EW comparisons point in the same direction; the table also retains the IS results.

Figure C cumulates the saved OOS monthly VW loss difference, VAR minus factor means. Its positive endpoint reflects deterioration, not an investment return. The average difference is 0.0000673, with Bartlett Newey–West(12) SE 0.0000322 and t=2.089 (EW t=2.047). These are descriptive normal-reference comparisons without a nested-model forecast-test correction. Extra premium-model parameters can amplify estimation noise, and correlated premium errors interact with stock exposures. The evidence therefore does not support this alternative as an improvement in stock-return prediction; no OOS replacement model was selected.

## Q3 · Characteristic returns and measurement

### Industry-controlled monthly regressions

Does value predict returns conditional on other characteristics? The full-sample coefficient is positive, but the OOS estimate is smaller and less precise (Table 6; Figure D). Monthly regressions use month-end-t characteristics and t+1 excess returns:

r<sup>e</sup><sub>t+1</sub> = X<sub>t</sub> f<sub>t+1</sub> + u<sub>t+1</sub> ;     min<sub>f</sub> ∑<sub>i</sub> √ME<sub>i,t</sub> (r<sup>e</sup><sub>i,t+1</sub> − X<sub>i,t</sub> f)<sup>2</sup>

X includes all represented FF12 industry indicators, without a separate intercept, and standardized log ME, log BM, profitability, investment and the origin Welch market-beta forecast from Q1. Characteristics use equal-weight population standard deviations on the matched monthly sample. The objective weight is √ME, so the equivalent least-squares row multiplier is ME<sup>1/4</sup>. Market capitalization is current PERMNO ME in USD millions. Historical CRSP SIC is joined at calendar month-end and classified with the official FF12 ranges, rather than French's annually assigned industry portfolios. Missing or invalid SIC is excluded, not imputed to Other.

Annual PS1 fundamentals use prior-calendar-year statements and June formation: June-end origins can use the new formation vintage, while earlier months use the preceding June. BM retains PS1's prior-December company-ME denominator. Exact statement-release vintages are unavailable, so this is the inherited June-formation convention, not fully point-in-time accounting. The regression sample contains 2,668,791 stock-months over all 750 assignment months, with at least 849 stocks per month.

### Economic magnitude and the weaker OOS value estimate

A characteristic coefficient is a monthly return associated with one cross-sectional standard deviation of that characteristic, conditional on the other regressors. The full-sample value coefficient is 0.1527% per month, with NW(12) SE 0.0447% and t=3.416. It describes a positive conditional association for cheaper stocks, not a causal effect. Profitability is also positive and investment negative in the full sample; log size and predicted beta have weak average coefficients (Table 6).

The value result is notably weaker OOS: the coefficient is 0.0781% per month, with SE 0.0700% and t=1.116, compared with an IS coefficient of 0.2040% and t=3.625. The later period alone does not give precise evidence of a positive conditional value premium. These estimates do not constitute a formal test of a structural break. Figure D shows monthly coefficients and a trailing 36-month mean, including the current month; it does not use a centered, forward-looking smoother.

### Changing units versus changing the economic comparison

Re-expressing the five standardized characteristics as z_new=2z+3 preserves their information and fitted span. Slopes halve, while industry coefficients absorb translations because the full dummy span contains the constant. Table 7 records a maximum slope-mapping error of 2.984×10<sup>−15</sup> and fitted-return difference of 2.225×10<sup>−13</sup>; residual differences have the same magnitude since y is unchanged. These are numerical identities, not economic findings.

Omitting profitability instead changes the conditioning set. The saved no-profitability value coefficient averages 0.1453%, versus 0.1527% with full controls, on the same stocks, units and weights (Table 6). Other no-profitability coefficients are marked “Not estimated”: they were not retained in the accepted saved outputs, and no new regressions were run to fill the table. This limited comparison does not substitute full-model slopes for missing omitted-model estimates.

## Q3 · Pure value and the source of the premium

### Joint weighted residualization

I select standardized log BM as the value signal z. To isolate relative cheapness, C contains log ME, profitability, investment, predicted beta and all represented FF12 dummies. Removing these linear exposures separates value from the size, business characteristics and industry composition that often accompany it. The controls are projected jointly, using exactly the return-regression sample and WLS objective weights:

a = (C′WC)<sup>−1</sup>C′Wz ;     z<sup>⊥</sup> = z − Ca ;     C′Wz<sup>⊥</sup> = 0

W=diag(√ME). The industry span contains the constant; an alternative control set without the full industry span would require an intercept. The residual is retained in its original projection units and is not standardized again. A positive residual identifies a stock with higher log BM than the selected controls predict, rather than necessarily a high absolute BM.

The controls explain an average 31.691% of weighted cross-sectional signal variation, and 30.115% OOS (Table 7). The maximum norm-scaled weighted-orthogonality error is 8.952×10<sup>−15</sup>. This establishes negligible weighted linear exposure to the included controls, not independence from them or neutrality to omitted and nonlinear risks.

### The FWL comparison: an identity, not evidence of a premium

r<sup>e</sup><sub>t+1</sub> = Cδ + γz + u ;     r<sup>e</sup><sub>t+1</sub> = α<sup>⊥</sup>1 + γ<sup>⊥</sup>z<sup>⊥</sup> + v

The weighted Frisch–Waugh–Lovell theorem implies γ=γ<sup>⊥</sup> when the projection and both return regressions share observations and weights, C spans the constant, and residual signal variation is nonzero. Orthogonality removes the control component from the signal's normal equation; it does not create a different conditional return slope. The largest observed coefficient difference is 4.267×10<sup>−16</sup> (Table 7). Fitted returns and residuals from the two return regressions need not coincide because the second omits C.

Original value can bundle industry, size, profitability, investment and market-exposure effects. Pure value instead compares stocks whose chosen controls are similar: a positive pure signal means relatively greater cheapness after those linear comparisons. The unchanged conditional slope is true by construction; whether that slope is economically meaningful or persistent must be judged from the return estimates. In particular, the imprecise OOS value coefficient in Table 6 prevents the algebraic equality from being read as evidence of a robust later-period premium.

### Scope of the conclusions

The assignment sample is July 1963–December 2025, subject to initialization and missing inputs. Q1 and Q3 cover all 750 outcome months; Q2 begins in August 1968 after common premium-model initialization. Expanding beta starts in 1960 rather than the full CRSP history, and accounting release-date vintages are unavailable. Welch decay and missing-session aging conventions are explicitly distinguished in Table 3. The attempted Q1 and Q2 alternatives do not improve OOS performance. These limitations qualify the findings; numerical WLS identities do not remove them.

References: Welch (2022), “Simply Better Market Betas,” Critical Finance Review 11(1), 37–64, especially Appendix A; Goyal and Welch (2008), “A Comprehensive Look at the Empirical Performance of Equity Premium Prediction,” Review of Financial Studies 21(4), 1455–1508; official Ken French Data Library daily RF and FF12 SIC definitions. Specification: Quantitative Investing Problem Set 2, pp. 1–5. Code and saved-source provenance accompany the submission in the separate reproducibility document.

