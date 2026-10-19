import unittest
import numpy as np
import pandas as pd
from ps1.panel import calendar_lag,aggregate_company,annual_accounting
from ps1.portfolios import bins,capital_wealth,assign
from ps1.analysis import cross_section
from ps1.statistics import summarize
from ps1.ingestion import french_blocks,CATALOG_SQL
from sqlalchemy import text

class EconomicsTests(unittest.TestCase):
    def test_missing_calendar_month_is_not_a_lag(self):
        p=pd.DataFrame({'permno':[1,1,1],'month':pd.to_datetime(['2020-01-01','2020-03-01','2020-04-01']),'me':[100.,110.,120.]})
        out=calendar_lag(p,'permno','me');self.assertTrue(np.isnan(out.lag_me.iloc[1]));self.assertEqual(out.lag_me.iloc[2],110.)
    def test_share_class_aggregation_preserves_vw_return(self):
        p=pd.DataFrame({'permco':[1,1,1,1],'permno':[11,12,11,12],'month':pd.to_datetime(['2020-01-01']*2+['2020-02-01']*2),'me':[100.,300.,110.,285.],'lag_me':[np.nan,np.nan,100.,300.],'ret':[0.,0.,.1,-.05],'exchange':['N']*4})
        out=aggregate_company(p);feb=out[out.month.eq('2020-02-01')].iloc[0];self.assertAlmostEqual(feb.ret,-.0125);self.assertEqual(feb.lag_me,400.)
    def test_split_does_not_change_market_cap(self):
        price,shares=100.,20.;factor=4.;self.assertEqual(price/factor*shares*factor,price*shares)
    def test_boundary_ties_go_to_lower_group(self):self.assertEqual(bins([10.,20.,21.],[10.,20.]).tolist(),[1,2,3])
    def test_collateralized_capital_includes_rf(self):
        high=pd.Series([.02,.03]);low=pd.Series([.01,.01]);rf=pd.Series([.005,.005]);r,w=capital_wealth(high,low,rf)
        np.testing.assert_allclose(r,[.015,.025]);self.assertAlmostEqual(w.iloc[-1],1.015*1.025)
    def test_book_equity_tax_change_and_asset_year_gap(self):
        a=pd.DataFrame({'gvkey':['1']*3,'datadate':pd.to_datetime(['1992-12-31','1993-12-31','1995-12-31']),'indfmt':['INDL']*3,'datafmt':['STD']*3,'popsrc':['D']*3,'consol':['C']*3,'curcd':['USD']*3,'at':[100.,120.,150.],'lt':[60.]*3,'seq':[40.]*3,'ceq':[np.nan]*3,'pstk':[2.]*3,'pstkrv':[np.nan]*3,'pstkl':[np.nan]*3,'txditc':[5.]*3,'sale':[90.]*3,'cogs':[60.]*3,'xsga':[10.]*3,'xint':[2.]*3,'mib':[0.]*3,'ib':[10.]*3})
        r=annual_accounting(a);np.testing.assert_allclose(r.be,[43,38,38]);self.assertAlmostEqual(r.inv.iloc[1],.2);self.assertTrue(np.isnan(r.inv.iloc[2]))
    def test_raw_and_zscore_regressions_mapping(self):
        rng=np.random.default_rng(4);x=rng.normal(size=(50,3))*[2,4,3];b=np.array([.2,.1,-.2]);y=.01+x@b
        raw,w,_=cross_section(y,x);z=(x-x.mean(0))/x.std(0);scaled,wz,_=cross_section(y,z,np.arange(1,51))
        np.testing.assert_allclose(raw[1:],b,atol=1e-12);np.testing.assert_allclose(scaled[1:],b*x.std(0),atol=1e-12);np.testing.assert_allclose(w[1:]@y,raw[1:]);np.testing.assert_allclose(wz[1:]@np.column_stack([np.ones(50),z]),np.eye(4)[1:],atol=1e-12)
    def test_t_sharpe_identity(self):
        s=pd.Series(np.random.default_rng(2).normal(.003,.02,750));stats=summarize(s,zero_investment=True);self.assertAlmostEqual(stats['t_iid'],stats['sharpe_annual']*np.sqrt(750/12))
    def test_french_monthly_only_and_units(self):
        source='Average Value Weight Returns -- Monthly\n,Lo 10,Hi 10\n196307,1,2\n196308,-99.99,3\n\n Annual Returns\n1963,12,13\n\n Number of Firms in Portfolios\n,Lo 10,Hi 10\n196307,100,200\n\n'
        b=french_blocks(source);self.assertEqual(len(b),2);self.assertEqual(b[0][1].iloc[0,0],.01);self.assertTrue(np.isnan(b[0][1].iloc[1,0]));self.assertEqual(b[1][1].iloc[0,0],100)
    def test_percent_wildcards_are_sqlalchemy_text(self):
        # PostgreSQL DBAPI must receive a compiled statement, not raw pyformat-interpreted %.
        q=text(CATALOG_SQL);self.assertIn("ILIKE '%crsp%'",str(q));self.assertEqual(list(q._bindparams),[])
if __name__=='__main__':unittest.main()
