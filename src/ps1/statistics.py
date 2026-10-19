"""Monthly-return statistics with explicit capital versus zero-investment conventions."""
import numpy as np
import pandas as pd
import statsmodels.api as sm

def summarize(returns,rf=None,zero_investment=False):
    r=pd.Series(returns).astype(float).replace([np.inf,-np.inf],np.nan).dropna()
    if r.empty: raise ValueError('No finite observations')
    excess=r if zero_investment else r-rf.reindex(r.index) if rf is not None else r
    excess=excess.dropna(); sd=r.std(ddof=1); esd=excess.std(ddof=1)
    wealth=(1+r).cumprod(); peaks=wealth.cummax().clip(lower=1)
    out={'months':len(r),'mean_monthly':r.mean(),'vol_monthly':sd,'mean_annual':12*r.mean(),'vol_annual':np.sqrt(12)*sd,'sharpe_annual':np.sqrt(12)*excess.mean()/esd if esd>0 else np.nan,'skewness':r.skew(),'max_drawdown':np.nan if zero_investment else (wealth/peaks-1).min()}
    out['t_iid']=r.mean()/(sd/np.sqrt(len(r))) if sd>0 else np.nan
    if len(r)>2:
        fit=sm.OLS(r.to_numpy(),np.ones((len(r),1))).fit(cov_type='HAC',cov_kwds={'maxlags':min(12,len(r)-1)})
        out['t_hac12']=float(fit.tvalues[0])
    return out

def reconcile(ours,reference):
    x=pd.concat([ours.rename('ours'),reference.rename('reference')],axis=1).dropna()
    d=x.ours-x.reference
    if x.empty: raise ValueError('No common months for reconciliation')
    return {'months':len(x),'correlation':x.ours.corr(x.reference),'mean_gap_monthly':d.mean(),'mean_gap_annual':12*d.mean(),'tracking_error_annual':d.std(ddof=1)*np.sqrt(12),'max_abs_gap':d.abs().max(),'max_gap_month':d.abs().idxmax().strftime('%Y-%m')}
