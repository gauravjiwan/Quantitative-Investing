from pathlib import Path
import sys,unittest,tempfile
import numpy as np,pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ps2.factor_history import MonthlyJointHistory
from ps2.factor_forecasts import joint_factor_exposure,FACTORS


class JointHistoryTests(unittest.TestCase):
    def test_joint_window_missingness_and_exact_direct_OLS_benchmark(self):
        rng=np.random.default_rng(270)
        months=pd.period_range('2000-01',periods=80,freq='M')
        f=pd.DataFrame(rng.normal(0,.04,(80,3)),index=months,columns=FACTORS)
        y=pd.Series(.001+f.to_numpy()@np.array([1.2,-.3,.8]),index=months)
        y.iloc[::11]=np.nan
        h=MonthlyJointHistory(1,36,24)
        for j,m in enumerate(months):
            coef,n=h.advance(m.year*12+m.month-1,np.array([y.iloc[j]]),f.iloc[j].to_numpy())
            if j in (36,48,79):
                direct=joint_factor_exposure(y,f,as_of=m,min_observations=24,window_months=36,fit_intercept=True)
                np.testing.assert_allclose(coef[0],np.r_[direct.alpha,direct.beta.to_numpy()],atol=1e-11)
                self.assertEqual(n[0],direct.n_observations)
        np.testing.assert_allclose(coef[0],[.001,1.2,-.3,.8],atol=1e-11)

    def test_rank_insufficient_and_calendar_gap(self):
        h=MonthlyJointHistory(2,36,24)
        for m in range(30):coef,n=h.advance(m,np.array([.01,np.nan]),np.array([.01,.02,.03]))
        self.assertTrue(np.isnan(coef).all())
        self.assertEqual(n.tolist(),[30,0])
        with self.assertRaises(ValueError):h.advance(31,np.array([0.,0.]),np.zeros(3))

    def test_restart_state_matches_uninterrupted_with_future_poisoning(self):
        rng=np.random.default_rng(11);h=MonthlyJointHistory(2,36,24)
        f=rng.normal(0,.04,(50,3));y=.001+f@np.array([1.,.5,-.2])
        for m in range(30):h.advance(m,np.array([y[m],y[m]*2]),f[m])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.npz'
            with path.open('wb') as stream:h.save(stream)
            resumed=MonthlyJointHistory.load(path)
        for m in range(30,50):
            a,n=h.advance(m,np.array([y[m],y[m]*2]),f[m])
            b,k=resumed.advance(m,np.array([y[m],y[m]*2]),f[m])
            np.testing.assert_allclose(a,b,atol=1e-13);np.testing.assert_array_equal(n,k)
        snapshot=a.copy();resumed.advance(50,np.array([100.,-100.]),np.array([.03,.04,-.01]))
        np.testing.assert_array_equal(a,snapshot)


if __name__=='__main__':unittest.main()
