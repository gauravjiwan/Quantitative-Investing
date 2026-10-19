from datetime import date
import importlib
from pathlib import Path
import sys,tempfile,unittest

import duckdb
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from ps2.sic import SICError,validate_intervals,join_month_ends
acq=importlib.import_module('ps2_extract_q3_sic')


class SICTests(unittest.TestCase):
    def setup_db(self,rows):
        c=duckdb.connect()
        frame=pd.DataFrame(rows,columns=['permno','permco','secinfostartdt','secinfoenddt','siccd'])
        for col in ('secinfostartdt','secinfoenddt'):frame[col]=pd.to_datetime(frame[col])
        c.register('history',frame)
        return c

    def test_closed_endpoints_and_calendar_month_end_not_label(self):
        with self.setup_db([(1,10,'2000-01-01','2000-01-30',100),(1,10,'2000-01-31','2000-02-29',200)]) as c:
            self.assertEqual(validate_intervals(c)['overlapping_intervals'],0)
            c.register('target_keys',pd.DataFrame({'permno':[1,1], 'observation_month':pd.to_datetime(['2000-01-01','2000-02-01']),
                'as_of_date':pd.to_datetime(['2000-01-31','2000-02-29'])}))
            self.assertEqual(c.execute(join_month_ends(c)+' ORDER BY observation_month').df().siccd.tolist(),[200,200])

    def test_overlaps_and_duplicate_keys_raise(self):
        for rows in [[(1,10,'2000-01-01','2000-02-01',100),(1,10,'2000-02-01','2000-03-01',200)],
                     [(1,10,'2000-01-01','2000-02-01',100)]*2,
                     [(1,10,'2000-02-01','2000-01-01',100)]]:
            with self.setup_db(rows) as c:
                with self.assertRaises(SICError):validate_intervals(c)

    def test_missing_and_invalid_SIC_retained(self):
        with self.setup_db([(1,10,'2000-01-01','2000-12-31',None),(2,20,'2000-01-01','2000-12-31',0)]) as c:
            r=validate_intervals(c)
            self.assertEqual((r['null_SIC'],r['invalid_nonnull_SIC']),(1,1))
            c.register('target_keys',pd.DataFrame({'permno':[1,2,3],'observation_month':pd.to_datetime(['2000-01-01']*3),
              'as_of_date':pd.to_datetime(['2000-01-31']*3)}))
            rows=c.execute(join_month_ends(c)+' ORDER BY permno').df()
            self.assertEqual(len(rows),3)
            self.assertEqual(rows.interval_matched.tolist(),[True,True,False])

    def test_multiple_matches_and_month_start_raise(self):
        with self.setup_db([(1,10,'2000-01-01','2000-12-31',100)]*2) as c:
            targets=pd.DataFrame({'permno':[1],'observation_month':pd.to_datetime(['2000-01-01']),
                'as_of_date':pd.to_datetime(['2000-01-31'])})
            c.register('target_keys',targets)
            with self.assertRaises(SICError):join_month_ends(c)

    def test_open_intervals_remain_open_without_filling_source_dates(self):
        with self.setup_db([(1,10,None,None,100)]) as c:
            r=validate_intervals(c)
            self.assertEqual((r['open_start'],r['open_end']),(1,1))
            c.register('target_keys',pd.DataFrame({'permno':[1],'observation_month':pd.to_datetime(['2000-01-01']),
              'as_of_date':pd.to_datetime(['2000-01-31'])}))
            row=c.execute(join_month_ends(c)).df().iloc[0]
            self.assertEqual(row.siccd,100)
            self.assertTrue(pd.isna(row.secinfostartdt) and pd.isna(row.secinfoenddt))
        with self.setup_db([(1,10,'2000-01-01','2000-12-31',100)]) as c:
            targets=pd.DataFrame({'permno':[1],'observation_month':pd.to_datetime(['2000-01-01']),
                'as_of_date':pd.to_datetime(['2000-01-01'])})
            c.register('target_keys',targets)
            with self.assertRaises(SICError):join_month_ends(c)

    def test_scoped_arrays_and_both_overflow_caps(self):
        b=[(1,date(1963,6,30),date(2025,11,30))]
        s=acq.spec_for(b,acq.TOTAL_CAP-3)
        self.assertEqual(s['parameters']['overflow_limit'],4)
        self.assertEqual(s['parameters']['end_dates'],[date(2025,12,1)])
        self.assertEqual(s['parameters']['permnos'],[1])
        self.assertIn('JOIN requested',s['sql'])
        for bad,used in [(b*2,0),(b,acq.TOTAL_CAP),([],0),([(1,date(1963,1,31),date(2000,1,31))],0)]:
            with self.assertRaises(ValueError):acq.spec_for(bad,used)

    def test_restart_checksum_and_overflow_are_not_complete(self):
        s=acq.spec_for([(1,date(2000,1,31),date(2000,1,31))],acq.TOTAL_CAP-1)
        row=dict(permno=1,permco=10,secinfostartdt=date(2000,1,1),secinfoenddt=date(2000,12,31),siccd=100)
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t)/'good'
            r=acq.save_batch(folder,s,[[row]])
            def no_fetch():raise AssertionError('Restart must not fetch')
            self.assertEqual(acq.save_batch(folder,s,no_fetch)['rows'],1)
            with (folder/r['files'][0]['file']).open('ab') as f:f.write(b'corrupt')
            with self.assertRaises(ValueError):acq.verify(folder,s)
            bad=Path(t)/'overflow'
            with self.assertRaises(ValueError):acq.save_batch(bad,s,[[row,row]])
            self.assertFalse((bad/'manifest.json').exists())
            outside={**row,'permno':2}
            with self.assertRaises(ValueError):acq.save_batch(Path(t)/'outside',s,[[outside]])


if __name__=='__main__':unittest.main()
