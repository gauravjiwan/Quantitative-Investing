from pathlib import Path
import sys,tempfile,unittest
import importlib,duckdb
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ps2.beta_history import BetaHistory,VARIANTS,WELCH_COLUMNS,slope
from ps2.betas import ols_market_beta
from ps2.welch import historical_welch_beta,slope_winsorize
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))


def moments(x,y,w=None):
    w=np.ones(len(x)) if w is None else w
    return np.array([w.sum(),w@x,w@y,w@(x*x),w@(x*y)])


class HistoryTests(unittest.TestCase):
    def test_Parquet_date32_roundtrip_current_session(self):
        from datetime import date
        builder=importlib.import_module('ps2_build_beta_panel')
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'dates.parquet'
            pd.DataFrame({'last_valid':[date(2025,11,28),date(2025,11,27),None]}).to_parquet(p,index=False)
            frame=pd.read_parquet(p)
            np.testing.assert_equal(builder.current_session_mask(frame.last_valid,pd.Timestamp('2025-11-28')),[True,False,False])

    def test_actual_aggregation_SQL_units_flags_and_monthly_weights(self):
        builder=importlib.import_module('ps2_build_beta_panel')
        dates=pd.bdate_range('2020-01-02',periods=7)
        x=np.array([.01,-.02,0,.03,.02,.01,.01]);y=np.array([.4,-.3,.02,.02,.8,.9,np.nan])
        market=pd.DataFrame({'caldt':dates,'month_date':pd.Timestamp('2020-01-01'),
            'RF':.001,'market_excess':x,'trading_idx':np.arange(7),'last_idx':6})
        daily=pd.DataFrame({'permno':1,'dlycaldt':dates,'dlyret':y+.001,
            'dlyretmissflg':['NA']*4+['MV','NA','MP'],
            'dlyretdurflg':['D1','D1','D3','D1','D1','P1','MR']})
        daily=pd.concat([daily,daily.assign(permno=2)],ignore_index=True)
        with duckdb.connect() as c:
            c.register('daily',daily);c.register('market',market)
            c.register('requested_ids',pd.DataFrame({'permno':[1]}))
            r=c.execute(builder.aggregate_sql()).df().iloc[0]
        self.assertEqual(r.n,4)
        self.assertEqual(r.last_valid,dates[3])
        np.testing.assert_allclose(r[['n','sx','sy','sxx','sxy']].to_numpy(dtype=float),moments(x[:4],y[:4]))
        for j,(rho,basis) in enumerate(VARIANTS):
            age=np.arange(4,0,-1) if basis=='pair' else 7-np.arange(4)
            expected=moments(x[:4],slope_winsorize(y[:4],x[:4]),np.exp(-rho*age))
            actual=r[[f'w{j}_{z}' for z in ('n','x','y','xx','xy')]].to_numpy(dtype=float)
            np.testing.assert_allclose(actual,expected,atol=1e-14)

    def test_streaming_matches_daily_ols_and_all_welch_variants_with_leap_boundary(self):
        rng=np.random.default_rng(725)
        cal=pd.bdate_range('2013-01-01','2019-03-31')
        x=pd.Series(rng.normal(.0003,.012,len(cal)),index=cal)
        y=1.4*x+.0001+pd.Series(rng.normal(0,.007,len(cal)),index=cal)
        y.iloc[::17]=np.nan
        state=BetaHistory(1)
        checks=0
        for month in pd.period_range('2013-01','2019-03',freq='M'):
            days=cal[cal.to_period('M')==month]
            valid=y.reindex(days).notna().to_numpy()
            xx=x.reindex(days).to_numpy()[valid];yy=y.reindex(days).to_numpy()[valid]
            clipped=slope_winsorize(yy,xx)
            m=np.zeros((1,10));m[0,:5]=moments(xx,yy)
            leap=(days[valid].month==2)&(days[valid].day==29)
            m[0,5:]=moments(xx[leap],yy[leap])
            w=np.zeros((4,1,5))
            for j,(rho,basis) in enumerate(VARIANTS):
                age=np.arange(len(xx),0,-1) if basis=='pair' else len(days)-np.flatnonzero(valid)
                w[j,0]=moments(xx,clipped,np.exp(-rho*age))
            result=state.advance(month.year*12+month.month-1,m,w,len(days),np.array([valid[-1]]))
            if month in pd.PeriodIndex(['2017-02','2018-03','2019-02','2019-03'],freq='M'):
                for name,years in [('ols_1y',1),('ols_3y',3),('ols_expanding_1960',None)]:
                    direct=ols_market_beta(y,x,as_of=month.end_time.normalize(),min_observations=20,years=years)
                    self.assertAlmostEqual(result[name][0],direct.beta,places=11)
                for j,name in enumerate(WELCH_COLUMNS):
                    rho,basis=VARIANTS[j]
                    direct=historical_welch_beta(y,x,as_of=month.end_time.normalize(),trading_calendar=cal,
                       min_observations=20,require_current_return=True,
                       age_basis='valid_pairs' if basis=='pair' else 'market_calendar',rho=rho)
                    np.testing.assert_allclose(result[name][0],direct.fit.beta,rtol=1e-11,atol=1e-11,equal_nan=True)
                checks+=1
        self.assertEqual(checks,4)

    def test_missing_current_return_and_monthly_target_minimum(self):
        s=BetaHistory(1)
        x=np.linspace(-.02,.02,21);y=2*x+.0003
        m=np.zeros((1,10));m[0,:5]=moments(x,y)
        w=np.stack([moments(x,slope_winsorize(y,x),np.exp(-rho*np.arange(21,0,-1))) for rho,basis in VARIANTS])[:,None,:]
        r=s.advance(2000*12,m,w,21,np.array([False]))
        self.assertAlmostEqual(r['ols_1y'][0],2)
        self.assertAlmostEqual(r['realized_beta'][0],2)
        self.assertTrue(np.isnan(r['welch_256_cal'][0]))
        m[0,:5]=moments(x[:9],y[:9]);w[:]=0
        r=s.advance(2000*12+1,m,w,21,np.array([False]))
        self.assertTrue(np.isnan(r['realized_beta'][0]))

    def test_state_restart_and_past_outputs_are_not_mutated(self):
        s=BetaHistory(1)
        x=np.linspace(-.02,.02,21);y=1.2*x
        m=np.zeros((1,10));m[0,:5]=moments(x,y)
        w=np.zeros((4,1,5))
        r=s.advance(2000*12,m,w,21,np.array([False]))
        n=r['n_expanding'].copy()
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'state.npz'
            with p.open('xb') as f:s.save(f)
            q=BetaHistory.load(p)
            a=s.advance(2000*12+1,m,w,21,np.array([False]))
            b=q.advance(2000*12+1,m,w,21,np.array([False]))
            for k in a:np.testing.assert_allclose(a[k],b[k],equal_nan=True)
        np.testing.assert_equal(r['n_expanding'],n)
        with self.assertRaises(ValueError):s.advance(2000*12+3,m,w,21,np.array([False]))

    def test_known_slope_and_zero_variance(self):
        x=np.arange(30)/100;y=.02+1.5*x
        self.assertAlmostEqual(slope(moments(x,y)[None,:])[0],1.5)
        self.assertTrue(np.isnan(slope(moments(np.ones(30),y)[None,:])[0]))


if __name__=='__main__':unittest.main()
