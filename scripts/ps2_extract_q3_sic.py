"""Bounded Q3-only SIC acquisition. Preview unless --execute; no daily queries."""
import argparse
from datetime import date,datetime,timezone,timedelta
import hashlib,json
from pathlib import Path
import sys,time,uuid

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import text

import ps2_extract_daily as io
sys.path.insert(0,str(io.ROOT/'src'))
from ps2.sic import validate_intervals,join_month_ends

SQL = '''WITH requested AS (
    SELECT * FROM unnest(CAST(:permnos AS integer[]),
                         CAST(:start_dates AS date[]),
                         CAST(:end_dates AS date[]))
      AS t(permno,start_date,end_date)
)
SELECT h.permno,h.permco,h.secinfostartdt,h.secinfoenddt,h.siccd
FROM crsp.stksecurityinfohist h
JOIN requested r ON h.permno=r.permno
WHERE (h.secinfostartdt<r.end_date OR h.secinfostartdt IS NULL)
  AND (h.secinfoenddt>=r.start_date OR h.secinfoenddt IS NULL)
ORDER BY h.permno,h.secinfostartdt NULLS FIRST,h.secinfoenddt NULLS FIRST
LIMIT :overflow_limit'''
TARGET_SQL = '''SELECT CAST(permno AS INTEGER) permno,CAST(permco AS INTEGER) permco,
 CAST(month AS DATE) observation_month,CAST(last_day(month) AS DATE) as_of_date
 FROM read_parquet(?) WHERE eligible AND me>0
 AND month BETWEEN DATE '1963-06-01' AND DATE '2025-11-01'
 ORDER BY permno,observation_month'''
SCHEMA = pa.schema([('permno',pa.int32()),('permco',pa.int32()),
    ('secinfostartdt',pa.date32()),('secinfoenddt',pa.date32()),('siccd',pa.int32())])
BATCH_IDS,PART_CAP,TOTAL_CAP,CHUNK = 1000,25000,250000,25000


def spec_for(bounds,used):
    if not bounds or len(bounds)>BATCH_IDS or used<0 or used>=TOTAL_CAP:
        raise ValueError('Invalid bounded SIC batch')
    ids=[int(x[0]) for x in bounds]
    if len(set(ids))!=len(ids) or min(ids)<1 or any(not date(1963,6,30)<=x[1]<=x[2]<=date(2025,11,30) for x in bounds):
        raise ValueError('Invalid SIC identifiers/date bounds')
    cap=min(PART_CAP,TOTAL_CAP-used)
    params={'permnos':ids,'start_dates':[x[1] for x in bounds],
            'end_dates':[x[2]+timedelta(days=1) for x in bounds], 'overflow_limit':cap+1}
    spec={'source':'crsp.stksecurityinfohist','sql':SQL,'parameters':params,'accepted_row_cap':cap,
          'chunk_size':CHUNK,'schema':str(SCHEMA)}
    spec['fingerprint']=hashlib.sha256(json.dumps(spec,sort_keys=True,default=str).encode()).hexdigest()
    return spec


def verify(folder,spec):
    marker=folder/'manifest.json'
    if not marker.exists():return None
    r=json.loads(marker.read_text())
    if r['fingerprint']!=spec['fingerprint'] or r['status']!='complete':
        raise ValueError('SIC restart fingerprint/status mismatch')
    count=0
    for f in r['files']:
        p=(folder/f['file']).resolve()
        if not p.is_relative_to(folder.resolve()) or io.sha256(p)!=f['sha256']:
            raise ValueError('SIC checksum/path mismatch')
        n=pq.ParquetFile(p).metadata.num_rows
        if n!=f['rows']:raise ValueError('SIC file row count mismatch')
        count+=n
    if count!=r['rows'] or count>spec['accepted_row_cap']:
        raise ValueError('SIC aggregate row count mismatch')
    return r


def save_batch(folder,spec,chunks):
    existing=verify(folder,spec)
    if existing is not None:return existing
    folder.mkdir(parents=True,exist_ok=True)
    attempt=folder/('attempt-'+uuid.uuid4().hex)
    attempt.mkdir(exist_ok=False)
    io.dump_new(attempt/'request.json',{'requested_utc':io.utc(),'request':spec})
    bounds={p:(a,b) for p,a,b in zip(spec['parameters']['permnos'],
        spec['parameters']['start_dates'],spec['parameters']['end_dates'])}
    count,files=0,[]
    for number,rows in enumerate(chunks):
        if len(rows)>CHUNK:raise ValueError('SIC chunk overflow')
        count+=len(rows)
        if count>spec['accepted_row_cap']:raise ValueError('SIC overflow; truncated data not complete')
        for r in rows:
            if r['permno'] not in bounds:raise ValueError('SIC row outside approved stock universe')
            lo,hi=bounds[r['permno']]
            if ((r['secinfostartdt'] is not None and r['secinfostartdt']>=hi) or
                (r['secinfoenddt'] is not None and r['secinfoenddt']<lo)):
                raise ValueError('SIC row outside requested interval overlap')
        if not rows:continue
        p=attempt/f'part-{number:05d}.parquet'
        with p.open('xb') as f:pq.write_table(pa.Table.from_pylist(rows,schema=SCHEMA),f,compression='zstd')
        files.append({'file':str(p.relative_to(folder)),'rows':len(rows),
                      'bytes':p.stat().st_size,'sha256':io.sha256(p)})
    rec={'status':'complete','fingerprint':spec['fingerprint'],'request':spec,
         'completed_utc':io.utc(),'rows':count,'files':files}
    io.dump_new(folder/'manifest.json',rec)
    return verify(folder,spec)


def run(execute,offline=False):
    source=io.ROOT/'data/processed/security_month.parquet'
    started=time.perf_counter()
    with duckdb.connect() as c:
        c.execute("SET memory_limit='256MB'")
        c.execute('SET threads=1')
        c.execute('SET preserve_insertion_order=false')
        c.execute('CREATE VIEW target_keys AS '+TARGET_SQL.replace('read_parquet(?)',"read_parquet('"+source.as_posix()+"')"))
        bounds=c.execute('SELECT permno,min(as_of_date),max(as_of_date) FROM target_keys GROUP BY permno ORDER BY permno').fetchall()
        count=c.execute('SELECT count(*) FROM target_keys').fetchone()[0]
        print(SQL,flush=True)
        print(json.dumps({'stock_ids':len(bounds),'stock_month_origins':count,'batches':(len(bounds)+BATCH_IDS-1)//BATCH_IDS,
          'max_intervals':TOTAL_CAP,'max_per_batch':PART_CAP,'chunk_size':CHUNK,
          'first_origin':'1963-06-30','last_origin':'2025-11-30',
          'date_bounds':'Each requested PERMNO uses min/max actual origin month-end; exclusive end=max+1 day.'}),flush=True)
        if not execute:return 0
        source_digest=io.sha256(source)
        digest=hashlib.sha256((source_digest+SQL+TARGET_SQL+str((BATCH_IDS,PART_CAP,TOTAL_CAP,CHUNK))).encode()).hexdigest()
        raw=io.ROOT/'data/raw/ps2/sic_q3'/digest[:20]
        raw.mkdir(parents=True,exist_ok=True)
        c.execute('SET temp_directory=?',[str(raw/'local_validation_temp')])
        if (raw/'completion.json').exists():
            done=json.loads((raw/'completion.json').read_text())
            prior=0
            for number,start in enumerate(range(0,len(bounds),BATCH_IDS)):
                spec=spec_for(bounds[start:start+BATCH_IDS],prior)
                rec=verify(raw/f'batch-{number:04d}',spec)
                if rec is None:raise ValueError('Completed SIC snapshot lacks a source batch')
                prior+=rec['rows']
            for f in done['products']:
                if io.sha256(io.ROOT/f['file'])!=f['sha256']:raise ValueError('Completed SIC product checksum mismatch')
            print('Verified existing SIC completion; no query or overwrite.',flush=True)
            return 0
        used,parts=0,[]
        for number,start in enumerate(range(0,len(bounds),BATCH_IDS)):
            spec=spec_for(bounds[start:start+BATCH_IDS],used)
            folder=raw/f'batch-{number:04d}'
            rec=verify(folder,spec)
            if rec is None:
                if offline:raise ValueError('Offline validation requires every cached SIC batch')
                with io.connection() as conn:
                    rec=save_batch(folder,spec,io.batches(conn,spec,CHUNK))
            used+=rec['rows'];parts.append((folder,rec))
            print(f'SIC batch {number+1}: {rec["rows"]} intervals; combined={used}',flush=True)
        files=[str(folder/f['file']) for folder,rec in parts for f in rec['files']]
        if not files:raise ValueError('No historical SIC intervals returned')
        c.read_parquet(files).create_view('history')
        intervals=validate_intervals(c)
        joined=join_month_ends(c)
        c.execute('CREATE VIEW joined_sic AS '+joined)
        coverage=c.execute('''SELECT count(*),count(*) FILTER(WHERE NOT interval_matched),
          count(*) FILTER(WHERE siccd IS NULL),count(*) FILTER(WHERE siccd<100 OR siccd>9999),
          count(*) FILTER(WHERE interval_matched AND permco<>sic_permco)
          FROM joined_sic''').fetchone()
        if io.sha256(source)!=source_digest:raise ValueError('PS1 input changed during SIC extraction')
        report={'intervals':intervals,'origin_rows':coverage[0],'no_interval':coverage[1],
                'null_SIC':coverage[2],'invalid_nonnull_SIC':coverage[3],'permco_disagreements':coverage[4],
                'multiple_matches':0,'month_end_rule':'Closed intervals at last_day(observation_month), not PS1 month-start labels.',
                'missing_policy':'Retain unmatched/null/invalid SIC rows; no carry-forward, backfill or Other imputation.',
                'source_input_sha256':source_digest,'elapsed_seconds':time.perf_counter()-started}
        if coverage[0]!=count or coverage[4]:raise ValueError('SIC join count/company mismatch; stop for review')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        out=io.ROOT/'data/processed/ps2/sic_q3'/stamp
        out.mkdir(parents=True,exist_ok=False)
        result=out/'stock_month_sic.parquet'
        c.execute('COPY (SELECT * FROM joined_sic ORDER BY permno,observation_month) TO ? (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 25000)',[str(result)])
        products=[{'file':str(result.relative_to(io.ROOT)),'sha256':io.sha256(result),'rows':count}]
        io.dump_new(out/'manifest.json',{'source_root':str(raw.relative_to(io.ROOT)),'products':products,'validation':report})
        products.append({'file':str((out/'manifest.json').relative_to(io.ROOT)),'sha256':io.sha256(out/'manifest.json')})
        io.dump_new(raw/'completion.json',{'status':'complete','products':products,'validation':report})
        io.dump_new(io.ROOT/'outputs/ps2'/f'sic_q3_validation_{stamp}.json',report)
        print(json.dumps(report,indent=2),flush=True)
        print('Processed SIC:',result.relative_to(io.ROOT),flush=True)
    return 0


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true')
    p.add_argument('--validate-only',action='store_true',help='Use cached batches only; no connection')
    a=p.parse_args()
    try:raise SystemExit(run(a.execute or a.validate_only,a.validate_only))
    except Exception as e:
        print('STOPPED:',io.safe_failure(e),flush=True)
        raise SystemExit(1)
