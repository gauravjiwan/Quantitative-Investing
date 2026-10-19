"""Resume local Q2/Q3 stages after a completed Q1 run; never connects to WRDS."""
import argparse,json,time,sys,unittest
from pathlib import Path
import ps2_extract_daily as io
from ps2_q2_empirical import q2
from ps2_q3_empirical import q3


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--beta-cache',type=Path,required=True)
    p.add_argument('--sic',type=Path,required=True);a=p.parse_args()
    out=a.run.resolve();data=io.ROOT/'data/processed/ps2'/out.name
    if not (out/'q1/manifest.json').exists():raise ValueError('A successful Q1 run is required')
    q2(out,data);q3(a.beta_cache.resolve(),a.sic.resolve(),out,data)
    if not (out/'tests.json').exists():
        started=time.perf_counter()
        with (out/'tests.txt').open('x',encoding='utf-8') as stream:
            result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.discover(str(io.ROOT/'tests')))
        io.dump_new(out/'tests.json',{'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
            'skipped':len(result.skipped),'elapsed_seconds':time.perf_counter()-started,'success':result.wasSuccessful()})
        if not result.wasSuccessful():raise ValueError('Tests failed; see tests.txt')
    from ps2_write_empirical_report import build
    build(out,a.beta_cache.resolve(),a.sic.resolve())


if __name__=='__main__':main()
