import contextlib
from datetime import date
from decimal import Decimal
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
runner = importlib.import_module('ps2_run_approved_years')


class RunnerTests(unittest.TestCase):
    def test_exact_sequential_scope_and_no_sic(self):
        jobs = runner.commands(1965, 2025)
        self.assertEqual(len(jobs), 122)
        self.assertEqual([(y, k) for y, k, c in jobs[:4]],
                         [(1965, 'stock'), (1965, 'index'), (1966, 'stock'), (1966, 'index')])
        self.assertEqual(jobs[-1][:2], (2025, 'index'))
        for y, k, c in jobs:
            self.assertEqual(c[-7:], ['--kind', k, '--year', str(y), '--chunk-size', '25000', '--execute'])
            self.assertNotIn('sic', c)
        for first, last in [(1964, 2025), (1965, 2026), (2025, 1965)]:
            with self.assertRaises(runner.io.ExtractionError):
                runner.commands(first, last)

    def test_disk_reserve(self):
        with patch.object(runner.shutil, 'disk_usage', return_value=Mock(free=runner.RESERVE - 1)):
            with self.assertRaises(runner.io.ExtractionError):
                runner.disk_gate()
        with patch.object(runner.shutil, 'disk_usage', return_value=Mock(free=runner.RESERVE)):
            self.assertEqual(runner.disk_gate(), runner.RESERVE)

    def setup_run(self, stack, root):
        (root / 'outputs/ps2').mkdir(parents=True)
        stack.enter_context(patch.object(runner.io, 'ROOT', root))
        stack.enter_context(patch.object(runner, 'disk_gate', return_value=10**10))
        stack.enter_context(patch.object(runner, 'french_data', return_value=None))
        stack.enter_context(patch.object(runner, 'preservation_snapshot', return_value={}))
        stack.enter_context(patch.object(runner, 'checkpoint'))
        stack.enter_context(contextlib.redirect_stdout(__import__('io').StringIO()))

    def test_verified_existing_2020_never_starts_child(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.ExitStack() as stack:
            self.setup_run(stack, Path(temp))
            stack.enter_context(patch.object(runner.io, 'verify_complete', return_value={'status': 'complete'}))
            stack.enter_context(patch.object(runner, 'validate', return_value={
                'validation': {'rows': 1}, 'parquet_bytes': 1, 'elapsed_seconds': 1.0}))
            child = stack.enter_context(patch.object(runner.subprocess, 'run'))
            self.assertEqual(runner.run(2020, 2020), 0)
            child.assert_not_called()
            self.assertEqual(runner.validate.call_count, 2)

    def test_extractor_failure_stops_before_next_command(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.ExitStack() as stack:
            self.setup_run(stack, Path(temp))
            stack.enter_context(patch.object(runner.io, 'verify_complete', return_value=None))
            child = stack.enter_context(patch.object(runner.subprocess, 'run', return_value=Mock(stdout='', returncode=1)))
            gate = stack.enter_context(patch.object(runner, 'validate'))
            self.assertEqual(runner.run(1965, 1966), 1)
            self.assertEqual(child.call_count, 1)
            gate.assert_not_called()

    def test_validation_failure_stops_before_next_query(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.ExitStack() as stack:
            self.setup_run(stack, Path(temp))
            stack.enter_context(patch.object(runner.io, 'verify_complete', return_value=None))
            child = stack.enter_context(patch.object(runner.subprocess, 'run', return_value=Mock(stdout='', returncode=0)))
            stack.enter_context(patch.object(runner, 'validate', side_effect=runner.io.ExtractionError('Synthetic failure')))
            self.assertEqual(runner.run(1965, 1966), 1)
            self.assertEqual(child.call_count, 1)

    def test_real_bounded_reread_and_calendar_gate(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(runner.io, 'ROOT', Path(temp)), patch.object(runner, 'disk_gate'):
            french = pd.DataFrame({'date': pd.to_datetime(['1965-01-04']),
                                   **{c: [0.] for c in ('Mkt-RF', 'SMB', 'HML', 'RF')}})
            folder, spec = runner.io.selected_jobs('stock', year=1965, executing=True)[0]
            row = dict(permno=1, dlycaldt=date(1965, 1, 4), dlyret=Decimal('0'), dlyretx=Decimal('0'),
                       dlyretmissflg='NA', dlyretdurflg='D1', dlydelflg='N', dlyprevdt=date(1964, 12, 31))
            runner.io.save_partition(folder, spec, [[row]])
            rec = runner.validate(1965, 'stock', french)
            self.assertEqual(rec['validation']['rows'], 1)
            self.assertTrue(rec['independent_reread'])
            self.assertEqual(rec['checksums_verified'], 1)
            french.loc[1] = [pd.Timestamp('1965-01-05'), 0., 0., 0., 0.]
            with self.assertRaises(runner.io.ExtractionError):
                runner.validate(1965, 'stock', french)
            file = next(folder.rglob('*.parquet'))
            with file.open('ab') as stream:
                stream.write(b'corrupt')
            with self.assertRaises(runner.io.ExtractionError):
                runner.validate(1965, 'stock', french.iloc[:1])


if __name__ == '__main__':
    unittest.main()
