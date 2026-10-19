from pathlib import Path
import sys,unittest
import numpy as np,pandas as pd
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).resolve().parents[1]/'src')]
from ps2_q3_empirical import mean_hac
from ps2.residualization import q3_design,wls,q3_fwl,CHARACTERISTICS
from ps2.french import classify_sic


class EmpiricalIntegrationTests(unittest.TestCase):
    def test_signed_monthly_coefficient_HAC_independent_benchmark(self):
        import statsmodels.api as sm
        x=pd.Series(np.sin(np.arange(50))+np.arange(50)*.002,index=pd.date_range('2000-01-01',periods=50,freq='MS'))
        result=mean_hac(x)
        independent=sm.OLS(x.to_numpy(),np.ones((len(x),1))).fit(cov_type='HAC',cov_kwds={'maxlags':12,'use_correction':False})
        self.assertAlmostEqual(result['mean'],independent.params[0],places=13)
        self.assertAlmostEqual(result['standard_error'],independent.bse[0],places=13)

    def test_classified_cross_section_affine_units_and_joint_FWL(self):
        rng=np.random.default_rng(94);n=120;idx=pd.Index(np.arange(n),name='permno')
        series=lambda x:pd.Series(x,index=idx)
        ranges=pd.DataFrame({'sic_start':[100,200],'sic_end':[199,299],'ff12':[1,2]})
        industry=classify_sic(series(np.resize([150,250,500],n)),ranges).ff12
        d=q3_design(series(np.exp(rng.normal(5,1,n))),series(np.exp(rng.normal(0,.5,n))),series(rng.normal(0,.2,n)),series(rng.normal(0,.1,n)),series(rng.normal(1,.2,n)),industry,standardization='equal')
        beta=np.linspace(-.003,.005,d.matrix.shape[1]);y=d.matrix@beta
        fit=wls(y,d.matrix,d.objective_weights)
        np.testing.assert_allclose(fit.coefficients,beta,atol=1e-13)
        affine=d.matrix.copy();affine.loc[:,list(CHARACTERISTICS)]=2*affine.loc[:,list(CHARACTERISTICS)]+3
        alternative=wls(y,affine,d.objective_weights)
        np.testing.assert_allclose(fit.fitted,alternative.fitted,atol=1e-13)
        result=q3_fwl(y,d.matrix.log_bm,d.matrix.drop(columns='log_bm'),d.objective_weights)
        self.assertAlmostEqual(result.full.coefficients['__signal__'],fit.coefficients.log_bm,places=13)
        self.assertAlmostEqual(result.slope_difference,0.,places=13)
