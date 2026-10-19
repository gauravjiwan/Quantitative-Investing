"""Bounded monthly sufficient statistics matching dated daily OLS/Welch fits.

Slots hold 37 months, including the leap-day endpoint needed by DateOffset
one-/three-year windows. State size depends on the fixed requested ID universe,
not the number of daily observations. All inputs are excess decimal returns.
"""
import calendar
import numpy as np

VARIANTS=((2/256,'cal'),(2/252,'cal'),(2/256,'pair'),(2/252,'pair'))
WELCH_COLUMNS=('welch_256_cal','welch_252_cal','welch_256_pair','welch_252_pair')


def slope(m,minimum=20):
    m=np.asarray(m,dtype=float)
    n,sx,sy,sxx,sxy=m.T
    out=np.full(len(m),np.nan)
    with np.errstate(divide='ignore',invalid='ignore'):
        d=sxx-sx*sx/n
        good=(n>=minimum)&np.isfinite(m).all(axis=1)&(d>np.maximum(np.abs(sxx)*1e-12,1e-300))
        out[good]=(sxy[good]-sx[good]*sy[good]/n[good])/d[good]
    return out


class BetaHistory:
    def __init__(self,n_ids):
        self.ring=np.zeros((n_ids,37,10))
        self.one=np.zeros((n_ids,5));self.three=self.one.copy();self.expanding=self.one.copy()
        self.weighted=np.zeros((4,n_ids,5));self.last_month=-1

    def advance(self,month,moments,weighted,calendar_days,current_valid):
        if self.last_month!=-1 and month!=self.last_month+1:
            raise ValueError('History must advance exactly one calendar month')
        n=len(self.one)
        if (moments.shape!=(n,10) or weighted.shape!=(4,n,5) or current_valid.shape!=(n,)
            or calendar_days<1 or not np.isfinite(moments).all() or not np.isfinite(weighted).all()):
            raise ValueError('Invalid bounded monthly moments')
        slot=month%37
        old12=self.ring[:,(slot-12)%37,:5].copy()
        old36=self.ring[:,(slot-36)%37,:5].copy()
        extra12=self.ring[:,(slot-12)%37,5:].copy()
        extra36=self.ring[:,(slot-36)%37,5:].copy()
        self.one+=moments[:,:5]-old12
        self.three+=moments[:,:5]-old36
        self.expanding+=moments[:,:5]
        year,month0=divmod(month,12)
        # DateOffset from nonleap Feb28 to leap-year Feb28 excludes Feb28,
        # but includes Feb29. Whole calendar-month sums otherwise match exactly.
        if month0!=1 or calendar.isleap(year):extra12[:]=0;extra36[:]=0
        if not calendar.isleap(year-1):extra12[:]=0
        if not calendar.isleap(year-3):extra36[:]=0
        for j,(rho,age) in enumerate(VARIANTS):
            ages=moments[:,0] if age=='pair' else calendar_days
            self.weighted[j]*=np.exp(-rho*ages)[...,None] if age=='pair' else np.exp(-rho*ages)
            self.weighted[j]+=weighted[j]
        self.ring[:,slot]=moments
        self.last_month=month
        r={'ols_1y':slope(self.one+extra12),'ols_3y':slope(self.three+extra36),
           'ols_expanding_1960':slope(self.expanding),
           'n_1y':self.one[:,0]+extra12[:,0],'n_3y':self.three[:,0]+extra36[:,0],
           'n_expanding':self.expanding[:,0].copy(),
           'realized_beta':slope(moments[:,:5],max(10,int(np.ceil(calendar_days/2)))),
           'n_realized':moments[:,0].copy()}
        for j,name in enumerate(WELCH_COLUMNS):
            b=slope(self.weighted[j],np.finfo(float).tiny)
            b[(self.expanding[:,0]<20)|~current_valid]=np.nan
            r[name]=b
        return r

    def save(self,stream):
        np.savez_compressed(stream,ring=self.ring,one=self.one,three=self.three,
            expanding=self.expanding,weighted=self.weighted,last_month=np.array(self.last_month))

    @classmethod
    def load(cls,path):
        with np.load(path,allow_pickle=False) as x:
            obj=cls(len(x['one']))
            for name in ('ring','one','three','expanding','weighted'):setattr(obj,name,x[name].copy())
            obj.last_month=int(x['last_month'])
        return obj
