"""NYSE independent annual sorts and calendar-correct monthly portfolio returns."""
import numpy as np
import pandas as pd
from .core import DataError

def bins(values,points): return np.searchsorted(np.asarray(points),values,side='left')+1

def size_breakpoints(f,groups=2):
    records=[]
    for year,g in f.groupby('formation_year'):
        ny=g.loc[g.exchange.eq('N')&g.june_me.gt(0),'june_me']
        if len(ny)<groups:raise DataError(f'{year}: insufficient NYSE size observations')
        records.append((year,np.quantile(ny,np.arange(1,groups)/groups)))
    return dict(records)

def assign(f,characteristic=None,size_groups=2,char_groups=3,size_points=None):
    points=size_points or size_breakpoints(f,size_groups);pieces=[];breaks=[]
    for year,g in f.groupby('formation_year'):
        g=g[g.june_me.gt(0)].copy()
        if characteristic:g=g[np.isfinite(g[characteristic])].copy()
        if g.empty:raise DataError(f'{year}: empty {characteristic} formation sample')
        g['size_group']=bins(g.june_me,points[year]);cp=[]
        if characteristic:
            ny=g.loc[g.exchange.eq('N'),characteristic]
            if len(ny)<char_groups:raise DataError(f'{year}: insufficient NYSE {characteristic} observations')
            q=[.3,.7] if char_groups==3 else list(np.arange(1,char_groups)/char_groups)
            cp=np.quantile(ny,q);g['char_group']=bins(g[characteristic],cp)
            g['portfolio']=[f'S{x}C{y}' for x,y in zip(g.size_group,g.char_group)]
        else:g['portfolio']='D'+g.size_group.astype(str).str.zfill(2)
        breaks.append({'formation_year':year,'size_breakpoints':';'.join(map(str,points[year])),'characteristic':characteristic or 'size','characteristic_breakpoints':';'.join(map(str,cp)),'formation_count':len(g)})
        pieces.append(g)
    return pd.concat(pieces,ignore_index=True),pd.DataFrame(breaks)

def portfolio_returns(panel,formation,key='permco',return_column='ret'):
    labels=formation[[key,'formation_year','portfolio']]
    if labels.duplicated([key,'formation_year']).any():raise DataError('Duplicate formation membership')
    p=panel.merge(labels,on=[key,'formation_year'],how='inner',validate='many_to_one')
    p=p[np.isfinite(p[return_column])&p[return_column].ge(-1)].copy()
    p['security_count']=p['return_security_count'] if 'return_security_count' in p else p['security_count'] if 'security_count' in p else 1
    ew=p.groupby(['month','portfolio']).agg(ret=(return_column,'mean'),security_count=('security_count','sum'),unit_count=(key,'size')).reset_index();ew['weighting']='EW'
    p=p[p.lag_me.gt(0)].copy();p['weighted_return']=p[return_column]*p.lag_me
    vw=p.groupby(['month','portfolio']).agg(weighted_return=('weighted_return','sum'),weight_cap=('lag_me','sum'),security_count=('security_count','sum'),unit_count=(key,'size')).reset_index()
    vw['ret']=vw.weighted_return/vw.weight_cap;vw['weighting']='VW'
    return pd.concat([ew,vw],ignore_index=True)

def factor_from_six(returns,kind):
    p=returns[returns.weighting.eq('VW')].pivot(index='month',columns='portfolio',values='ret')
    required=[f'S{s}C{c}' for s in [1,2] for c in [1,2,3]]
    if any(k not in p for k in required) or p[required].isna().any().any():raise DataError(f'Empty {kind} 2x3 cell/month')
    smb=p[['S1C1','S1C2','S1C3']].mean(axis=1)-p[['S2C1','S2C2','S2C3']].mean(axis=1)
    spread=.5*(p.S1C3+p.S2C3-p.S1C1-p.S2C1)
    if kind=='inv':spread=-spread
    return smb,spread

def capital_wealth(high,low,rf):
    ret=high-low+rf
    if (1+ret<=0).any():raise DataError('Long-short capital exhausted: monthly gross return <= 0; cannot continue normal rebalancing.')
    return ret,(1+ret).cumprod()
