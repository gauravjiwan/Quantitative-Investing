"""Configuration, immutable snapshots, storage, and strict data gates."""
from __future__ import annotations
import hashlib, json, os, re, tomllib
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import duckdb

_SOURCE_ROOT = Path(__file__).resolve().parents[2]
_WORKING_ROOT = Path.cwd()
ROOT = Path(os.environ['PS1_ROOT']).expanduser().resolve() if 'PS1_ROOT' in os.environ else (
    _WORKING_ROOT if (_WORKING_ROOT/'config/project.toml').is_file() else _SOURCE_ROOT
)
class DataError(RuntimeError): pass

def config(root=ROOT):
    with (Path(root)/'config/project.toml').open('rb') as f: return tomllib.load(f)

def mapping(root=ROOT):
    with (Path(root)/'config/field_map.toml').open('rb') as f: return tomllib.load(f)

def months(root=ROOT):
    s=config(root)['sample']; return pd.date_range(s['return_start'],s['return_end'],freq='MS')

def dates(s): return pd.to_datetime(s,errors='coerce').dt.to_period('M').dt.to_timestamp()

def unique(df,keys,label):
    if df[keys].isna().any().any() or df.duplicated(keys).any():
        raise DataError(f'{label}: null or duplicate key {keys}')

def coverage(df,root=ROOT,label='returns',column='month'):
    expected=months(root); actual=pd.DatetimeIndex(df[column].drop_duplicates()).sort_values()
    if not actual.equals(expected):
        raise DataError(f'{label}: missing={expected.difference(actual).strftime("%Y-%m").tolist()}; unexpected={actual.difference(expected).strftime("%Y-%m").tolist()}')

def save(df,name,root=ROOT):
    root=Path(root); p=root/'data/processed'/f'{name}.parquet'; p.parent.mkdir(parents=True,exist_ok=True)
    df.to_parquet(p,index=False)
    with duckdb.connect(str(root/config(root)['storage']['duckdb_path'])) as db:
        db.register('incoming',df); db.execute(f'CREATE OR REPLACE TABLE {identifier(name)} AS SELECT * FROM incoming')
    return p

def read(name,root=ROOT):
    p=Path(root)/'data/processed'/f'{name}.parquet'
    if not p.exists(): raise DataError(f'Missing {p}; run its prerequisite stage first.')
    return pd.read_parquet(p)

def table(df,name,root=ROOT):
    p=Path(root)/'outputs/tables'/f'{name}.csv'; p.parent.mkdir(parents=True,exist_ok=True); df.to_csv(p,index=False)

def identifier(value):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*(\.[A-Za-z_][A-Za-z_0-9]*)?',value):
        raise DataError(f'Invalid SQL identifier: {value!r}')
    return '.'.join('"'+x+'"' for x in value.split('.'))

def snapshot(df,path,source,query='',root=ROOT):
    path=Path(path).resolve(); root=Path(root).resolve(); path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists(): raise DataError(f'Refusing to replace raw snapshot {path}')
    df.to_parquet(path,index=False)
    manifest={'file':str(path.relative_to(root)),'source':source,'query':query,'rows':len(df),'retrieved_utc':datetime.now(timezone.utc).isoformat(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    for c in ['month','datadate']:
        if c in df: manifest[c+'_min']=str(df[c].min()); manifest[c+'_max']=str(df[c].max())
    path.with_suffix('.json').write_text(json.dumps(manifest,indent=2)+'\n')

def raw(kind,root=ROOT):
    paths=sorted((Path(root)/'data/raw'/kind).glob('*.parquet'))
    if not paths: raise DataError(f'No raw {kind} snapshots. Run extract or import an approved WRDS export.')
    for p in paths:
        m=p.with_suffix('.json')
        if not m.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=json.loads(m.read_text())['sha256']:
            raise DataError(f'Raw snapshot manifest/checksum mismatch: {p}')
    return pd.concat([pd.read_parquet(p) for p in paths],ignore_index=True)
