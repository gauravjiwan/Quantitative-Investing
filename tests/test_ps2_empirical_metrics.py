from pathlib import Path
import sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ps2.empirical_metrics import pooled_calibration,frozen_shrinkage


class MetricTests(unittest.TestCase):
    def test_pooled_known_intercept_slope_and_R_squared(self):
        x=np.array([-.2,.5,1.,2.]);y=2+3*x
        r=pooled_calibration(len(x),x.sum(),y.sum(),x@x,x@y,y@y)
        self.assertAlmostEqual(r['intercept'],2);self.assertAlmostEqual(r['slope'],3)
        self.assertAlmostEqual(r['r_squared'],1)

    def test_constant_forecast_and_preselected_constrained_shrinkage(self):
        r=pooled_calibration(3,3,6,3,6,14)
        self.assertTrue(np.isnan(r['slope']));self.assertEqual(r['r_squared'],0)
        self.assertAlmostEqual(frozen_shrinkage([1,2],[2,4]),.5)
        self.assertEqual(frozen_shrinkage([-1],[2]),0)
        self.assertEqual(frozen_shrinkage([4],[2]),1)
        with self.assertRaises(ValueError):frozen_shrinkage([],[])


if __name__=='__main__':unittest.main()
