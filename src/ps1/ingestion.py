"""WRDS discovery, reviewed extraction, raw imports, and French reference snapshots."""
from __future__ import annotations
import io, json, re, hashlib, urllib.request, zipfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from sqlalchemy import text as sql_text
from .core import ROOT, DataError, config, mapping, identifier, snapshot, raw, dates, save
from .wrds_client import connect

CATALOG_SQL="""SELECT table_schema,table_name,ordinal_position,column_name,data_type
FROM information_schema.columns WHERE (table_schema ILIKE '%crsp%' OR table_schema ILIKE '%comp%')
AND (table_name ILIKE '%mth%' OR table_name ILIKE '%monthly%' OR table_name ILIKE '%security%'
OR table_name ILIKE '%name%' OR table_name ILIKE '%index%' OR table_name ILIKE '%funda%'
OR table_name ILIKE '%link%' OR table_name ILIKE '%msf%') ORDER BY table_schema,table_name,ordinal_position"""

# Exact sources remain unselected until the account's metadata is observed and reviewed.
CANDIDATES={
'crsp_monthly':{'permno':['permno'],'permco':['permco'],'month':['mthcaldt'],'ret':['mthret'],'retx':['mthretx'],'price':['mthprc'],'shares':['shrout','mthshrout'],'exchange':['primaryexch'],'issuer_type':['issuertype'],'security_type':['securitytype'],'security_subtype':['securitysubtype'],'share_type':['sharetype'],'us_incorporated':['usincflg'],'conditional_type':['conditionaltype'],'trading_status':['tradingstatusflg'],'price_factor':['mthcumfacpr','cumfacpr'],'share_factor':['mthcumfacshr','cumfacshr'],'company_name':['issuernm','comnam'],'ticker':['ticker'],'return_flag':['mthretflg','mthretmissflg'],'return_duration':['mthretdurflg']},
'crsp_names':{'permno':['permno'],'permco':['permco'],'name_start':['secinfostartdt','namedt'],'name_end':['secinfoenddt','nameenddt','nameendt'],'company_name':['issuernm','comnam'],'ticker':['ticker'],'exchange':['primaryexch'],'issuer_type':['issuertype'],'security_type':['securitytype'],'security_subtype':['securitysubtype'],'share_type':['sharetype'],'us_incorporated':['usincflg']},
'crsp_index':{'month':['caldt','mthcaldt'],'vwretd':['vwretd'],'ewretd':['ewretd']},
'compustat_annual':{x:[x] for x in ['gvkey','datadate','fyear','at','lt','seq','ceq','pstk','pstkrv','pstkl','txditc','sale','cogs','xsga','xint','mib','ib','indfmt','datafmt','popsrc','consol','curcd']},
'ccm_link':{'gvkey':['gvkey'],'permno':['lpermno'],'permco':['lpermco'],'link_start':['linkdt'],'link_end':['linkenddt'],'link_type':['linktype'],'link_primary':['linkprim']}}

REQUIRED={
'crsp_monthly':['permno','permco','month','ret','retx','price','shares'],
'crsp_names':['permno','name_start','name_end'],
'crsp_index':['month','vwretd','ewretd'],
'compustat_annual':['gvkey','datadate','at','lt','seq','ceq','pstk','pstkrv','pstkl','txditc','sale','cogs','xsga','xint','mib','ib','indfmt','datafmt','popsrc','consol','curcd'],
'ccm_link':['gvkey','permno','link_start','link_end','link_type','link_primary']}

def inventory(root=ROOT):
    root=Path(root); c=connect()
    try: df=c.raw_sql(sql_text(CATALOG_SQL))
    finally: c.close()
    p=root/'data/raw/metadata'; p.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    snapshot(df,p/f'catalog_{stamp}.parquet','WRDS information_schema',CATALOG_SQL,root)
    df.to_csv(p/'latest_catalog.csv',index=False)
    proposals={}
    for kind,candidates in CANDIDATES.items():
        options=[]
        for (schema,table_name),g in df.groupby(['table_schema','table_name']):
            cols=set(g.column_name.str.lower()); fields={k:next((v for v in vs if v in cols),'') for k,vs in candidates.items()}
            if all(fields.get(k) for k in REQUIRED[kind]):
                options.append({'table':schema+'.'+table_name,'fields':fields})
        proposals[kind]=options
    (p/'mapping_candidates.json').write_text(json.dumps(proposals,indent=2)+'\n')
    print('Authenticated; metadata saved to',p)
    for k,v in proposals.items(): print(k,':',len(v),'candidate tables')
    print('Review candidates and CIZ units/classification documentation before selecting config/field_map.toml. No stock observations downloaded.')

def reviewed(root):
    m=mapping(root)
    if not m.get('review',{}).get('approved',False):
        raise DataError('field_map.toml review.approved is false: authenticate inventory, select verified tables/fields and units first.')
    for kind in REQUIRED:
        spec=m.get(kind,{})
        if not spec.get('table'): raise DataError(f'Unmapped {kind} table')
        identifier(spec['table'])
        for k in REQUIRED[kind]:
            if not spec.get(k): raise DataError(f'Unmapped {kind}.{k}')
        for k,v in spec.items():
            if k!='table' and v: identifier(v)
    if not isinstance(m['review'].get('shares_to_millions'),(float,int)) or m['review']['shares_to_millions']<=0:
        raise DataError('Specify verified shares_to_millions (e.g. 0.001 only if raw shares are thousands).')
    return m

def extract(root=ROOT,pilot=False):
    root=Path(root); m=reviewed(root); c=connect(); s=config(root)['sample']
    try:
        for kind,spec in ((k,m[k]) for k in REQUIRED):
            fields=', '.join(f'{identifier(v)} AS {identifier(k)}' for k,v in spec.items() if k!='table' and v)
            datekey={'crsp_monthly':'month','crsp_index':'month','compustat_annual':'datadate'}.get(kind)
            years=range(1962,2026) if kind=='crsp_monthly' else range(1963,2026) if kind=='crsp_index' else range(1961,2025) if kind=='compustat_annual' else [None]
            if pilot: years=[next(iter(years))]
            for y in years:
                folder=root/'data/raw'/('pilot/'+kind if pilot else kind); path=folder/f'{y or "history"}.parquet'
                if path.exists():
                    manifest=path.with_suffix('.json')
                    if not manifest.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=json.loads(manifest.read_text())['sha256']: raise DataError(f'Cached raw checksum mismatch: {path}')
                    print('Cached',path.name,kind); continue
                where=''
                if datekey:
                    start=max(pd.Timestamp(f'{y}-01-01'),pd.Timestamp(s['market_data_start']+'-01')) if kind=='crsp_monthly' else max(pd.Timestamp(f'{y}-01-01'),pd.Timestamp(s['return_start']+'-01')) if kind=='crsp_index' else pd.Timestamp(f'{y}-01-01')
                    end=pd.Timestamp(f'{y+1}-01-01')
                    where=f" WHERE {identifier(spec[datekey])} >= '{start:%Y-%m-%d}' AND {identifier(spec[datekey])} < '{end:%Y-%m-%d}'"
                query=f'SELECT {fields} FROM {identifier(spec["table"])}{where}'
                df=c.raw_sql(sql_text(query))
                if df.empty: raise DataError(f'Empty WRDS export: {kind} {y}')
                snapshot(df,path,spec['table'],query,root); print(kind,y,len(df))
    finally: c.close()

def import_export(kind,file,root=ROOT):
    m=reviewed(root); file=Path(file)
    df=pd.read_parquet(file) if file.suffix.lower()=='.parquet' else pd.read_csv(file,low_memory=False)
    df.columns=df.columns.str.lower()
    ren={v.lower():k for k,v in m[kind].items() if k!='table' and v}
    df=df.rename(columns=ren)
    missing=set(REQUIRED[kind])-set(df)
    if missing: raise DataError(f'Export missing fields: {sorted(missing)}')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    snapshot(df,Path(root)/'data/raw'/kind/f'import_{stamp}.parquet',f'User-supplied WRDS export: {file.name}',root=root)

REFERENCE_FILES={
'ff5':'F-F_Research_Data_5_Factors_2x3',
'size':'Portfolios_Formed_on_ME',
'bm25':'25_Portfolios_5x5',
'bm6':'6_Portfolios_2x3',
'op6':'6_Portfolios_ME_OP_2x3',
'inv6':'6_Portfolios_ME_INV_2x3'}

def french_blocks(content):
    """Read only six-digit monthly CSV rows, preserving section heading and order."""
    blocks=[]; rows=[]; header=None; heading=''; pending=''
    for line in content.splitlines():
        if re.match(r'^\s*\d{6}\s*,',line):
            rows.append(line); continue
        if rows:
            text=(header or '')+'\n'+'\n'.join(rows)
            df=pd.read_csv(io.StringIO(text),index_col=0)
            df.index=pd.to_datetime(df.index.astype(str),format='%Y%m')
            df.columns=df.columns.str.strip()
            df=df.apply(pd.to_numeric,errors='coerce').replace([-99.99,-999],np.nan)
            if 'return' in heading.lower() or 'Mkt-RF' in df.columns: df=df/100
            blocks.append((heading,df)); rows=[]
        if line.strip():
            if line.lstrip().startswith(','): header=line; heading=pending
            else: pending=line.strip()
    if rows: raise DataError('French CSV ended without a section delimiter')
    if not blocks: raise DataError('No monthly blocks found in French CSV')
    return blocks

def references(root=ROOT):
    root=Path(root); folder=root/'data/raw/french'; folder.mkdir(parents=True,exist_ok=True)
    for kind,file in REFERENCE_FILES.items():
        url=f'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{file}_CSV.zip'
        p=folder/f'{kind}.zip'; manifest=p.with_suffix('.json')
        if not p.exists():
            request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 PS1 academic research'})
            with urllib.request.urlopen(request,timeout=90) as response: data=response.read()
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if not z.namelist(): raise DataError(f'Empty reference archive {url}')
            p.write_bytes(data); manifest.write_text(json.dumps({'source':url,'retrieved_utc':datetime.now(timezone.utc).isoformat(),'sha256':hashlib.sha256(data).hexdigest()},indent=2)+'\n')
        if not manifest.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=json.loads(manifest.read_text())['sha256']:
            raise DataError(f'Reference checksum mismatch {p}')
        with zipfile.ZipFile(p) as z:
            member=next(x for x in z.namelist() if x.lower().endswith('.csv')); content=z.read(member).decode('utf-8-sig')
        for i,(heading,df) in enumerate(french_blocks(content)):
            df=df.loc[config(root)['sample']['return_start']:config(root)['sample']['return_end']]
            out=df.reset_index(names='month'); save(out,f'ref_{kind}_{i}',root)
            print(kind,i,heading,len(out),list(df.columns)[:3])
        (folder/f'{kind}_sections.json').write_text(json.dumps([{'index':i,'heading':h,'columns':list(d.columns)} for i,(h,d) in enumerate(french_blocks(content))],indent=2)+'\n')
