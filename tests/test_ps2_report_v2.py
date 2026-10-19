from pathlib import Path
import sys,unittest
import numpy as np,pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from ps2_report_v2 import hac_mean,matched_losses,fmt,table_layout


class ReportV2Tests(unittest.TestCase):
    def test_undefined_statistic_is_not_zero(self):
        self.assertEqual(fmt(np.nan),'undefined')
        self.assertEqual(fmt(0.,3),'0.000')

    def test_signed_coefficient_HAC_independent_statsmodels(self):
        import statsmodels.api as sm
        x=pd.Series(np.sin(np.arange(60))*.01-.003,index=pd.date_range('2000-01-01',periods=60,freq='MS'))
        summary=hac_mean(x)
        fit=sm.OLS(x.to_numpy(),np.ones((len(x),1))).fit(cov_type='HAC',cov_kwds={'maxlags':12,'use_correction':False})
        self.assertAlmostEqual(summary['mean'],fit.params[0],places=13)
        self.assertAlmostEqual(summary['standard_error'],fit.bse[0],places=13)
        self.assertAlmostEqual(summary['t_statistic'],fit.tvalues[0],places=11)

    def test_matched_loss_keys_and_calendar(self):
        a=pd.DataFrame({'target_month':pd.date_range('2000-01-01',periods=4,freq='MS'),'n':[3,5,2,4]})
        matched_losses(a,a.copy())
        b=a.copy();b.loc[1,'n']=3
        with self.assertRaises(ValueError):matched_losses(a,b)
        with self.assertRaises(ValueError):matched_losses(a.drop(index=1),a.drop(index=1))

    def test_known_trailing_average_is_lagged(self):
        x=pd.Series(np.arange(50,dtype=float));mean=x.rolling(36,min_periods=36).mean()
        self.assertTrue(mean.iloc[:35].isna().all());self.assertEqual(mean.iloc[35],17.5)
        x.iloc[49]=1e9;changed=x.rolling(36,min_periods=36).mean()
        np.testing.assert_array_equal(mean.iloc[:49],changed.iloc[:49])

    def test_table_width_and_rejection(self):
        t=table_layout(['Model','Number'],[['Example','0.12345']])
        self.assertAlmostEqual(sum(t._argW),520.)
        with self.assertRaises(ValueError):table_layout(['Label','Number'],[['a'*200,'0']])


if __name__=='__main__':unittest.main()
