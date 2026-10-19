"""Small numerical summaries for the immutable empirical runs."""
import numpy as np


def pooled_calibration(n,sx,sy,sxx,sxy,syy):
    if n<2:return {'intercept':np.nan,'slope':np.nan,'r_squared':np.nan}
    vx=sxx-sx*sx/n;vy=syy-sy*sy/n;cov=sxy-sx*sy/n
    if vx<=abs(sxx)*1e-12:return {'intercept':sy/n,'slope':np.nan,'r_squared':0.}
    b=cov/vx
    return {'intercept':sy/n-b*sx/n,'slope':b,
            'r_squared':cov*cov/(vx*vy) if vy>0 else np.nan}


def frozen_shrinkage(monthly_cross,monthly_variance):
    cross=np.asarray(monthly_cross,dtype=float);variance=np.asarray(monthly_variance,dtype=float)
    if not len(cross) or not np.isfinite(cross).all() or not np.isfinite(variance).all() or variance.sum()<=0:
        raise ValueError('Invalid in-sample shrinkage objective')
    return float(np.clip(cross.sum()/variance.sum(),0,1))
