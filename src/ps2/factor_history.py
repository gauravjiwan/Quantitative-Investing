"""Joint monthly factor OLS with a fixed calendar window and bounded state."""
import numpy as np


class MonthlyJointHistory:
    def __init__(self,n_ids,window=36,minimum=24):
        if not 4<=minimum<=window:raise ValueError('Joint OLS requires an explicit feasible minimum')
        self.window,self.minimum=window,minimum
        self.valid=np.zeros((n_ids,window),dtype=bool)
        self.returns=np.zeros((n_ids,window));self.factors=np.zeros((window,4))
        self.xx=np.zeros((n_ids,4,4));self.xy=np.zeros((n_ids,4));self.count=np.zeros(n_ids,dtype=np.int32)
        self.last_month=-1

    def advance(self,month,stock_excess,factors):
        if self.last_month!=-1 and month!=self.last_month+1:raise ValueError('Calendar-month gap in joint history')
        y=np.asarray(stock_excess,dtype=float);f=np.asarray(factors,dtype=float)
        if y.shape!=self.count.shape or f.shape!=(3,):raise ValueError('Joint history input shape mismatch')
        slot=month%self.window;x=np.r_[1.,f]
        oldvalid=self.valid[:,slot].copy();oldy=self.returns[:,slot].copy();oldx=self.factors[slot].copy()
        newvalid=np.isfinite(y)&np.isfinite(x).all()
        safe=np.where(newvalid,y,0.);x=np.where(np.isfinite(x),x,0.)
        self.xx-=oldvalid[:,None,None]*np.outer(oldx,oldx)
        self.xy-=(oldvalid*oldy)[:,None]*oldx
        self.xx+=newvalid[:,None,None]*np.outer(x,x)
        self.xy+=safe[:,None]*x
        self.count+=newvalid.astype(np.int32)-oldvalid.astype(np.int32)
        self.valid[:,slot]=newvalid;self.returns[:,slot]=safe;self.factors[slot]=x;self.last_month=month
        coef=np.full_like(self.xy,np.nan);take=np.flatnonzero(self.count>=self.minimum)
        if len(take):
            matrices=self.xx[take];scale=np.sqrt(np.maximum(np.diagonal(matrices,axis1=1,axis2=2),0))
            good=(scale>0).all(axis=1);indices=take[good];scale=scale[good]
            a=self.xx[indices]/(scale[:,:,None]*scale[:,None,:])
            eig=np.linalg.eigvalsh(a);rank_ok=eig[:,0]>eig[:,-1]*1e-10
            indices=indices[rank_ok];scale=scale[rank_ok];a=a[rank_ok]
            if len(indices):coef[indices]=np.linalg.solve(a,(self.xy[indices]/scale)[:,:,None])[:,:,0]/scale
        return coef,self.count.copy()

    def save(self,stream):
        np.savez_compressed(stream,valid=self.valid,returns=self.returns,factors=self.factors,
            xx=self.xx,xy=self.xy,count=self.count,window=self.window,minimum=self.minimum,last_month=self.last_month)

    @classmethod
    def load(cls,path):
        with np.load(path,allow_pickle=False) as f:
            h=cls(len(f['count']),int(f['window']),int(f['minimum']))
            for name in ('valid','returns','factors','xx','xy','count'):setattr(h,name,f[name].copy())
            h.last_month=int(f['last_month'])
        return h
