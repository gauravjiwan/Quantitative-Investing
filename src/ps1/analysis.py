"""All PS1 empirical tasks, reference reconciliation, and reproducible figures."""
from __future__ import annotations
import os
from pathlib import Path
import numpy as np
import pandas as pd
from .core import ROOT, DataError, config, months, read, save, table, coverage, dates
from .statistics import summarize,reconcile
from .portfolios import assign,size_breakpoints,portfolio_returns,factor_from_six,capital_wealth

def plot_frame(df,name,title,root=ROOT,log=False):
    os.environ.setdefault('MPLCONFIGDIR',str(Path(root)/'.mplconfig'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(11,6));df.plot(ax=ax,lw=1.15,logy=log);ax.set_title(title);ax.set_xlabel('Month');ax.grid(alpha=.2);ax.legend(fontsize=8)
    fig.tight_layout();p=Path(root)/'outputs/figures';p.mkdir(parents=True,exist_ok=True);fig.savefig(p/f'{name}.png',dpi=160);plt.close(fig)

def rf(root):
    f=read('ref_ff5_0',root).set_index('month');coverage(f.reset_index(),root,'French FF5');return f.RF

def window(panel,root):return panel[panel.month.isin(months(root))].copy()

def checks(series,root,label):
    coverage(series.rename_axis('month').reset_index(),root,label)
    if series.isna().any():raise DataError(f'{label}: missing portfolio observations')

def market_series(p,root):
    p=window(p,root);p=p[p.eligible & np.isfinite(p.ret)&p.ret.ge(-1)].copy()
    ew=p.groupby('month').agg(ret=('ret','mean'),security_count=('permno','size')).reset_index();ew['portfolio']='market';ew['weighting']='EW'
    v=p[p.lag_me.gt(0)].copy();v['weighted_return']=v.ret*v.lag_me
    vw=v.groupby('month').agg(weighted_return=('weighted_return','sum'),weight_cap=('lag_me','sum'),security_count=('permno','size')).reset_index();vw['ret']=vw.weighted_return/vw.weight_cap;vw['portfolio']='market';vw['weighting']='VW'
    return pd.concat([ew,vw],ignore_index=True)

def summaries(long,root,zero=False):
    result=[]
    for (portfolio,weighting),g in long.groupby(['portfolio','weighting']):
        s=g.set_index('month').ret;checks(s,root,portfolio+' '+weighting)
        out={'portfolio':portfolio,'weighting':weighting,**summarize(s,rf(root),zero)}
        for k in ['security_count','unit_count']:
            if k in g:out['average_'+k]=g[k].mean()
        result.append(out)
    return pd.DataFrame(result)

def q1(root=ROOT):
    p=read('security_month',root);market=market_series(p,root);save(market,'q1_market',root);table(summaries(market,root),'q1_market_statistics',root)
    idx=read('crsp_index',root).set_index('month');rows=[]
    for w,col in [('EW','ewretd'),('VW','vwretd')]:
        s=market[market.weighting.eq(w)].set_index('month').ret
        rows.append({'portfolio':'market','weighting':w,**reconcile(s,idx[col])})
    june=p[p.eligible&p.month.dt.month.eq(6)&p.me.gt(0)][['permno','month','me','exchange']].copy();june['formation_year']=june.month.dt.year;june=june.rename(columns={'me':'june_me'})
    labels,bp=assign(june,size_groups=10);save(labels,'q1_size_membership',root);table(bp,'q1_size_breakpoints',root)
    returns=portfolio_returns(window(p[p.eligible],root),labels,key='permno');save(returns,'q1_size_returns',root);table(summaries(returns,root),'q1_size_statistics',root)
    for w,section in [('VW',0),('EW',1)]:
        ref=read(f'ref_size_{section}',root).set_index('month')
        cols=['Lo 10']+[f'{i}-Dec' for i in range(2,10)]+['Hi 10']
        if not set(cols).issubset(ref.columns):raise DataError(f'Unexpected French size decile columns: {list(ref.columns)}')
        for i,col in enumerate(cols,1):
            s=returns[returns.weighting.eq(w)&returns.portfolio.eq(f'D{i:02}')].set_index('month').ret
            rows.append({'portfolio':f'D{i:02}','weighting':w,**reconcile(s,ref[col])})
    table(pd.DataFrame(rows),'q1_reconciliation',root)
    market_wide=market.pivot(index='month',columns='weighting',values='ret');plot_frame((1+market_wide).cumprod(),'q1_market_wealth','Q1: market total-return wealth ($1 initial)',root,True)
    wide=returns.pivot(index='month',columns=['portfolio','weighting'],values='ret')
    gap=pd.DataFrame({f'D{i:02}':wide[(f'D{i:02}','EW')]-wide[(f'D{i:02}','VW')] for i in range(1,11)})
    plot_frame(gap.cumsum(),'q1_size_ew_vw_gap','Q1: cumulative monthly EW minus VW return differences',root)
    print('Q1 complete.')

def construct_factors(f,p,root,return_column='ret'):
    factors={};parts={};breakpoints=[];counts=[]
    common_size=size_breakpoints(f,2)
    for kind in ['bm','op','inv']:
        labels,bp=assign(f,kind,size_points=common_size);r=portfolio_returns(window(p,root),labels,return_column=return_column)
        smb,spread=factor_from_six(r,kind);factors['SMB_'+kind]=smb;factors[{'bm':'HML','op':'RMW','inv':'CMA'}[kind]]=spread
        parts[kind]=r;breakpoints.append(bp);counts.append(labels.groupby('formation_year').size().rename(kind))
    out=pd.DataFrame(factors);out['SMB']=out[['SMB_bm','SMB_op','SMB_inv']].mean(axis=1)
    market=market_series(read('security_month',root),root);out['Mkt-RF']=market[market.weighting.eq('VW')].set_index('month').ret-rf(root)
    for col in out:checks(out[col],root,col)
    return out,parts,pd.concat(breakpoints),pd.concat(counts,axis=1)

def q2(root=ROOT):
    f=read('formation',root);p=read('company_month',root);out,parts,bps,counts=construct_factors(f,p,root)
    save(out.reset_index(names='month'),'q2_factors',root);table(out.reset_index(names='month'),'q2_factors',root);table(bps,'q2_breakpoints',root);table(counts.reset_index(),'q2_formation_counts',root)
    ref=read('ref_ff5_0',root).set_index('month');stats=[];gaps=[]
    for factor in ['Mkt-RF','SMB','HML','RMW','CMA']:
        for source,values in [('constructed',out[factor]),('French',ref[factor])]:stats.append({'factor':factor,'source':source,**summarize(values,zero_investment=True)})
        gaps.append({'factor':factor,**reconcile(out[factor],ref[factor])})
    table(pd.DataFrame(stats),'q2_factor_statistics',root);table(pd.DataFrame(gaps),'q2_reconciliation',root)
    base_gaps=[]
    for kind,r in parts.items():
        save(r,f'q2_{kind}_six',root)
        rr=read(f'ref_{kind}6_0',root).set_index('month')
        vw=r[r.weighting.eq('VW')].pivot(index='month',columns='portfolio',values='ret')
        for k,col in zip([f'S{s}C{c}' for s in [1,2] for c in [1,2,3]],rr.columns):base_gaps.append({'characteristic':kind,'portfolio':k,'French_column':col,**reconcile(vw[k],rr[col])})
    table(pd.DataFrame(base_gaps),'q2_basic_portfolio_reconciliation',root)
    plot_frame(out[['Mkt-RF','SMB','HML','RMW','CMA']]-ref[['Mkt-RF','SMB','HML','RMW','CMA']],'q2_factor_gaps','Q2: constructed minus published monthly factor returns',root)
    low=min(gaps,key=lambda x:x['correlation'])['factor']
    variants=[]
    representative,_,_,_=construct_factors(f,p,root,'representative_ret')
    for factor in ['Mkt-RF','SMB','HML','RMW','CMA']:
        variants.append({'variant':'representative_share_return','factor':factor,**reconcile(representative[factor],ref[factor])})
    # Strict-expense variant changes only profitability eligibility; hold original size breakpoints fixed.
    strict=f.copy();strict.loc[strict.missing_expense_count.gt(0),'op']=np.nan
    labels,_=assign(strict,'op',size_points=size_breakpoints(f,2));r=portfolio_returns(window(p,root),labels);smbo,rmw=factor_from_six(r,'op')
    for factor,s in [('RMW',rmw),('SMB',(out.SMB_bm+smbo+out.SMB_inv)/3)]:variants.append({'variant':'all_three_expenses_required','factor':factor,**reconcile(s,ref[factor])})
    table(pd.DataFrame(variants),'q2_sensitivity',root)
    (Path(root)/'outputs/q2_diagnosis.md').write_text(f'# Factor reconciliation diagnosis\n\nLowest-correlation factor: **{low}**.\n\nInspect q2_basic_portfolio_reconciliation.csv and characteristic_coverage.csv, then compare one-at-a-time share-class and expense-policy variants in q2_sensitivity.csv. These are measured sensitivity checks, not proof of the historical cause of every gap.\n')
    labels,bp=assign(f,'bm',size_groups=5,char_groups=5);r=portfolio_returns(window(p,root),labels);save(r,'q2_bm25',root);table(bp,'q2_bm25_breakpoints',root)
    vw=r[r.weighting.eq('VW')].pivot(index='month',columns='portfolio',values='ret');wealth={};ls={};comparisons=[];ref25=read('ref_bm25_0',root).set_index('month')
    for label,col in zip([f'S{s}C{c}' for s in range(1,6) for c in range(1,6)],ref25.columns):
        checks(vw[label],root,label);comparisons.append({'portfolio':label,'French_column':col,**reconcile(vw[label],ref25[col])})
    for s in range(1,6):
        ret,w=capital_wealth(vw[f'S{s}C5'],vw[f'S{s}C1'],rf(root));checks(ret,root,f'capital S{s}');ls[f'S{s}']=ret;wealth[f'S{s}']=w
    save(pd.DataFrame(ls).reset_index(names='month'),'q2_long_short_capital_returns',root);table(pd.DataFrame(wealth).reset_index(names='month'),'q2_long_short_wealth',root);table(pd.DataFrame(comparisons),'q2_bm25_reconciliation',root)
    initial=pd.DataFrame({k:[1.] for k in wealth},index=[pd.Timestamp(config(root)['sample']['return_start'])-pd.offsets.Day(1)])
    plot_frame(pd.concat([initial,pd.DataFrame(wealth)]),'q2_long_short_wealth','Q2: five collateralized high-minus-low B/M strategies',root,True)
    factor_diagnostics(root)
    print('Q2 complete; lowest factor correlation:',low)

def q3(root=ROOT):
    f=read('formation',root);p=window(read('company_month',root),root);original=read('q2_factors',root).set_index('month');split=pd.Timestamp(config(root)['methodology']['q3_split']);size_points=size_breakpoints(f,2)
    rows=[];all_returns=[];count_rows=[]
    for base,new,factor in [('bm','ep','HML'),('op','gp','RMW')]:
        matched=f[np.isfinite(f[base])&np.isfinite(f[new])].copy();variants={'Q2_full_baseline':original[factor]}
        for characteristic,label in [(base,'matched_baseline'),(new,'modified')]:
            formation,_=assign(matched,characteristic,size_points=size_points);r=portfolio_returns(p,formation);_,s=factor_from_six(r,characteristic);variants[label]=s
            count_rows.append(formation.groupby('formation_year').size().rename(label).reset_index().assign(characteristic=new))
        for label,s in variants.items():
            checks(s,root,new+' '+label);all_returns.append(s.rename('ret').reset_index().assign(characteristic=new,variant=label))
            for win,mask in [('in_sample',s.index<split),('out_of_sample',s.index>=split)]:rows.append({'characteristic':new,'variant':label,'window':win,**summarize(s.loc[mask],zero_investment=True)})
    stats=pd.DataFrame(rows);table(stats,'q3_statistics',root);save(pd.concat(all_returns,ignore_index=True),'q3_returns',root);table(pd.concat(count_rows,ignore_index=True),'q3_coverage',root)
    differences=[]
    for (char,win),g in stats.groupby(['characteristic','window']):
        v=g.set_index('variant').sharpe_annual;differences.append({'characteristic':char,'window':win,'modified_minus_Q2_sharpe':v.modified-v.Q2_full_baseline,'modified_minus_matched_sharpe':v.modified-v.matched_baseline})
    table(pd.DataFrame(differences),'q3_sharpe_differences',root);print('Q3 complete; fixed split:',split.strftime('%Y-%m'))

def cross_section(y,x,weights=None):
    x=np.column_stack([np.ones(len(x)),np.asarray(x,dtype=float)]);y=np.asarray(y,dtype=float)
    weights=np.ones(len(y)) if weights is None else np.asarray(weights,dtype=float)/np.mean(weights)
    a=x*np.sqrt(weights[:,None]);b=y*np.sqrt(weights)
    if np.linalg.matrix_rank(a)<x.shape[1]:raise DataError('Rank-deficient monthly regression')
    # SVD-based mapping avoids squaring the condition number through X'WX.
    mapping=np.linalg.pinv(a)*np.sqrt(weights)[None,:];beta=mapping@y
    identity=mapping@x
    if not np.allclose(identity,np.eye(x.shape[1]),atol=2e-6,rtol=2e-6):raise DataError('FMP target exposures do not equal identity')
    if not np.allclose(mapping[1:].sum(axis=1),0,atol=2e-6):raise DataError('Slope FMP is not zero net investment')
    return beta,mapping,np.linalg.cond(a)

def q4(root=ROOT):
    p=window(read('company_month',root),root);f=read('formation',root)
    p=p.merge(f[['permco','formation_year','bm','op']],on=['permco','formation_year'],how='left',validate='many_to_one')
    p=p[np.isfinite(p.ret)&p.ret.ge(-1)&p.lag_me.gt(0)&p.bm.gt(0)&np.isfinite(p.op)].copy()
    p['log_size']=np.log(p.lag_me);p['log_bm']=np.log(p.bm);cols=['log_size','log_bm','op'];rows=[];diagnostics=[]
    minimum=config(root)['methodology']['minimum_regression_observations']
    for month,g in p.groupby('month'):
        if len(g)<minimum:raise DataError(f'{month:%Y-%m}: only {len(g)} regression observations')
        x=g[cols].to_numpy(dtype=float);sd=x.std(axis=0,ddof=0)
        if (sd<=0).any():raise DataError(f'{month:%Y-%m}: zero cross-sectional characteristic dispersion')
        z=(x-x.mean(axis=0))/sd
        for standardization,xx in [('raw',x),('zscore',z)]:
            for weighting in ['OLS','WLS']:
                beta,weights,condition=cross_section(g.ret,xx,None if weighting=='OLS' else g.lag_me)
                for j,col in enumerate(cols,1):rows.append({'month':month,'characteristic':col,'standardization':standardization,'weighting':weighting,'coefficient':beta[j],'companies':len(g),'gross_exposure':np.abs(weights[j]).sum()})
                diagnostics.append({'month':month,'standardization':standardization,'weighting':weighting,'condition_number':condition,'companies':len(g),'maximum_absolute_op':g.op.abs().max(),'largest_company_cap_share':g.lag_me.max()/g.lag_me.sum()})
    result=pd.DataFrame(rows);save(result,'q4_coefficients',root);table(pd.DataFrame(diagnostics),'q4_regression_diagnostics',root);statistics=[]
    for (char,standard,w),g in result.groupby(['characteristic','standardization','weighting']):
        s=g.set_index('month').coefficient;checks(s,root,char+standard+w);statistics.append({'characteristic':char,'standardization':standard,'weighting':w,**summarize(s,zero_investment=True),'average_companies':g.companies.mean(),'average_gross_exposure':g.gross_exposure.mean()})
    stats=pd.DataFrame(statistics);stats['t_sharpe_identity_error']=stats.t_iid-stats.sharpe_annual*np.sqrt(stats.months/12);table(stats,'q4_statistics',root)
    rmw=read('q2_factors',root).set_index('month').RMW;comparisons=[]
    for (standard,w),g in result[result.characteristic.eq('op')].groupby(['standardization','weighting']):
        s=g.set_index('month').coefficient;comparisons.append({'standardization':standard,'weighting':w,'FMP_sharpe':summarize(s,zero_investment=True)['sharpe_annual'],'RMW_sharpe':summarize(rmw.reindex(s.index),zero_investment=True)['sharpe_annual'],'correlation_with_RMW':s.corr(rmw)})
    table(pd.DataFrame(comparisons),'q4_profitability_comparison',root);print('Q4 complete; all four regressions use identical monthly company samples.')

def factor_diagnostics(root=ROOT):
    """Attribute the largest monthly reconciliation gap to observable sorted cells."""
    gaps=pd.read_csv(Path(root)/'outputs/tables/q2_reconciliation.csv');low=gaps.loc[gaps.correlation.idxmin()]
    factor=low.factor;kind={'HML':'bm','RMW':'op','CMA':'inv'}.get(factor)
    if not kind:return
    ours=read(f'q2_{kind}_six',root);ours=ours[ours.weighting.eq('VW')].pivot(index='month',columns='portfolio',values='ret')
    reference=read(f'ref_{kind}6_0',root).set_index('month');month=pd.Timestamp(low.max_gap_month);rows=[]
    for label,refcol in zip([f'S{s}C{c}' for s in [1,2] for c in [1,2,3]],reference.columns):
        sign=.5 if label.endswith('C3') else -.5 if label.endswith('C1') else 0.
        if factor=='CMA':sign=-sign
        diff=ours.loc[month,label]-reference.loc[month,refcol]
        rows.append({'factor':factor,'month':month,'portfolio':label,'reference_column':refcol,'constructed_return':ours.loc[month,label],'published_return':reference.loc[month,refcol],'return_gap':diff,'factor_coefficient':sign,'contribution_to_factor_gap':sign*diff})
    decomposition=pd.DataFrame(rows);table(decomposition,'q2_lowest_factor_gap_decomposition',root)
    series=read('q2_factors',root).set_index('month')[factor];ref=read('ref_ff5_0',root).set_index('month')[factor]
    periods=[]
    for start,end in [('1963-07','1973-06'),('1973-07','2000-06'),('2000-07','2025-12')]:periods.append({'factor':factor,'window':start+' through '+end,**reconcile(series.loc[start:end],ref.loc[start:end])})
    table(pd.DataFrame(periods),'q2_lowest_factor_periods',root)
    biggest=decomposition.loc[decomposition.contribution_to_factor_gap.abs().idxmax()]
    sensitivity=pd.read_csv(Path(root)/'outputs/tables/q2_sensitivity.csv');rep=sensitivity[sensitivity.factor.eq(factor)&sensitivity.variant.eq('representative_share_return')].iloc[0]
    text=f'''# Lowest-correlation factor diagnosis\n\n{factor} has full-sample correlation {low.correlation:.6f}. Its largest monthly gap is {month:%Y-%m}: {low.max_abs_gap:.4%} in absolute return. The largest signed cell contribution comes from {biggest.portfolio} ({biggest.reference_column}), contributing {biggest.contribution_to_factor_gap:.4%} to the factor gap, as shown in the table below.\n\nRepresentative-share returns give correlation {rep.correlation:.6f}, versus {low.correlation:.6f} in the aggregate-class baseline, so that convention has little effect on this factor's overall replication. The financial-expense eligibility experiment is materially more consequential for profitability: requiring all three expense items changes the RMW replication and company coverage substantially. The baseline instead implements the published revenue-plus-at-least-one-expense rule.\n\nThe most plausible remaining source is financial characteristic/eligibility and portfolio-weight differences, including accounting vintages and company-accounting choices. This is an inference from cell-level gaps and controlled sensitivities; French security-level inputs and exact holdings are unavailable, so it is not a proven attribution. The period comparison below separates early coverage and later performance.\n'''
    (Path(root)/'outputs/q2_diagnosis.md').write_text(text)
