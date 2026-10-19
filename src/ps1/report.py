"""Evidence-bound English report and submission bundle, generated from results."""
from __future__ import annotations
import html,json,hashlib
from pathlib import Path
import pandas as pd
from .core import ROOT,DataError,config,months,read

METHODS='''The return sample is July 1963 through December 2025 (750 monthly observations). CRSP Stock Version 2 (CIZ) total returns are used directly, including dividends, splits, and the available delisting treatment. We do not apply an additional legacy delisting-return adjustment. CRSP shares are in thousands; market equity is price times shares divided by 1,000, in USD millions. Historical US common stocks are selected using sharetype NS, securitytype EQTY, securitysubtype COM, usincflg Y, issuertype ACOR/CORP, and exchanges N/A/Q. We do not filter to securities surviving at the end of the sample. Missing returns are excluded, never filled with zero.

Question 1 uses security-level observations. Questions 2–4 consolidate eligible listed share classes by PERMCO; company returns are lag-market-equity-weighted share-class returns. Company-level market equity is the sum of observed eligible listed classes, not an estimate of unlisted share classes. Partial share-class coverage is separately recorded. Main portfolio weights use the preceding calendar month's market equity; an earlier observation separated by a calendar gap is not a valid lag.

Portfolios are formed at the end of June and held by fixed membership from July through the next June. NYSE breakpoints are independently computed for size and the relevant characteristic. Quantile ties go to the lower group. Value-weighted portfolios use beginning-of-month market equity; equal-weighted portfolios rebalance to equal weights monthly. IPOs after formation wait until the next June for sorted portfolios.

Compustat annual consolidated standard industrial-format domestic-population USD financial statements are linked through CCM LC/LU, P/C links valid on the financial-statement date, and matched to the associated June security. Multiple GVKEYs under one PERMCO (including tracking stocks) are audited and resolved using primary/confirmed link priority and the largest June eligible class; financial statements are not summed across businesses. We use the last fiscal year ending in the preceding calendar year. Book equity uses reported equity, then common equity plus preferred stock, then assets less liabilities, subtracting preferred stock in redemption/liquidation/par-value order. Missing preferred stock is treated as zero. Deferred taxes are added only for fiscal years ending before 1993. Operating profitability is revenue less COGS, SG&A, and interest, divided by book equity plus minority interest; revenue and at least one expense must be observed, and remaining missing expenses and minority interest are treated as zero. Investment uses consecutive prior-calendar-year assets. The annual information is carried only into its subsequent holding year. Restated historical data are not a complete point-in-time archive.

Arithmetic mean and volatility are annualized using 12 and sqrt(12). Sharpe ratios for long-only returns use monthly returns minus RF; zero-investment factor spreads and slope FMPs are not reduced by RF again. Maximum drawdown uses compounded long-only total-return wealth, including the initial capital peak. French data are converted from monthly percentages to decimals. The published-data download vintage is fixed in raw-file manifests.'''

def md_table(df):
    cols=list(df.columns);lines=['| '+' | '.join(cols)+' |','| '+' | '.join(['---']*len(cols))+' |']
    for row in df.itertuples(index=False,name=None):
        values=[f'{v:.6g}' if isinstance(v,float) else str(v) for v in row];lines.append('| '+' | '.join(values)+' |')
    return '\n'.join(lines)

def supplement(lines,frames,root):
    """Export already-computed monthly returns and add measured interpretations."""
    from .analysis import market_series
    from .statistics import reconcile
    out=root/'outputs'
    for dataset,filename,columns,series in [
        ('q1_market','q1_market_monthly',['month','portfolio','weighting','ret','security_count'],2),
        ('q1_size_returns','q1_size_monthly',['month','portfolio','weighting','ret','security_count','unit_count'],20),
    ]:
        data=read(dataset,root)[columns].sort_values(['month','portfolio','weighting']).reset_index(drop=True)
        groups=list(data.groupby(['portfolio','weighting']))
        if len(groups)!=series:raise DataError(f'{dataset}: unexpected series count')
        for key,g in groups:
            if not pd.DatetimeIndex(g.month).equals(months(root)) or g.ret.isna().any():
                raise DataError(f'{dataset}: incomplete monthly series {key}')
        data.to_csv(out/'tables'/f'{filename}.csv',index=False)
    index=lines.index('### Size-decile results')
    lines[index:index]=['The submission includes q1_market_monthly.csv (two series, 1,500 rows) and q1_size_monthly.csv (20 series, 15,000 rows). Each series contains 750 months. Returns are decimals (0.01 means 1%); dates label the return month, and security_count records the securities actually included in each return. These are exports of the existing calculations, not newly constructed portfolios.','']
    size=frames['q1_size_statistics'].set_index(['portfolio','weighting'])
    def size_value(p,w,c):return size.loc[(p,w),c]
    small_gap=size_value('D01','EW','mean_annual')-size_value('D01','VW','mean_annual')
    large_gap=size_value('D10','EW','mean_annual')-size_value('D10','VW','mean_annual')
    index=lines.index('### Reconciliation')
    lines[index:index]=[
        f"Within the smallest June-size decile (D01), EW and VW annualized means are {size_value('D01','EW','mean_annual'):.2%} and {size_value('D01','VW','mean_annual'):.2%}, a difference of {100*small_gap:.4f} percentage points; their annualized Sharpes are {size_value('D01','EW','sharpe_annual'):.4f} and {size_value('D01','VW','sharpe_annual'):.4f}. In D10, means are {size_value('D10','EW','mean_annual'):.2%} and {size_value('D10','VW','mean_annual'):.2%}, with an EW-minus-VW difference of {100*large_gap:.4f} percentage points. Thus the within-decile weighting effect is much more pronounced at the small end in this sample.",
        'Even inside D01, firms have unequal capitalization: EW assigns more relative weight to its smallest securities and resets those equal weights monthly, whereas VW follows beginning-of-month capitalization. These choices change both composition and rebalancing. The observed differences do not isolate a causal small-stock premium or a separate rebalancing return; that would require further decomposition. The cumulative EW-minus-VW figure sums monthly return differences and is not a compounded strategy wealth series.','']
    p=read('security_month',root);reference=read('crsp_index',root).set_index('month');diagnostics=[]
    broader=(p.exchange.isin(['N','A','Q'])&p.share_type.eq('NS')&p.security_type.eq('EQTY')
             &p.security_subtype.eq('COM')&p.issuer_type.isin(['ACOR','CORP']))
    baseline=read('q1_market',root)
    for variant,market in [('assignment_US_baseline',baseline),('include_non_US_incorporated',market_series(p.assign(eligible=broader),root))]:
        for w,col in [('EW','ewretd'),('VW','vwretd')]:
            diagnostics.append({'variant':variant,'weighting':w,**reconcile(market[market.weighting.eq(w)].set_index('month').ret,reference[col])})
    diagnostic=pd.DataFrame(diagnostics);diagnostic.to_csv(out/'tables/q1_universe_sensitivity.csv',index=False)
    comparisons=diagnostic.set_index(['variant','weighting'])
    def universe_metric(variant,weighting,column):return comparisons.loc[(variant,weighting),column]
    index=lines.index('![Market wealth](figures/q1_market_wealth.png)')
    lines[index:index]=['### Quantitative universe diagnostic','',md_table(diagnostic),'',
        (f'This one-at-a-time experiment relaxes only the US-incorporation restriction while retaining the ordinary-common-stock, issuer-type, and exchange rules. '
         f"VW correlation with CRSP changes from {universe_metric('assignment_US_baseline','VW','correlation'):.6f} to {universe_metric('include_non_US_incorporated','VW','correlation'):.6f}, and annualized tracking error from {universe_metric('assignment_US_baseline','VW','tracking_error_annual'):.4%} to {universe_metric('include_non_US_incorporated','VW','tracking_error_annual'):.4%}; "
         f"EW correlation changes from {universe_metric('assignment_US_baseline','EW','correlation'):.6f} to {universe_metric('include_non_US_incorporated','EW','correlation'):.6f}, and tracking error from {universe_metric('assignment_US_baseline','EW','tracking_error_annual'):.4%} to {universe_metric('include_non_US_incorporated','EW','tracking_error_annual'):.4%}. "
         'The incorporation filter therefore accounts for part of the discrepancy, especially for VW, but substantial residual differences remain. This diagnostic does not change the assignment-compliant US baseline. Missing returns, beginning-capital coverage, other index eligibility rules, and historical listing changes remain candidate explanations, not measured attributions.'),'']
    stats=frames['q3_statistics'].set_index(['characteristic','variant','window'])
    def sr(char,var,win):return stats.loc[(char,var,win),'sharpe_annual']
    index=lines.index('## Question 4 — Sorts versus Fama–MacBeth')
    lines[index:index]=['### What the out-of-sample results imply','',
        f"For value, replacing B/M with E/P raises out-of-sample Sharpe from {sr('ep','Q2_full_baseline','out_of_sample'):.4f} to {sr('ep','modified','out_of_sample'):.4f}; on the matched sample, the baseline is {sr('ep','matched_baseline','out_of_sample'):.4f}. However, in-sample modified Sharpe is {sr('ep','modified','in_sample'):.4f}, below the original {sr('ep','Q2_full_baseline','in_sample'):.4f}. The results support better risk-adjusted performance in the chosen later window, not uniform dominance across time. Earnings may capture productive economic value that historical book equity misses, but the reversal across windows also suggests sensitivity to the economic regime, earnings cyclicality, or sector composition. These mechanisms have not been separately tested.",
        f"For profitability, GP/assets raises in-sample Sharpe from {sr('gp','Q2_full_baseline','in_sample'):.4f} to {sr('gp','modified','in_sample'):.4f}, but reduces out-of-sample Sharpe from {sr('gp','Q2_full_baseline','out_of_sample'):.4f} to {sr('gp','modified','out_of_sample'):.4f}. The matched-sample original has the same out-of-sample Sharpe as the full baseline, so this loss is not explained by the measured coverage difference. The hypothesis that a simpler gross-profit measure and an assets denominator improve risk-adjusted performance fails in this evaluation window. Removing SG&A and interest may discard useful expense information, while the assets denominator may introduce industry and capital-intensity exposures. These are plausible explanations for future tests, not established causes.",
        'No significance test for the difference in Sharpe ratios was performed, so neither a positive difference nor a negative one establishes statistical significance. The unsuccessful profitability modification is retained rather than selecting another signal after observing the test window. Historical restatements and the use of a retrospective data snapshot also limit the interpretation as a fully investable point-in-time backtest.','']
    q4=frames['q4_statistics'].set_index(['characteristic','standardization','weighting'])
    paragraphs=['### Comparing all three regression characteristics','']
    for char,label in [('log_size','Log size'),('log_bm','Log book-to-market'),('op','Operating profitability')]:
        cells=[]
        for standard,w in [('raw','OLS'),('raw','WLS'),('zscore','OLS'),('zscore','WLS')]:
            row=q4.loc[(char,standard,w)]
            cells.append(f"{standard} {w}: mean monthly coefficient {row.mean_monthly:.4%}, ordinary t {row.t_iid:.4f}, annualized Sharpe {row.sharpe_annual:.4f}")
        paragraphs.extend([label+' — '+'; '.join(cells)+'.',''])
        if char=='log_size':
            paragraphs.extend(['The log-size FMP has positive exposure to larger size and zero exposure to the other regressors. Its negative mean therefore describes a conditional larger-minus-smaller return direction, opposite to the small-minus-big convention of SMB. Reversing this FMP changes the signs of its mean, t, and Sharpe; it does not make it identical to SMB, which uses coarse sorting and different samples and exposures. The smaller negative coefficient and weaker t under market-cap WLS are consistent with less influence from small firms, but do not establish the source of the size premium.',''])
        elif char=='log_bm':
            paragraphs.extend(['The sharp fall in the raw B/M mean and t under WLS is consistent with the conditional value association being stronger when small companies receive equal influence. It is not causal evidence. Within each weighting scheme, raw and z-scored B/M have similar t and Sharpe here, although their coefficient units differ: raw coefficients price a one-unit log-B/M exposure, while standardized coefficients price a one-cross-sectional-standard-deviation exposure.',''])
        else:
            paragraphs.extend(['Market-cap WLS increases the raw OP mean coefficient and ordinary t relative to OLS, while monthly z-scoring lowers OP Sharpe and t in both weighting schemes. A monthly standardized slope equals the raw slope times that month\'s characteristic standard deviation; this time-varying scaling changes the relative contribution of months to the coefficient series. Consequently, comparing raw and z-scored coefficient magnitudes alone is not an economic improvement test.',''])
    paragraphs.extend(['All four regressions use the same monthly company sample, so their differences do not arise from sample selection between specifications. Their slopes are returns to unit-characteristic-exposure portfolios, not returns normalized to an identical gross investment. A constant positive rescaling would not change Sharpe; different or time-varying portfolio exposures and controls may matter. The comparison with the full Q2 RMW additionally involves different eligibility samples. Establishing how much of that gap is due specifically to B/M and size controls would require a matched-sample RMW and nested regressions; that attribution is not established here.',''])
    index=lines.index('## Reproducibility and limitations');lines[index:index]=paragraphs
    resolutions=pd.read_csv(out/'tables/financial_link_resolutions.csv')
    groups=resolutions.groupby(['permco','formation_year']).ngroups
    company=read('company_month',root)
    partial=company.ret.notna()&company.lag_me.gt(0)&company.return_cap_coverage.lt(.999999)
    n=int(partial.sum());minimum=company.loc[partial,'return_cap_coverage'].min()
    lines.extend(['','### Specific unresolved construction limitations','',
        f'{groups} company/formation-year groups have multiple linked GVKEYs ({len(resolutions)} candidate rows). Selecting a primary/confirmed link and then the largest June class can associate one business\'s financial statements with the whole PERMCO capitalization. Alternative mapping-rule sensitivity has not been performed.',
        f'{n} company-month observations have a finite company return and positive lagged company equity while covering less than all of that beginning equity; the lowest coverage is {minimum:.2%}. Available share-class returns are renormalized within the company, but portfolio VW weights use the full company lagged equity. This implicitly uses the observed classes to represent the missing-class return. Coverage is recorded, but the effect of excluding or differently weighting these observations has not been measured.',
        'The CCM join explicitly checks link validity on the financial-statement date and matches the linked security to June, but does not separately require link validity on the June formation date. This is a disclosed alignment choice, not a demonstration that all historical associations are unambiguous. A June-date validity sensitivity has not been performed.',''])

def package(root=ROOT):
    """Write the two private course deliverables with reproducible data snapshots."""
    import zipfile, shutil
    root=Path(root);out=root/'outputs';submission=root/'submission';submission.mkdir(exist_ok=True)
    files=[]
    for folder in ['src/ps1','sql','config','tests','scripts']:
        files.extend(p for p in sorted((root/folder).rglob('*')) if p.is_file() and '__pycache__' not in str(p) and not p.name.endswith('.pyc'))
    files.extend(root/name for name in ['README.md','decision_log.md','pyproject.toml','requirements.lock','data/README.md'])
    for kind in ['crsp_monthly','crsp_names','crsp_index','compustat_annual','ccm_link']:
        files.extend(p for p in sorted((root/'data/raw'/kind).glob('*')) if p.is_file() and p.suffix in {'.parquet','.json'})
    files.extend(p for p in sorted((root/'data/raw/french').glob('*')) if p.is_file() and p.suffix in {'.zip','.json'})
    files.extend(p for p in sorted((out/'tables').glob('*.csv')) if p.stem not in {
        'google_share_classes','google_company_returns','partial_share_class_returns',
        'ambiguous_financial_links','financial_link_resolutions'})
    files.extend(sorted((out/'figures').glob('*.png')))
    files.extend(out/name for name in ['ps1_report.md','ps1_report.pdf','q2_diagnosis.md','README.md','RESULTS_GUIDE.md'])
    validation=out/'validation.json'
    if validation.exists():
        v=json.loads(validation.read_text());v['submission_files']=len(files)+1
        v['source_checksums']={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in v.get('source_checksums',{})}
        v['report_pdf_sha256']=hashlib.sha256((out/'ps1_report.pdf').read_bytes()).hexdigest()
        validation.write_text(json.dumps(v,indent=2)+'\n')
        files.append(validation)
    missing=[str(p) for p in files if not p.is_file()]
    if missing:raise DataError(f'Submission package missing files: {missing}')
    shutil.copy2(out/'ps1_report.pdf',submission/'PS1_Answers.pdf')
    with zipfile.ZipFile(submission/'PS1_Code.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p,Path('PS1_Code')/p.relative_to(root))

def build(root=ROOT):
    root=Path(root);out=root/'outputs';out.mkdir(parents=True,exist_ok=True)
    required=['q1_market_statistics','q1_size_statistics','q1_reconciliation','q2_factor_statistics','q2_reconciliation','q2_sensitivity','q2_bm25_reconciliation','q3_statistics','q3_sharpe_differences','q4_statistics','q4_profitability_comparison']
    missing=[n for n in required if not (out/'tables'/f'{n}.csv').exists()]
    if missing:raise DataError('Cannot generate final report; missing empirical tables: '+', '.join(missing))
    frames={n:pd.read_csv(out/'tables'/f'{n}.csv') for n in required}
    for n in ['q1_market_statistics','q1_size_statistics']:
        frames[n]=frames[n].drop(columns=['mean_monthly','vol_monthly','t_iid','t_hac12','average_unit_count'],errors='ignore')
    frames['q3_statistics']=frames['q3_statistics'][['characteristic','variant','window','months','mean_annual','vol_annual','sharpe_annual']]
    frames['q4_statistics']=frames['q4_statistics'].drop(columns=['t_sharpe_identity_error','skewness'],errors='ignore')
    for n in ['q2_factor_statistics','q3_statistics','q4_statistics']:
        frames[n]=frames[n].drop(columns=['max_drawdown'],errors='ignore')
    if len(months(root))!=750:raise DataError('Production report requires the complete 750-month assignment window')
    q1=frames['q1_market_statistics'].set_index('weighting');gap=q1.loc['EW','mean_annual']-q1.loc['VW','mean_annual']
    q2=frames['q2_reconciliation'];lowest=q2.loc[q2.correlation.idxmin()]
    q3=frames['q3_sharpe_differences'];split=config(root)['methodology']['q3_split']
    lines=['# Problem Set 1 — Quantitative Investing','', 'Empirical results generated from WRDS and Ken French snapshots.','', '## Database and methodology','',METHODS,'','## Question 1 — Value- and equal-weighted benchmarks','',md_table(frames['q1_market_statistics']),'',f'The EW minus VW annualized arithmetic mean difference is {gap:.2%}. Equal weighting gives each security one position, increasing the influence of small securities and companies with multiple listed classes. Value weighting concentrates the portfolio in larger companies. This is a composition and rebalancing difference, not evidence that either weighting scheme must outperform in every period.','', '### Size-decile results','',md_table(frames['q1_size_statistics']),'','### Reconciliation','',md_table(frames['q1_reconciliation']),'','The universe excludes non-common securities and non-US-incorporated issuers; the CRSP benchmark can include a broader eligible index universe. Differences must therefore be assessed alongside missing-return and start-cap coverage, historical listing changes, and security-versus-company size assignments. We do not infer that every gap is caused by one of these choices.','', '![Market wealth](figures/q1_market_wealth.png)','', '![Size EW–VW differences](figures/q1_size_ew_vw_gap.png)','', '## Question 2 — Fama–French factors','', '### Multiple share classes: Google/Alphabet','', 'Each eligible listed class has its own market equity and return in Q1. In Q1 EW, each class occupies a separate equal-weight position; in Q1 VW, its weight is its own beginning market equity. For Q2, company equity is the sum of eligible observed classes and the company return is the beginning-market-equity-weighted average of their returns. This avoids duplicating one company’s financial statement at the formation breakpoint. It does not impute privately held class equity. The worked example below shows the observed classes and their aggregation in this report.','', '### Factor results','',md_table(frames['q2_factor_statistics']),'',md_table(q2),'',f'The lowest-correlation factor is {lowest.factor}, with correlation {lowest.correlation:.6f}. The six underlying portfolios, annual characteristic coverage, and one-at-a-time variants provide diagnostics. The table below measures sensitivity to representative-class returns and requiring all three expenses; these checks do not establish the exact proprietary construction of the published series.','',md_table(frames['q2_sensitivity']),'','![Factor gaps](figures/q2_factor_gaps.png)','', '### 5×5 sorts and collateralized long-short wealth','', 'Independent NYSE size and B/M quintile breakpoints form 25 value-weighted portfolios. For each size quintile, the monthly capital return is RF plus high-B/M minus low-B/M. Initial capital is $1 at the end of June 1963, with cash, long, and short weights reset to 1, 1, and −1 after each month. Wealth compounds the full capital return. Trading costs, stock-borrow fees, and financing frictions are not included.','', '![Long-short wealth](figures/q2_long_short_wealth.png)','',md_table(frames['q2_bm25_reconciliation']),'', '## Question 3 — Improving value and profitability','',f'The preselected split is {split}: July 1963–June 2000 is in sample, and July 2000–December 2025 is out of sample. This aligns the split with annual portfolio formation and reserves 306 months for evaluation. The split and hypotheses were fixed before inspecting strategy results.','', 'Value is modified from B/M to income before extraordinary items divided by previous-December market equity. The hypothesis is that earnings measure productive economic value that book equity may miss; earnings cyclicality and accounting noise may defeat the hypothesis. Profitability is modified to gross profits (revenue minus COGS) divided by assets. This reduces sensitivity to equity financing and the treatment of some expenses, but can introduce industry and capital-intensity differences. Negative earnings are retained; missing earnings are not set to zero.','', 'Size breakpoints, NYSE 30/70 sorting convention, holding period, and value weighting remain fixed. Full Q2 baseline, matched-sample original, and matched-sample modified results are all reported so a change in financial-data coverage is not mistaken for a better characteristic.','',md_table(frames['q3_statistics']),'',md_table(q3),'']
    for _,r in q3[q3.window.eq('out_of_sample')].iterrows():
        conclusion='improves' if r.modified_minus_matched_sharpe>0 else 'does not improve'
        lines.append(f'For {r.characteristic}, the modified strategy {conclusion} the matched-sample out-of-sample Sharpe; the difference is {r.modified_minus_matched_sharpe:.4f}. This is an out-of-sample performance comparison, not a statistical claim of significance. Compare it with the full-baseline difference ({r.modified_minus_Q2_sharpe:.4f}) to identify the role of sample coverage.\n')
    lines+=['## Question 4 — Sorts versus Fama–MacBeth','', 'Each month we regress company returns on an intercept, log beginning market equity, log the available annual B/M, and annual OP. OLS and market-cap WLS each run with raw and equal-weight z-scored characteristics on the same monthly sample. The regressions are cross-sectional, not pooled. Slope coefficients are zero-net-investment FMP returns with unit exposure to the target characteristic and zero exposure to the other regressors. Their implicit gross exposure is not constrained to the gross exposure of a sorted factor.','',md_table(frames['q4_statistics']),'', 'For the ordinary time-series standard error of the monthly coefficients, t = mean / (sd/sqrt(T)) = annualized Sharpe × sqrt(T/12). The identity is numerically checked. Newey–West 12-lag t values need not satisfy it. Monthly z-scoring rescales coefficients by time-varying cross-sectional standard deviations, so Sharpe and t values can change, rather than merely the coefficient units. Market-cap WLS gives more influence to large companies and less influence to small companies and their extreme characteristics.','',md_table(frames['q4_profitability_comparison']),'','The OP FMP controls simultaneously for continuous log size and log B/M. The 2×3 RMW sort uses coarse size controls and does not remove continuous B/M exposure. These exposure differences, weighting differences, monthly scaling, and unconstrained FMP gross exposure help interpret performance gaps; the numerical results alone do not prove which explanation dominates.','', '## Reproducibility and limitations','', 'The private course ZIP contains the full Python/SQL pipeline, pinned dependencies, tests, aggregate result tables, chart inputs, and fixed WRDS and French raw snapshots. The one-command runner installs the listed Python packages, checks the data snapshots, and rebuilds the security and company panels, all four questions, and this report without a WRDS login. A Python 3.11–3.13 installation and access to a Python package index are required. The extraction code records query/source, timestamp, row count, and SHA-256. Full-sample coverage, key uniqueness, calendar lags, complete sorted cells, and regression exposure identities are checked.','', 'Sources: [Ken French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html), [five-factor construction](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_5_factors_2x3.html), [variable definitions](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/variable_definitions.html), [WRDS CIZ webinar](https://wrds-www.wharton.upenn.edu/documents/2084/Webinar.pdf).','', 'WRDS acknowledgment required by its terms: Wharton Research Data Services (WRDS) was used in preparing Quantitative Investing Problem Set 1. This service and the data available thereon constitute valuable intellectual property and trade secrets of WRDS and/or its third-party suppliers.','', '## AI assistance','', 'OpenAI Codex was used to help implement and debug the Python/SQL workflow, check data quality and numerical outputs, and draft and edit this report. The reported empirical values come from the stated WRDS and Ken French data sources, not from generated examples.']
    google_path=out/'tables/google_share_classes.csv'
    if google_path.exists():
        google=pd.read_csv(google_path);example=google[google.month.eq('2014-06-01')].copy()
        if len(example)>1:
            cap=example.me.sum();startcap=example.lag_me.sum();ret=(example.lag_me*example.ret).sum()/startcap
            market=read('q1_market',root);ew_n=int(market[market.month.eq('2014-06-01')&market.weighting.eq('EW')].security_count.iloc[0])
            index=lines.index('### Factor results')
            lines[index:index]=['### Worked Google example: June 2014','',md_table(example),'',f'The two observed classes have combined June market equity of ${cap:,.3f} million (${cap/1000:,.3f} billion). Their May market-equity-weighted June company return is {ret:.6%}. The company calculation weights each June class return by its May capitalization divided by ${startcap:,.3f} million. Q1 EW has {ew_n:,} eligible securities that month, giving each Google class 1/{ew_n:,} and the company together 2/{ew_n:,}. Q1 VW assigns each class its own beginning capitalization share, whose sum equals the company capitalization share.','']
    diagnosis=out/'q2_diagnosis.md'
    if diagnosis.exists():
        index=lines.index('### 5×5 sorts and collateralized long-short wealth')
        lines[index:index]=['### Measured lowest-correlation diagnosis','',diagnosis.read_text().split('\n',2)[-1],'',md_table(pd.read_csv(out/'tables/q2_lowest_factor_gap_decomposition.csv')),'','The following table separates the factor comparison into three periods.','',md_table(pd.read_csv(out/'tables/q2_lowest_factor_periods.csv')),'']
    q4=frames['q4_statistics'].set_index(['characteristic','standardization','weighting'])
    q4_explanation=(f"For raw log B/M, OLS has annualized Sharpe {q4.loc[('log_bm','raw','OLS'),'sharpe_annual']:.4f} and ordinary t {q4.loc[('log_bm','raw','OLS'),'t_iid']:.4f}, compared with WLS Sharpe {q4.loc[('log_bm','raw','WLS'),'sharpe_annual']:.4f} and t {q4.loc[('log_bm','raw','WLS'),'t_iid']:.4f}. The reduction when large companies receive more weight is consistent with a stronger conditional value premium among smaller companies, though it does not establish causality. For profitability under OLS, raw OP Sharpe is {q4.loc[('op','raw','OLS'),'sharpe_annual']:.4f}, versus {q4.loc[('op','zscore','OLS'),'sharpe_annual']:.4f} after monthly standardization. The scale is time varying, so z-scoring gives different relative importance to months with different OP dispersion; the saved extreme-OP and condition-number diagnostics help identify that mechanism.")
    insert=lines.index('## Reproducibility and limitations');lines[insert:insert]=[q4_explanation,'']
    supplement(lines,frames,root)
    text = '\n'.join(lines)
    (out / 'ps1_report.md').write_text(text, encoding='utf-8')
    # A self-contained printable HTML report: tables retain precision, figures are embedded.
    import base64,re
    def inline(t):
        t=html.escape(t)
        t=re.sub(r'\*\*(.*?)\*\*',r'<strong>\1</strong>',t)
        t=re.sub(r'`([^`]+)`',r'<code>\1</code>',t)
        t=re.sub(r'\[([^]]+)\]\((https://[^)]+)\)',r'<a href="\2">\1</a>',t)
        return t
    pieces=[]; table_rows=[]
    def flush_table():
        if table_rows:
            header=table_rows[0];body=table_rows[2:]
            pieces.append('<div class="table"><table><thead><tr>'+''.join('<th>'+inline(x)+'</th>' for x in header)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+inline(x)+'</td>' for x in row)+'</tr>' for row in body)+'</tbody></table></div>')
            table_rows.clear()
    for line in text.splitlines():
        if line.startswith('|'):
            table_rows.append([x.strip() for x in line.strip('|').split('|')]);continue
        flush_table()
        image=re.fullmatch(r'!\[([^]]+)\]\((figures/[^)]+)\)',line)
        if image:
            path=out/image.group(2);encoded=base64.b64encode(path.read_bytes()).decode()
            pieces.append(f'<figure><img alt="{html.escape(image.group(1))}" src="data:image/png;base64,{encoded}"><figcaption>{html.escape(image.group(1))}</figcaption></figure>')
        elif line.startswith('#'):
            level=len(line)-len(line.lstrip('#'));pieces.append(f'<h{level}>'+inline(line[level:].strip())+f'</h{level}>')
        elif line.strip():pieces.append('<p>'+inline(line)+'</p>')
    flush_table()
    style='body{max-width:1100px;margin:40px auto;font:15px/1.55 system-ui;padding:0 24px;color:#17212b}h1,h2,h3{color:#143852}h2{border-bottom:1px solid #cad4dc;padding-bottom:8px;margin-top:36px}table{border-collapse:collapse;width:100%;font-size:11px;font-variant-numeric:tabular-nums}th,td{padding:7px;border-bottom:1px solid #ddd;text-align:right}th:first-child,td:first-child{text-align:left}th{background:#edf3f7}.table{overflow:auto;margin:18px 0}img{max-width:100%}figcaption{text-align:center;color:#566}code{font-size:.9em}a{color:#176c9b}@media print{body{font-size:10px;margin:0;padding:0}table{font-size:8px}h2{break-after:avoid}tr,figure{break-inside:avoid}.table{overflow:visible}a{color:inherit}}'
    (out/'ps1_report.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Quant Investing PS1</title><style>'+style+'</style><body>'+''.join(pieces)+'</body></html>')
    (out/'RESULTS_GUIDE.md').write_text('# Reading the PS1 results\n\nReturns in the CSV files are decimals: 0.01 means 1%. Read the English PDF first; its tables and figures answer all four questions. The CSV files in the code ZIP are aggregate portfolio returns and diagnostics, not WRDS security-level exports.\n\n- Q1: compare market and size-decile EW/VW statistics, then inspect the CRSP/French reconciliation and small-decile discussion.\n- Q2: compare the five factors, the lowest-correlation diagnosis, the Google share-class example, and the five collateralized 5-by-5 wealth paths.\n- Q3: use the matched-sample baseline to isolate the characteristic change from sample coverage.\n- Q4: compare the 12 monthly FMP series under OLS/WLS and raw/z-scored specifications; ordinary t follows the Sharpe identity, while HAC t need not.\n')
    manifests=[]
    for p in sorted((root/'data/raw').rglob('*.json')):
        if p.name in ['mapping_candidates.json']:continue
        manifests.append({'file':str(p.relative_to(root)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    (out/'run_manifest.json').write_text(json.dumps({'sample_months':750,'config_sha256':hashlib.sha256((root/'config/project.toml').read_bytes()).hexdigest(),'field_map_sha256':hashlib.sha256((root/'config/field_map.toml').read_bytes()).hexdigest(),'raw_manifests':manifests},indent=2)+'\n')
    import subprocess, sys, importlib.util, os
    pdf_python=sys.executable
    if importlib.util.find_spec('reportlab') is None:
        pdf_python=os.environ.get('PS1_PDF_PYTHON','')
        if not pdf_python: raise DataError('PDF rendering requires ReportLab; install the project dependencies or set PS1_PDF_PYTHON.')
    subprocess.run([pdf_python,str(root/'scripts/render_report_pdf.py')],check=True)
    validation=out/'validation.json'
    if validation.exists():
        v=json.loads(validation.read_text());v['pdf_visual_qa']='Pending visual review of regenerated PDF'
        validation.write_text(json.dumps(v,indent=2)+'\n')
    package(root)
    print('Report and submission package generated:',out/'ps1_report.html')
