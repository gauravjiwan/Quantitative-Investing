"""Historical security panel, share-class aggregation, and lagged annual characteristics."""
from __future__ import annotations
import numpy as np
import pandas as pd
import duckdb
from .core import ROOT, DataError, config, mapping, raw, dates, save, read, table, unique, coverage

def calendar_lag(df,key,value):
    prev=df[[key,'month',value]].copy();prev['month']+=pd.offsets.MonthBegin(1)
    return df.merge(prev.rename(columns={value:'lag_'+value}),on=[key,'month'],how='left',validate='one_to_one')

def eligible(df):
    required=['exchange','share_type','security_type','security_subtype','us_incorporated','issuer_type']
    missing=set(required)-set(df)
    if missing: raise DataError(f'Missing historical classification: {sorted(missing)}')
    return (df.exchange.isin(['N','A','Q']) & df.share_type.eq('NS') & df.security_type.eq('EQTY')
            & df.security_subtype.eq('COM') & df.us_incorporated.eq('Y') & df.issuer_type.isin(['ACOR','CORP']))

def attach_names(df,names):
    names=names.copy(); names['name_start']=pd.to_datetime(names.name_start);names['name_end']=pd.to_datetime(names.name_end,errors='coerce').fillna(pd.Timestamp('2099-12-31'))
    attrs=[x for x in names if x not in ['permno','name_start','name_end'] and x not in df]
    if not attrs: return df
    with duckdb.connect() as db:
        db.register('m',df);db.register('h',names)
        select=', '.join('h."'+x+'"' for x in attrs)
        out=db.execute(f'SELECT m.*, {select} FROM m LEFT JOIN h ON m.permno=h.permno AND m.observation_date BETWEEN h.name_start AND h.name_end').df()
    unique(out,['permno','month'],'historical names join');return out

def aggregate_company(securities):
    p=securities.copy();p['valid_return']=np.isfinite(p.ret)&p.ret.ge(-1)&p.lag_me.gt(0)
    p['return_cap']=p.lag_me.where(p.valid_return,0);p['weighted_return']=p.ret.where(p.valid_return,0)*p.return_cap
    p['available_start_cap']=p.lag_me.where(p.lag_me.gt(0))
    grouped=p.groupby(['permco','month'],sort=True)
    totals=grouped[['me','return_cap','available_start_cap','weighted_return']].sum(min_count=1).rename(columns={'return_cap':'covered_start_cap'}).join(grouped.agg(security_count=('permno','size'),return_security_count=('valid_return','sum'))).reset_index()
    totals['ret']=totals.weighted_return/totals.covered_start_cap.replace(0,np.nan)
    # Representative determined from prior-month cap whenever possible; fallback is current cap for formation attributes.
    p['representative_cap']=p.lag_me.fillna(p.me)
    rep=p.sort_values(['representative_cap','permno'],ascending=[False,True]).drop_duplicates(['permco','month'])
    attrs=[x for x in ['exchange','company_name','ticker','permno','ret'] if x in rep]
    rep=rep[['permco','month']+attrs].rename(columns={'permno':'representative_permno','ret':'representative_ret'})
    totals=totals.merge(rep,on=['permco','month'],validate='one_to_one')
    totals=calendar_lag(totals,'permco','me')
    totals['return_cap_coverage']=totals.covered_start_cap/totals.lag_me
    totals['partial_share_class_return']=totals.return_security_count<totals.security_count
    totals['formation_year']=totals.month.dt.year-(totals.month.dt.month<=6).astype(int)
    return totals

def build(root=ROOT):
    m=mapping(root)
    if not m.get('review',{}).get('approved'): raise DataError('Field map and units must be reviewed before building a panel.')
    p=raw('crsp_monthly',root);p['observation_date']=pd.to_datetime(p.month);p['month']=dates(p.month)
    for k in ['permno','permco','ret','retx','price','shares','price_factor','share_factor']:
        if k in p:p[k]=pd.to_numeric(p[k],errors='coerce')
    unique(p,['permno','month'],'raw CRSP')
    p=attach_names(p,raw('crsp_names',root))
    p['me']=p.price.abs()*p.shares*m['review']['shares_to_millions']
    p.loc[p.shares.le(0)|p.price.eq(0),'me']=np.nan
    for rawcol,factor,out,rule in [('price','price_factor','adjusted_price',m['review']['price_adjustment']),('shares','share_factor','adjusted_shares',m['review']['shares_adjustment'])]:
        if factor not in p:raise DataError(f'Missing split factor {factor}')
        f=p[factor].where(p[factor].gt(0));p[out]=p[rawcol]/f if rule=='divide' else p[rawcol]*f
    p=calendar_lag(p,'permno','me')
    p['eligible']=eligible(p); p['return_valid']=np.isfinite(p.ret)&p.ret.ge(-1)
    p['formation_year']=p.month.dt.year-(p.month.dt.month<=6).astype(int)
    research=p[p.month.between(config(root)['sample']['return_start'],config(root)['sample']['return_end'])]
    coverage(research,root,'security panel')
    table(research.groupby('month').agg(raw_securities=('permno','size'),eligible_securities=('eligible','sum'),valid_returns=('return_valid','sum')).reset_index(),'panel_coverage',root)
    # Keep the broad panel for diagnostics; downstream universes apply the saved eligible flag.
    save(p,'security_month',root)
    comp=aggregate_company(p[p.eligible].copy());unique(comp,['permco','month'],'company panel');save(comp,'company_month',root)
    idx=raw('crsp_index',root);idx['month']=dates(idx.month);unique(idx,['month'],'CRSP index');coverage(idx,root,'CRSP index');save(idx,'crsp_index',root)
    table(comp[comp.partial_share_class_return][['permco','month','return_cap_coverage','security_count','return_security_count']],'partial_share_class_returns',root)
    if 'company_name' in p:
        google=p[p.company_name.fillna('').str.contains('GOOGLE|ALPHABET',case=False,regex=True)]
        table(google[['permno','permco','month','ticker','company_name','me','lag_me','ret']],'google_share_classes',root)
        table(comp[comp.permco.isin(google.permco.unique())],'google_company_returns',root)
    print('Panel:',len(p),'security-month rows;',len(comp),'company-month rows.')

def annual_accounting(a):
    a=a.copy();a['datadate']=pd.to_datetime(a.datadate);a['calendar_year']=a.datadate.dt.year
    a['gvkey']=a.gvkey.astype(str).str.replace(r'\.0$','',regex=True).str.zfill(6)
    keep=a.indfmt.eq('INDL')&a.datafmt.eq('STD')&a.popsrc.eq('D')&a.consol.eq('C')&a.curcd.eq('USD')
    a=a[keep].sort_values(['gvkey','datadate'])
    if a.duplicated(['gvkey','datadate']).any(): raise DataError('Duplicate standard USD financial statements for same gvkey/datadate')
    a=a.drop_duplicates(['gvkey','calendar_year'],keep='last')
    for k in ['at','lt','seq','ceq','pstk','pstkrv','pstkl','txditc','sale','cogs','xsga','xint','mib','ib']:
        a[k]=pd.to_numeric(a[k],errors='coerce')
    se=a.seq.combine_first(a.ceq+a.pstk.fillna(0)).combine_first(a['at']-a['lt'])
    ps=a.pstkrv.combine_first(a.pstkl).combine_first(a.pstk).fillna(0)
    a['be']=se-ps+np.where(a.calendar_year.lt(1993),a.txditc.fillna(0),0)
    a['missing_expense_count']=a[['cogs','xsga','xint']].isna().sum(axis=1)
    numerator=a.sale-a[['cogs','xsga','xint']].fillna(0).sum(axis=1)
    den=a.be+a.mib.fillna(0)
    a['op']=(numerator/den).where(a.be.gt(0)&den.gt(0)&a.sale.notna()&a.missing_expense_count.lt(3))
    prev=a[['gvkey','calendar_year','at']].copy();prev.calendar_year+=1;prev=prev.rename(columns={'at':'previous_assets'})
    a=a.merge(prev,on=['gvkey','calendar_year'],how='left',validate='one_to_one')
    a['inv']=((a['at']-a.previous_assets)/a.previous_assets).where(a.previous_assets.gt(0)&a['at'].gt(0))
    a['gp']=((a.sale-a.cogs)/a['at']).where(a['at'].gt(0))
    a['formation_year']=a.calendar_year+1
    return a

def characteristics(root=ROOT):
    a=annual_accounting(raw('compustat_annual',root));save(a,'annual_accounting',root)
    links=raw('ccm_link',root);links=links[links.link_type.isin(['LC','LU'])&links.link_primary.isin(['P','C'])].copy()
    links['gvkey']=links.gvkey.astype(str).str.replace(r'\.0$','',regex=True).str.zfill(6)
    links['link_start']=pd.to_datetime(links.link_start,errors='coerce').fillna(pd.Timestamp('1900-01-01'))
    links['link_end']=pd.to_datetime(links.link_end,errors='coerce').fillna(pd.Timestamp('2099-12-31'))
    links['permno']=pd.to_numeric(links.permno,errors='coerce')
    security=read('security_month',root);j=security[security.eligible&security.month.dt.month.eq(6)][['permno','permco','formation_year','me']].copy();j.formation_year+=1
    # The June panel's formation_year denotes the preceding holding year; June forms the new year.
    with duckdb.connect() as db:
        db.register('a',a);db.register('links',links);db.register('j',j)
        joined=db.execute('''SELECT a.*,j.permco,j.permno,j.me AS class_me,links.link_primary,links.link_type
        FROM a JOIN links ON a.gvkey=links.gvkey AND a.datadate BETWEEN links.link_start AND links.link_end
        JOIN j ON links.permno=j.permno AND a.formation_year=j.formation_year''').df()
    if joined.empty:raise DataError('No date-valid Compustat/CCM/June links')
    joined['link_rank']=joined.link_primary.map({'P':0,'C':1})*2+joined.link_type.map({'LC':0,'LU':1})
    joined=joined.sort_values(['link_rank','class_me','permno'],ascending=[True,False,True]).drop_duplicates(['permco','formation_year','gvkey'])
    if joined.duplicated(['permco','formation_year']).any():
        table(joined[joined.duplicated(['permco','formation_year'],keep=False)][['permco','formation_year','gvkey','permno','datadate','link_primary','link_type','class_me']],'ambiguous_financial_links',root)
        # Tracking stocks can share a PERMCO while linking to distinct business GVKEYs.
        # Select primary/confirmed link first, then the largest June listed class; preserve all candidates.
        resolution=joined[joined.duplicated(['permco','formation_year'],keep=False)].copy()
        selected=joined.drop_duplicates(['permco','formation_year'],keep='first')[['permco','formation_year','gvkey']].assign(selected=True)
        resolution=resolution.merge(selected,on=['permco','formation_year','gvkey'],how='left')
        resolution['selected']=resolution.selected.eq(True)
        resolution['resolution']='primary/confirmed link priority, then largest June class; no financial summation'
        table(resolution[['permco','formation_year','gvkey','permno','datadate','link_primary','link_type','class_me','selected','resolution']],'financial_link_resolutions',root)
        joined=joined.drop_duplicates(['permco','formation_year'],keep='first')
    companies=read('company_month',root)
    june=companies[companies.month.dt.month.eq(6)][['permco','month','me','exchange','security_count']].copy();june['formation_year']=june.month.dt.year;june=june.rename(columns={'me':'june_me'}).drop(columns='month')
    dec=companies[companies.month.dt.month.eq(12)][['permco','month','me']].copy();dec['formation_year']=dec.month.dt.year+1;dec=dec.rename(columns={'me':'dec_me'}).drop(columns='month')
    f=june.merge(dec,on=['permco','formation_year'],how='left',validate='one_to_one').merge(joined.drop(columns=['permno']),on=['permco','formation_year'],how='left',validate='one_to_one')
    f['bm']=(f.be/f.dec_me).where(f.be.gt(0)&f.dec_me.gt(0))
    f['ep']=(f.ib/f.dec_me).where(f.dec_me.gt(0))
    for k in ['bm','op','inv','ep','gp']:
        f[k]=f[k].where(f.june_me.gt(0)&f.dec_me.gt(0)&np.isfinite(f[k]))
    unique(f,['permco','formation_year'],'formation');save(f,'formation',root)
    table(f.groupby('formation_year').agg(companies=('permco','size'),bm=('bm','count'),op=('op','count'),inv=('inv','count'),ep=('ep','count'),gp=('gp','count')).reset_index(),'characteristic_coverage',root)
    print('Formation company-years:',len(f))
