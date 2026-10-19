"""Verify accepted local artifacts and render a four-page empirical writeup."""
import argparse,json,time,html
from pathlib import Path
import numpy as np,pandas as pd
import ps2_extract_daily as io
from ps2_empirical import connection


def verify(out,beta_root,sic):
    started=time.perf_counter();records={}
    for q in ('q1','q2','q3'):
        rec=json.loads((out/q/'manifest.json').read_text());records[q]=rec
        products=rec.get('products',[{'file':rec.get('product'),'sha256':rec.get('product_sha256')}])
        for product in products:
            if io.sha256(io.ROOT/product['file'])!=product['sha256']:raise ValueError(q+' product checksum mismatch')
    inputs=json.loads((beta_root/'completion.json').read_text())['inputs']
    if io.sha256(io.ROOT/'data/processed/security_month.parquet')!=inputs['security_month']:raise ValueError('PS1 security input changed')
    accepted_files=accepted_rows=0
    for year in range(1960,2026):
        for kind in ('stock','index'):
            folder,spec=io.selected_jobs(kind,year=year,executing=True)[0]
            if io.sha256(folder/'manifest.json')!=inputs[f'{kind}_{year}_manifest']:raise ValueError('Accepted daily manifest changed')
            rec=io.verify_complete(folder,spec)
            if rec is None:raise ValueError('Missing accepted daily partition')
            accepted_files+=len(rec['files']);accepted_rows+=rec['validation']['rows']
    if io.sha256(sic)!=records['q3']['sic_source_sha256']:raise ValueError('SIC checksum mismatch')
    checks={}
    with connection(out) as c:
        for q in ('q1','q2','q3'):
            rec=records[q];p=(rec['products'][0]['file'] if q=='q1' else rec['product'])
            c.read_parquet(str(io.ROOT/p)).create_view(q)
            origin='origin_month'
            rows,unique,nulls=c.execute(f'''SELECT count(*),count(DISTINCT (permno,{origin})),
              count(*) FILTER(WHERE permno IS NULL OR {origin} IS NULL OR target_month IS NULL OR me IS NULL OR me<=0) FROM {q}''').fetchone()
            future=c.execute(f'SELECT count(*) FROM {q} WHERE target_month<>{origin}+INTERVAL 1 MONTH').fetchone()[0]
            if rows!=unique or nulls or future or rows!=rec['matched_stock_months']:raise ValueError(q+' final key/count/timing check failed')
            checks[q]={'rows':rows,'duplicate_keys':rows-unique,'invalid_keys_or_ME':nulls,'wrong_forecast_horizon':future}
    result={'accepted_daily_files_checksum_verified':accepted_files,'accepted_daily_rows':accepted_rows,
        'PS1_security_input_unchanged':True,'empirical_checks':checks,'elapsed_seconds':time.perf_counter()-started}
    io.dump_new(out/'final_validation.json',result)
    return records,result


def build(out,beta_root,sic):
    if (out/'report.pdf').exists():raise ValueError('Report already exists; refusing overwrite')
    records,checks=verify(out,beta_root,sic)
    q1,q2,q3=[records[k] for k in ('q1','q2','q3')]
    tests=json.loads((out/'tests.json').read_text())
    if not tests['success']:raise ValueError('Synthetic suite not passing')
    read=lambda q,name:pd.read_csv(out/q/(name+'.csv'))
    rmse=read('q1','rmse');cal=read('q1','pooled_calibration');stock=read('q2','stock_metrics');factor=read('q2','factor_metrics')
    nw=read('q2','paired_losses_NW');coeff=read('q3','mean_coefficients_NW');omit=read('q3','omitted_profitability')
    def beta(model,period='OOS',weight='VW'):
        return rmse[(rmse.model==model)&(rmse.period==period)&(rmse.weighting==weight)].iloc[0]
    def srow(model):return stock[(stock.model==model)&(stock.period=='OOS')&(stock.weighting=='VW')].iloc[0]
    value=coeff[(coeff.period=='ALL')&(coeff.characteristic=='log_bm')].iloc[0]
    welch_cal=cal[(cal.period=='OOS')&(cal.model=='welch_256_cal')].iloc[0]
    stock_nw=nw[(nw.scope=='stocks')&(nw.period=='OOS')&(nw.weighting=='VW')&(nw.model=='factor_VAR')].iloc[0]
    pages=[]
    pages.append(('Data, timing, and predicting market betas (Q1, assignment pp. 1-3)',[
      'This analysis uses the validated PS1 security returns, eligibility, market capitalization, annual characteristics and traded factors, adding accepted CRSP CIZ daily returns and daily value-weighted total market returns. Outcomes run July 1963-December 2025 where initialization permits. PERMNO identifies stocks; company fundamentals are linked by contemporaneous PERMCO. ME is in USD millions. All returns are decimals: the preserved French daily source is divided by 100. Daily stock and market excess returns subtract exactly the same date-matched RF; monthly analyses use the PS1 monthly French RF, without substituting compounded rounded daily RF.',
      'PS1 month-start dates label observation months. Forecast information stops at actual calendar month-end t; returns and realized betas belong to t+1, and value weights use ME at t. IS ends June 2000 and OOS begins July 2000, reusing the existing PS1 split before OOS model evaluation. This leaves 444 IS and 306 OOS assignment months, including several market regimes.',
      'Historical betas are intercept OLS over trailing calendar one-year and three-year windows, plus an explicitly approved expanding-since-1960 benchmark. It is not a full-1926-history beta. The daily adapter retains usable NA missing-return flags and one-trading-period D1-D4/DU durations; other flags stay in raw data but do not enter daily beta estimation. Histories require 20 valid pairs, and Welch requires a valid final-session return. Realized next-month intercept OLS requires at least max(10, ceil(half of market sessions)); 15/20-day and 60/126 historical-count sensitivities are tabulated.',
      'Welch clips excess stock returns to [min(-2x,4x), max(-2x,4x)] for excess market return x, then fits an intercept and slope by age-weighted least squares. The original paper introduction says rho=2/252; its later discussion and executable Appendix use 2/256. We use exponential objective weights exp(-rho*j), Appendix rho=2/256, and report 2/252 plus valid-pair versus market-calendar aging. Calendar aging is the labeled main missing-session policy; the Appendix does not resolve that preprocessing choice.',
      f"The common comparison contains {q1['matched_stock_months']:,} stock-months and {q1['evaluation_months']} months. Pooled predictive regression is primary. OOS Welch calibration has intercept {welch_cal.intercept:.4f}, slope {welch_cal.slope:.4f}, and R-squared {welch_cal.r_squared:.4f}. Its VW RMSE is {beta('welch_256_cal').RMSE:.4f}, versus {beta('ols_1y').RMSE:.4f}, {beta('ols_3y').RMSE:.4f}, and {beta('ols_expanding_1960').RMSE:.4f} for one-year, three-year, and expanding OLS. Its EW RMSE is {beta('welch_256_cal',weight='EW').RMSE:.4f}. We normalize weights within month, average monthly squared losses equally, then take a square root. Short realized windows make targets noisy; EW gives volatile small stocks more influence. Clipping reduces outlier influence, while older full-history data can become stale.",
      f"The alternative was shrinkage toward market exposure one: 1+k*(Welch-1). A constrained IS VW loss minimization, with grid diagnostics, selected k={q1['shrinkage_k_fitted_IS_VW_only']:.3f}. Frozen OOS it equals Welch, producing zero paired loss difference and zero estimated SE; its t-statistic is undefined. There is no empirical improvement to claim. We did not retune after seeing OOS. The economic motivation is exposure mean reversion and measurement error, but stronger shrinkage toward one was not supported by the IS objective. All tested approaches, sensitivity rows, calibration estimates and monthly losses are supplied."]))
    pages.append(('Forecasting factor premia and stock returns (Q2, pp. 3-4)',[
      'Three-factor exposures are estimated jointly, not by combining three univariate slopes. We use trailing 36 calendar months of stock excess returns and the PS1 traded Mkt-RF, HML and SMB factors, fitting an intercept with at least 24 complete months and a full-rank design. Exposure forecasts use these slopes at t; estimated alpha is excluded from next-month return forecasts. Single-factor market beta can differ because correlated omitted size/value factors affect the univariate slope.',
      'The first return forecast is the expanding historical mean CRSP VW excess return, identical across stocks. The factor-mean forecast is beta-prime times the three expanding historical factor means. The alternative is an expanding VAR(1): each factor outcome at s+1 is jointly regressed on a constant and the three realized factors at s. Its specification is fixed before OOS; rolling-origin coefficients update only with completed outcomes through t. Lagged returns may capture premium persistence, reversals and cross-factor adjustment, but also mostly noise. There is no claimed valuation-spread model or use of unobserved economic predictors.',
      f"At least 60 factor observations/completed lagged training pairs initialize the expanding forecasts. The identical three-model comparison therefore begins August 1968 and ends December 2025: {q2['evaluation_months']} months, {q2['matched_stock_months']:,} stock-months, 383 IS and 306 OOS months. July 1963-July 1968 is initialization rather than evaluated performance. The same exposure snapshot, realized returns, origin ME and stocks are used across premium methods. Exposure histories may have missing months; no future eligibility is used when joining target returns.",
      f"OOS VW monthly stock MSE is {srow('CRSP_mean').MSE:.8f} for the CRSP mean, {srow('factor_mean').MSE:.8f} for factor means and {srow('factor_VAR').MSE:.8f} for VAR premia. Relative to factor means, VAR stock pseudo-R-squared is {srow('factor_VAR').R2_vs_factor_mean:.3%}; relative to CRSP it is {srow('factor_VAR').R2_vs_CRSP:.3%}. Factor means themselves have pseudo-R-squared {srow('factor_mean').R2_vs_CRSP:.3%} against CRSP. EW results and all IS metrics are tabulated separately.",
      'OOS factor VAR pseudo-R-squared versus expanding means is '+', '.join(f"{r.factor}: {r.pseudo_R2:.3%}" for r in factor[(factor.period=='OOS')&(factor.model=='VAR')].itertuples())+'. Thus any improvement in one premium does not ensure better stock forecasts: the joint exposure vector and covariance of forecast errors determine the resulting stock-return error.',
      f"The OOS monthly VW paired stock loss difference, VAR minus factor means, is {stock_nw.mean_loss_difference:.8f}, with Bartlett Newey-West(12) SE {stock_nw.standard_error:.8f} and t={stock_nw.t_statistic:.3f}. Positive differences mean deterioration. These are descriptive normal-reference statistics, not a nested-model forecast-test correction. Factor-level uncertainty is also supplied. Weak expected-return signals, volatile realized returns, estimated exposures and extra VAR coefficients make forecasting difficult. The alternative did not deliver the desired stock-return improvement. No OOS result was used to select a replacement model.",
      'The IS results are rolling-origin forecasts using only contemporaneously available training outcomes, rather than a regression fitted to the entire IS period and mislabeled as a forecast. Stocks are evaluated on decimal excess returns. Monthly EW/VW MSEs are averaged equally over evaluation months, and pseudo-R-squared is one minus the matched MSE ratio.']))
    pages.append(('Characteristics, industries, and pure value (Q3, pp. 4-5)',[
      'A bounded, sequential historical SIC extraction used only the 26,299 PERMNOs and their own month-end date intervals needed for Q3. It produced 128,895 intervals, no duplicate interval keys, no overlaps and no multiple stock-month matches. SIC is joined at actual calendar month-end, not the monthly label or last observed trading date. Official French FF12 inclusive ranges are applied historically. Valid unmatched SICs become residual Other; missing or invalid SICs are excluded, never imputed. Of 3,459,176 candidate origins, 17,248 have no interval and 84,793 have invalid nonnull SIC.',
      'Predictors are current PERMNO log ME, PS1 annual log BM, operating profitability and investment, and origin Welch 2/256 calendar-age beta. Each is centered and scaled by equal-weight cross-sectional population SD on the common monthly regression sample. The latest formation year is y-(month<6), so June-end origins use the new June formation; earlier months use the prior June. PS1 BM uses prior-December company ME and prior-calendar-year book equity. Annual accounting characteristics are held until the next formation. Fiscal dates are checked to precede the formation year. Actual statement-release vintages are unavailable; this is the inherited conservative June-formation convention, not a claim of complete point-in-time accounting.',
      f"The full regression has all represented FF12 indicators, no additional intercept, and the five characteristics. Objective weights are sqrt(ME), so row multipliers are ME^(1/4). The matched sample has {q3['matched_stock_months']:,} stock-months over {q3['evaluation_months']} months, with at least {q3['min_monthly_stocks']:,} stocks per month. Missing fundamental, beta, industry and outcome counts are reported separately; these marginal exclusion counts overlap.",
      f"The average full-model value coefficient is {value['mean']:.6f} per month (decimal excess return for one cross-sectional SD of log BM), with Newey-West(12) SE {value.standard_error:.6f}, t={value.t_statistic:.3f}. It measures the conditional return association of cheaper stocks holding the selected industries and characteristics fixed; it is not a causal effect. Removing profitability changes that economic comparison: the mean value coefficient without OP is {omit.omit_OP_value_slope.mean():.6f}, versus {omit.full_value_slope.mean():.6f} with OP on exactly the same rows.",
      f"We re-express all five standardized characteristics as 2*z+3. Their slopes halve and industry coefficients absorb the translations. Maximum characteristic-coefficient mapping error is {q3['max_affine_coefficient_error']:.3g}; maximum fitted-return difference is {q3['max_affine_fit_error']:.3g}. Residuals consequently agree to the same numerical tolerance. This changes units while preserving information and fitted spans; omitting OP generally changes fitted returns and slopes.",
      f"The selected signal is standardized log BM. Controls are the four other characteristics and the full represented industry dummy span. Joint WLS projection explains an average {q3['projection_R2_mean']:.2%} of weighted signal variation. The residual is not standardized again. Maximum norm-scaled C'Wz_perp error is {q3['max_relative_orthogonality']:.3g}; maximum full-versus-pure slope difference is {q3['max_FWL_slope_error']:.3g}. The constant lies in the industry span and all projections/regressions use identical stocks and objective weights.",
      'Weighted FWL makes the two signal slopes identical by construction; the equality is not evidence of a premium. A positive pure value signal identifies a stock cheaper than its industries, size, profitability, investment and beta predict. Original value exposure can bundle all these sources; purified value asks about return differences at similar controls. Pure means zero weighted linear exposure to the selected controls only. The full and pure return regressions need not have identical fitted returns or residuals because the latter omits controls.']))
    pages.append(('Reproduction, checks, and limits',[
      f"Actual synthetic verification: {tests['tests_run']} tests, {tests['failures']} failures, {tests['errors']} errors, {tests['skipped']} skipped; {tests['elapsed_seconds']:.2f} seconds. Tests include exact OLS/Welch benchmarks, signed clipping, missing-session aging, calendar/leap boundaries, save/restart, future poisoning, joint-factor rank/missingness, matched weighted losses, independent statsmodels HAC, SIC endpoints/overlaps/caps/checksums, June formation timing, affine span and weighted FWL. These numerical checks do not establish economic profitability.",
      f"Final local validation checksum-verified {checks['accepted_daily_files_checksum_verified']:,} accepted daily Parquet files and their annual manifests without rewriting them. Empirical products match manifest row counts, have no duplicate/null stock-month keys, positive origin ME and exactly one-month forecast horizons. The PS1 security input still matches its pre-SIC/pre-beta SHA-256 fingerprint. Every source and final output file is inventoried. No new daily WRDS extraction, package installation or change to PS1 was needed.",
      'The daily panel was processed into annual/monthly sufficient statistics under a DuckDB memory limit; no 102-million-row DataFrame was created. Betas retain only bounded rolling/expanding state, Q2 processes annual stock histories with saved joint state, and Q3 computes one monthly cross section at a time with checksummed restart files. A DuckDB limit is not a whole-process memory limit. Recorded beta engine peaks are available in annual manifests; resource notes distinguish resumed finalization time from original computation time.',
      'Reproduce locally with the existing virtual environment: first run scripts/ps2_build_beta_panel.py to verify/reuse or create the monthly beta cache, then scripts/ps2_empirical.py --beta-cache <cache> for a fresh Q1 run. Run scripts/ps2_finish_empirical.py --run <new-run> --beta-cache <cache> --sic <accepted-sic-parquet> for Q2/Q3/report. These empirical commands do not connect to WRDS. Keep all raw inputs and manifests at their recorded paths. Existing final reports refuse overwrite. Run python -B -m unittest discover -s tests with src on sys.path; the exact tested command is documented in REPRODUCE.md.',
      'The retained Welch initialization and source-convention differences are explicit: expanding starts in 1960 by approval; rho=2/252 versus 2/256 and both aging rules are sensitivity results. Minimum-history conventions and equal-weight characteristic normalization are analysis policies, not universal financial identities. Q2 lacks pre-July-1963 traded-factor initialization, and its common forecast sample starts in August 1968. The accounting vintage limitation and invalid SIC exclusions can affect external validity. These limits are disclosed rather than repaired with invented data.',
      'Technical attempts that failed before valid completion are preserved: local SIC validation exceeded its initial memory cap, an inefficient local interval join was stopped, a Parquet date-type comparison triggered the Q1 empty-sample guard, and a reserved SQL alias was corrected. Q2 final manifest writing initially rejected a relative path after tables were computed; its annual caches were checksum-verified and resumed without overwriting tables. The selected valid beta cache and empirical run are unambiguous in manifests. No failed or truncated extraction is treated as a complete dataset.',
      'References: Quantitative Investing Problem Set 2, pp. 1-5; Welch (2022), Simply Better Market Betas, Critical Finance Review 11(1), 37-64, especially pp. 38, 48 and Appendix p. 63, https://cfr.ivo-welch.info/published/papers/welch2022simply.pdf; official French Data Library daily factor archive and FF12 SIC definitions preserved in source manifests; CRSP CIZ source definitions preserved in Pilot B documentation. Welch details and source links are recorded in docs/ps2_welch_method.md.']))
    text='# Quantitative Investing PS2: empirical results\n\n'
    for title,paragraphs in pages:text+='## '+title+'\n\n'+'\n\n'.join(paragraphs)+'\n\n'
    with (out/'report.md').open('x',encoding='utf-8') as f:f.write(text)
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib import colors
    styles=getSampleStyleSheet();style=ParagraphStyle('body',parent=styles['BodyText'],fontSize=9.2,leading=12,spaceAfter=8)
    story=[]
    for i,(title,paragraphs) in enumerate(pages):
        if i:story.append(PageBreak())
        story.append(Paragraph(html.escape(title),styles['Heading2']))
        for paragraph in paragraphs:story.append(Paragraph(html.escape(paragraph),style))
    def footer(canvas,doc):canvas.setFont('Helvetica',8);canvas.drawRightString(560,25,f'PS2 empirical writeup | {doc.page}')
    SimpleDocTemplate(str(out/'report.pdf'),pagesize=(612,792),rightMargin=42,leftMargin=42,topMargin=35,bottomMargin=38).build(story,onFirstPage=footer,onLaterPages=footer)
    q1table=rmse[(rmse.period.isin(['IS','OOS']))&(rmse.model.isin(['ols_1y','ols_3y','ols_expanding_1960','welch_256_cal','welch_252_cal','shrinkage']))]
    with (out/'tables.csv').open('x',encoding='utf-8',newline='') as f:q1table.to_csv(f,index=False)
    sourcefiles=[*io.ROOT.glob('src/ps2/*.py'),*io.ROOT.glob('scripts/ps2*.py'),*io.ROOT.glob('tests/test_ps2*.py')]
    fingerprints={str(p.relative_to(io.ROOT)):io.sha256(p) for p in sourcefiles}
    for name in ['formation','q2_factors','ref_ff5_0','crsp_index','security_month']:
        p=io.ROOT/f'data/processed/{name}.parquet';fingerprints[str(p.relative_to(io.ROOT))]=io.sha256(p)
    io.dump_new(out/'reproducibility.json',{'source_fingerprints':fingerprints,'beta_cache':str(beta_root.relative_to(io.ROOT)),
        'SIC':str(sic.relative_to(io.ROOT)),'records':records,'tests':tests})
    allfiles=[p for base in [out,io.ROOT/'data/processed/ps2'/out.name] for p in base.rglob('*') if p.is_file() and 'temporary' not in p.parts]
    io.dump_new(out/'file_inventory.json',{'files':[{'path':str(p.relative_to(io.ROOT)),'bytes':p.stat().st_size,'sha256':io.sha256(p)} for p in allfiles]})
    print('REPORT_COMPLETE '+str(out.relative_to(io.ROOT)),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--beta-cache',type=Path,required=True);p.add_argument('--sic',type=Path,required=True)
    a=p.parse_args();build(a.run.resolve(),a.beta_cache.resolve(),a.sic.resolve())
