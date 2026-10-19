"""Sequential unchanged extraction commands plus offline gates; preview by default.

Only 1965--2025 are allowed here. No direct database connection or SQL is added.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pandas as pd
import pyarrow.parquet as pq

import ps2_extract_daily as io
from ps2_pilot_b_wrds import KNOWN

FRENCH = io.ROOT / 'data/processed/ps2/french/20261019T032947505510Z/manifest.json'
RESERVE = 1024 ** 3


def commands(first, last):
    if not 1965 <= first <= last <= 2025:
        raise io.ExtractionError('Runner scope must be within 1965--2025.')
    return [(year, kind, [sys.executable, '-B', str(io.ROOT / 'scripts/ps2_extract_daily.py'),
                          '--kind', kind, '--year', str(year), '--chunk-size', '25000', '--execute'])
            for year in range(first, last + 1) for kind in ('stock', 'index')]


def disk_gate(root=io.ROOT):
    free = shutil.disk_usage(root).free
    if free < RESERVE:
        raise io.ExtractionError('Less than 1 GiB disk reserve; stopped before next command.')
    return free


def french_data():
    rec = json.loads(FRENCH.read_text(encoding='utf-8'))
    f = rec['outputs'][0]
    path = io.ROOT / f['file']
    if io.sha256(path) != f['sha256']:
        raise io.ExtractionError('French factor checksum mismatch.')
    frame = pd.read_parquet(path)
    if frame.date.isna().any() or frame.date.duplicated().any():
        raise io.ExtractionError('French null/duplicate dates.')
    return frame


def validate(year, kind, french):
    folder, spec = io.selected_jobs(kind, year=year, executing=True)[0]
    rec = io.verify_complete(folder, spec)
    if rec is None or rec['chunk_size'] != 25000:
        raise io.ExtractionError('Missing or unexpected completed partition.')
    stats = io.Stats(spec)
    for f in rec['files']:
        for chunk in pq.ParquetFile(folder / f['file']).iter_batches(batch_size=25000):
            disk_gate()
            stats.add(chunk.to_pylist())
    v = stats.summary()
    for k in ('rows', 'duplicate_keys', 'null_key_rows', 'order_errors', 'date_counts', 'null_counts', 'flags'):
        if v[k] != rec['validation'][k]:
            raise io.ExtractionError('Independent Parquet reread differs from manifest: ' + k)
    if not v['rows'] or any(v[k] for k in ('duplicate_keys', 'null_key_rows', 'order_errors')):
        raise io.ExtractionError('Empty partition or invalid keys/order.')
    unknown = {k: sorted(set(v['flags'].get(k, {})) - allowed) for k, allowed in KNOWN.items()}
    if any(unknown.values()):
        raise io.ExtractionError('Unrecognized source flag; stop for review, no row removed.')
    if any(d['nonfinite_nonnull'] or d['below_minus_one'] for d in v['return_distributions'].values()):
        raise io.ExtractionError('Unexpected nonfinite or below-minus-one return; no correction.')
    if v['previous_dates']['not_before_current']:
        raise io.ExtractionError('Invalid previous-observation date.')
    fy = french[french.date.dt.year.eq(year)]
    observed = set(v['date_counts'])
    expected = set(fy.date.dt.strftime('%Y-%m-%d'))
    alignment = {'observed_not_in_french': sorted(observed - expected),
                 'french_not_observed': sorted(expected - observed),
                 'French_missing_by_column': {c: int(fy[c].isna().sum()) for c in ('Mkt-RF', 'SMB', 'HML', 'RF')}}
    if alignment['observed_not_in_french'] or alignment['french_not_observed'] or any(alignment['French_missing_by_column'].values()):
        raise io.ExtractionError('French calendar/factor coverage differs; stop for review.')
    if kind == 'index':
        sf, ss = io.selected_jobs('stock', year=year, executing=True)[0]
        stock = io.verify_complete(sf, ss)
        if stock is None or observed != set(stock['validation']['date_counts']):
            raise io.ExtractionError('Stock/index calendar mismatch.')
        if v['null_counts'].get('vwretd', 0):
            raise io.ExtractionError('Missing daily index return.')
    return {'year': year, 'kind': kind, 'validation': v, 'French_alignment': alignment,
            'unknown_flags': unknown, 'checksums_verified': len(rec['files']),
            'independent_reread': True,
            **{k: rec.get(k) for k in ('elapsed_seconds', 'parquet_bytes', 'bytes_per_row',
                                     'rows_per_second', 'process_memory_after')}}


def preservation_snapshot():
    paths = set((io.ROOT / 'src/ps1').rglob('*.py'))
    paths.add(io.ROOT / 'scripts/ps2_extract_daily.py')
    for name in ('pilot', 'pilot_b', 'french'):
        paths.update(p for p in (io.ROOT / 'data/raw/ps2' / name).rglob('*') if p.is_file())
    for kind in ('stock', 'index'):
        for marker in (io.ROOT / 'data/raw/ps2/historical' / kind).glob('*/manifest.json'):
            folder, spec = io.selected_jobs(kind, year=int(marker.parent.name), executing=True)[0]
            rec = io.verify_complete(folder, spec)
            paths.add(marker)
            paths.update(folder / f['file'] for f in rec['files'])
    return {str(p.relative_to(io.ROOT)): io.sha256(p) for p in sorted(paths)}


def verify_preservation(before):
    for name, digest in before.items():
        if io.sha256(io.ROOT / name) != digest:
            raise io.ExtractionError('A protected pre-existing file changed.')


def checkpoint(out, records, year, started, before, final=False):
    verify_preservation(before)
    report = {'status': 'complete' if final else 'checkpoint', 'through_year': year,
              'wall_elapsed_seconds': time.perf_counter() - started,
              'disk_free_bytes': disk_gate(), 'protected_files_unchanged': len(before),
              'partitions': records,
              'totals': {kind: {'rows': sum(r['validation']['rows'] for r in records if r['kind'] == kind),
                               'new_rows': sum(r['validation']['rows'] for r in records if r['kind'] == kind and not r['skipped_existing']),
                               'parquet_bytes': sum(r['parquet_bytes'] for r in records if r['kind'] == kind),
                               'new_extraction_seconds': sum(r['elapsed_seconds'] for r in records if r['kind'] == kind and not r['skipped_existing'])}
                         for kind in ('stock', 'index')}}
    io.dump_new(out / ('final.json' if final else f'checkpoint_{year}.json'), report)
    print(json.dumps({k: report[k] for k in ('status', 'through_year', 'wall_elapsed_seconds', 'disk_free_bytes', 'totals')}), flush=True)


def run(first, last):
    jobs = commands(first, last)
    disk_gate()
    french = french_data()
    before = preservation_snapshot()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = io.ROOT / 'outputs/ps2' / ('stage_1965_2025_' + stamp)
    out.mkdir(exist_ok=False)
    io.dump_new(out / 'preservation_before.json', before)
    io.dump_new(out / 'commands.json', [{'year': y, 'kind': k, 'command': c} for y, k, c in jobs])
    print('REPORT_FOLDER=' + str(out.relative_to(io.ROOT)), flush=True)
    records, started, year, kind = [], time.perf_counter(), None, None
    try:
        for year, kind, command in jobs:
            disk_gate()
            folder, spec = io.selected_jobs(kind, year=year, executing=True)[0]
            existing = io.verify_complete(folder, spec) is not None
            if not existing:
                print(f'START {year} {kind}', flush=True)
                result = subprocess.run(command, cwd=io.ROOT, capture_output=True, text=True, timeout=1800)
                if result.stdout:
                    print(result.stdout.strip(), flush=True)
                if result.returncode:
                    raise io.ExtractionError('Extractor failed; no retry or next query. Return code ' + str(result.returncode))
            row = validate(year, kind, french)
            row['skipped_existing'] = existing
            records.append(row)
            io.dump_new(out / f'{kind}_{year}_validation.json', row)
            print(f'PASS {year} {kind}: rows={row["validation"]["rows"]} bytes={row["parquet_bytes"]} '
                  f'extraction_seconds={row["elapsed_seconds"]:.2f} skipped={existing} '
                  f'run_elapsed={time.perf_counter()-started:.2f}s', flush=True)
            if kind == 'index' and (year - first + 1) % 5 == 0:
                checkpoint(out, records, year, started, before)
        checkpoint(out, records, last, started, before, final=True)
        return 0
    except Exception as exc:
        failure = {'status': 'stopped', 'year': year, 'kind': kind,
                   'error': io.safe_failure(exc), 'completed_validated_partitions': len(records),
                   'wall_elapsed_seconds': time.perf_counter() - started}
        io.dump_new(out / 'failure.json', failure)
        print(json.dumps(failure), flush=True)
        return 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--first-year', type=int, required=True)
    p.add_argument('--last-year', type=int, required=True)
    p.add_argument('--execute', action='store_true')
    a = p.parse_args()
    jobs = commands(a.first_year, a.last_year)
    if not a.execute:
        for y, k, command in jobs:
            print(y, k, subprocess.list2cmdline(command))
        print('PREVIEW ONLY; no authentication, queries or writes.')
        return 0
    return run(a.first_year, a.last_year)


if __name__ == '__main__':
    raise SystemExit(main())
