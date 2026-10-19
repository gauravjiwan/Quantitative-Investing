"""Local-only, annual-restartable daily-to-monthly beta integration.

Never opens WRDS or changes source partitions. Fixed NumPy history plus bounded
DuckDB queries replace loading the daily panel into Python memory.
"""
import argparse,hashlib,json,sys,time,uuid,shutil
from pathlib import Path
import duckdb,numpy as np,pandas as pd
import pyarrow.parquet as pq
import ps2_extract_daily as io
sys.path.insert(0,str(io.ROOT/'src'))
from ps2.beta_history import BetaHistory,VARIANTS,WELCH_COLUMNS

FF=io.ROOT/'data/processed/ps2/french/20261019T032947505510Z/ff3_daily_decimal.parquet'
CONFIG={'history_start':'1960-01-01','first_origin':'1963-06','last_origin':'2025-11',
    'hist_min_days':20,'realized_min_days':10,'realized_min_fraction':.5,
    'Welch_require_current_return':True,'return_flags':['NA'],
    'one_period_durations':['D1','D2','D3','D4','DU'],
    'Welch_variants':list(zip(WELCH_COLUMNS,VARIANTS)),
    'OLS_windows':'(calendar month-end minus DateOffset(years=1 or3),month-end]; expanding since1960',
    'split_realization_month':'2000-07','memory_limit':'512MB','threads':1}


def aggregate_sql():
    weights=[];sums=[]
    for j,(rho,age) in enumerate(VARIANTS):
        exponent='n-rn+1' if age=='pair' else 'last_idx-trading_idx+1'
        weights.append(f'exp(-{rho}*({exponent})) w{j}')
        for tag,value in [('n','1'),('x','x'),('y','clipped'),('xx','x*x'),('xy','x*clipped')]:
            sums.append(f'sum(w{j}*({value})) w{j}_{tag}')
    leap="month(dlycaldt)=2 AND day(dlycaldt)=29"
    ordinary=['count(*) n','sum(x) sx','sum(y) sy','sum(x*x) sxx','sum(x*y) sxy']
    ordinary += [f'sum(CASE WHEN {leap} THEN ({value}) ELSE 0 END) leap_{tag}'
        for tag,value in [('n','1'),('x','x'),('y','y'),('xx','x*x'),('xy','x*y')]]
    return '''WITH valid AS (
      SELECT d.permno,d.dlycaldt,m.month_date,m.trading_idx,m.last_idx,
        CAST(d.dlyret AS DOUBLE)-m.RF y,m.market_excess x
      FROM daily d JOIN requested_ids u ON d.permno=u.permno
      JOIN market m ON d.dlycaldt=m.caldt
      WHERE d.dlyret IS NOT NULL AND d.dlyretmissflg='NA'
       AND d.dlyretdurflg IN ('D1','D2','D3','D4','DU')
    ), ordered AS (
      SELECT *,count(*) OVER(PARTITION BY permno,month_date) n,
       row_number() OVER(PARTITION BY permno,month_date ORDER BY dlycaldt) rn,
       least(greatest(y,least(-2*x,4*x)),greatest(-2*x,4*x)) clipped FROM valid
    ), weighted AS (SELECT *,'''+','.join(weights)+''' FROM ordered)
    SELECT permno,month_date,max(dlycaldt) last_valid,'''+','.join(ordinary+sums)+'''
    FROM weighted GROUP BY permno,month_date ORDER BY month_date,permno'''


def source_files(kind,year):
    folder=io.ROOT/f'data/raw/ps2/historical/{kind}/{year}'
    rec=json.loads((folder/'manifest.json').read_text())
    if rec['status']!='complete':raise ValueError('Incomplete accepted source partition')
    return [str(folder/f['file']) for f in rec['files']]


def checked_product(path,record):
    if not path.is_file() or io.sha256(path)!=record['sha256']:
        raise ValueError('Beta cache checksum mismatch; no overwrite')


def current_session_mask(values,last_market_date):
    return pd.to_datetime(values).eq(pd.Timestamp(last_market_date)).to_numpy()


def run(reuse_moments=None):
    started=time.perf_counter()
    input_hashes={'security_month':io.sha256(io.ROOT/'data/processed/security_month.parquet'),
        'French_daily':io.sha256(FF),'history_code':io.sha256(io.ROOT/'src/ps2/beta_history.py'),
        'builder_code':io.sha256(Path(__file__))}
    for kind in ('stock','index'):
        for year in range(1960,2026):
            input_hashes[f'{kind}_{year}_manifest']=io.sha256(io.ROOT/f'data/raw/ps2/historical/{kind}/{year}/manifest.json')
    fingerprint=hashlib.sha256(json.dumps({'inputs':input_hashes,'config':CONFIG,'sql':aggregate_sql()},sort_keys=True).encode()).hexdigest()
    if reuse_moments is not None:
        old=json.loads((reuse_moments/'completion.json').read_text())
        if old['config']!=json.loads(json.dumps(CONFIG)) or any(v!=input_hashes[k] for k,v in old['inputs'].items() if k!='builder_code'):
            raise ValueError('Cached moments have different inputs or financial configuration')
        expected=hashlib.sha256(json.dumps({'inputs':old['inputs'],'config':CONFIG,'sql':aggregate_sql()},sort_keys=True).encode()).hexdigest()
        if expected!=old['fingerprint']:raise ValueError('Cached moment SQL fingerprint mismatch')
    root=io.ROOT/'data/processed/ps2/beta_panel'/fingerprint[:20]
    root.mkdir(parents=True,exist_ok=True)
    print('BETA_CACHE='+str(root.relative_to(io.ROOT)),flush=True)
    with duckdb.connect() as c:
        c.execute("SET memory_limit='512MB'");c.execute('SET threads=1');c.execute('SET preserve_insertion_order=false')
        c.execute('SET temp_directory=?',[str(root/'temporary')])
        universe=c.execute('''SELECT DISTINCT CAST(permno AS INTEGER) permno FROM read_parquet(?)
          WHERE eligible AND me>0 AND month BETWEEN DATE '1963-06-01' AND DATE '2025-11-01'
          ORDER BY permno''',[str(io.ROOT/'data/processed/security_month.parquet')]).df()
        ids=universe.permno.to_numpy();n_ids=len(ids);c.register('requested_ids',universe)
        index=pd.concat([pd.read_parquet(p) for y in range(1960,2026) for p in source_files('index',y)],ignore_index=True)
        index['caldt']=pd.to_datetime(index.dlycaldt)
        ff=pd.read_parquet(FF,columns=['date','RF'])
        m=index.merge(ff,left_on='caldt',right_on='date',how='left',validate='one_to_one').sort_values('caldt')
        if m.caldt.duplicated().any() or m[['vwretd','RF']].isna().any().any():raise ValueError('Daily market/RF alignment error')
        m['market_excess']=m.vwretd.astype(float)-m.RF
        m['month_date']=m.caldt.dt.to_period('M').dt.to_timestamp()
        m['trading_idx']=np.arange(len(m),dtype=np.int32)
        m['last_idx']=m.groupby('month_date').trading_idx.transform('max')
        c.register('market',m[['caldt','month_date','trading_idx','last_idx','RF','market_excess']])
        month_calendar=m.groupby('month_date').agg(ncalendar=('caldt','size'),last_date=('caldt','max'))
        state=BetaHistory(n_ids)
        for year in range(1960,2026):
            out=root/str(year);out.mkdir(exist_ok=True)
            marker=out/'manifest.json'
            if marker.exists():
                rec=json.loads(marker.read_text())
                if rec['fingerprint']!=fingerprint:raise ValueError('Beta cache fingerprint mismatch')
                for f in rec['products']:checked_product(out/f['file'],f)
                statefile=next(p['file'] for p in rec['products'] if Path(p['file']).name=='state.npz')
                state=BetaHistory.load(out/statefile)
                print('Verified cached beta year',year,flush=True)
                continue
            begin=time.perf_counter()
            attempt=out/('attempt-'+uuid.uuid4().hex);attempt.mkdir(exist_ok=False)
            monthly=attempt/'daily_month_moments.parquet'
            if reuse_moments is not None:
                prior=json.loads((reuse_moments/str(year)/'manifest.json').read_text())
                source=next(p for p in prior['products'] if Path(p['file']).name=='daily_month_moments.parquet')
                priorpath=reuse_moments/str(year)/source['file'];checked_product(priorpath,source)
                with priorpath.open('rb') as src,monthly.open('xb') as dst:shutil.copyfileobj(src,dst,1024*1024)
            else:
                c.read_parquet(source_files('stock',year)).create_view('daily',replace=True)
                c.execute('COPY ('+aggregate_sql()+') TO ? (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 25000)',[str(monthly)])
            frame=pd.read_parquet(monthly)
            saved=[]
            for month in pd.date_range(f'{year}-01-01',f'{year}-12-01',freq='MS'):
                g=frame[frame.month_date.eq(month)]
                where=np.searchsorted(ids,g.permno.to_numpy())
                if not np.array_equal(ids[where],g.permno.to_numpy()):raise ValueError('Unknown beta-cache ID')
                mom=np.zeros((n_ids,10));w=np.zeros((4,n_ids,5));current=np.zeros(n_ids,dtype=bool)
                mom[where]=g[['n','sx','sy','sxx','sxy','leap_n','leap_x','leap_y','leap_xx','leap_xy']].to_numpy(dtype=float)
                for j in range(4):w[j,where]=g[[f'w{j}_{tag}' for tag in ('n','x','y','xx','xy')]].to_numpy(dtype=float)
                cal=month_calendar.loc[month]
                current[where]=current_session_mask(g.last_valid,cal.last_date)
                r=state.advance(month.year*12+month.month-1,mom,w,int(cal.ncalendar),current)
                # Retain observed or historically estimable securities, not all global IDs/months.
                keep=(mom[:,0]>0)|(state.one[:,0]>=20)
                output=pd.DataFrame({k:v[keep] for k,v in r.items()})
                output.insert(0,'month',month);output.insert(0,'permno',ids[keep])
                output['current_valid']=current[keep];output['calendar_days']=int(cal.ncalendar)
                saved.append(output)
            path=attempt/'monthly_betas.parquet'
            with path.open('xb') as f:pd.concat(saved,ignore_index=True).to_parquet(f,index=False,compression='zstd')
            statepath=attempt/'state.npz'
            with statepath.open('xb') as f:state.save(f)
            products=[{'file':str(p.relative_to(out)),'sha256':io.sha256(p),'bytes':p.stat().st_size} for p in (monthly,path,statepath)]
            rec={'fingerprint':fingerprint,'year':year,'config':CONFIG,'products':products,
                 'stock_month_moments':len(frame),'elapsed_seconds':time.perf_counter()-begin,'peak_process':io.process_peak_memory()}
            io.dump_new(marker,rec)
            print(f'Beta year {year}: {len(frame)} moments; {rec["elapsed_seconds"]:.2f}s; peak={rec["peak_process"]["peak_bytes"]}',flush=True)
        completion=root/'completion.json'
        if not completion.exists():io.dump_new(completion,{'status':'complete','fingerprint':fingerprint,'inputs':input_hashes,'config':CONFIG,
            'elapsed_seconds':time.perf_counter()-started,'universe_ids':n_ids})
    print('BETA_PANEL_COMPLETE='+str(root.relative_to(io.ROOT)),flush=True)
    return root


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reuse-moments',type=Path)
    run(p.parse_args().reuse_moments)
