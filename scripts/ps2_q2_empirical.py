"""Local-only Q2 empirical integration; shared joint betas across premium models."""
import json,time
from pathlib import Path
import duckdb,numpy as np,pandas as pd
import ps2_extract_daily as io
from ps2_empirical import connection,save_csv as new_csv,plot_setup,SPLIT
from ps2.factor_history import MonthlyJointHistory
from ps2.factor_forecasts import FACTORS,expanding_mean_forecast,expanding_predictive_forecast,paired_loss_inference


def save_csv(frame,path):
    if path.exists():
        import io as memory
        pd.testing.assert_frame_equal(pd.read_csv(path),pd.read_csv(memory.StringIO(frame.to_csv(index=False))),check_exact=False,rtol=1e-12,atol=1e-15)
    else:new_csv(frame,path)


def q2(out,data):
    out,data=out.resolve(),data.resolve()
    begin=time.perf_counter();folder=out/'q2';folder.mkdir(exist_ok=True)
    product=data/'q2';product.mkdir(exist_ok=True)
    if (folder/'manifest.json').exists():
        done=json.loads((folder/'manifest.json').read_text())
        if io.sha256(io.ROOT/done['product'])!=done['product_sha256']:raise ValueError('Q2 product checksum mismatch')
        return done
    factors=pd.read_parquet(io.ROOT/'data/processed/q2_factors.parquet').set_index('month')[list(FACTORS)]
    factors.index=pd.to_datetime(factors.index).to_period('M')
    rf=pd.read_parquet(io.ROOT/'data/processed/ref_ff5_0.parquet')[['month','RF']].set_index('month').RF
    rf.index=pd.to_datetime(rf.index).to_period('M')
    crsp=pd.read_parquet(io.ROOT/'data/processed/crsp_index.parquet').set_index('month').vwretd
    crsp.index=pd.to_datetime(crsp.index).to_period('M');crsp=(crsp-rf).rename('CRSP_excess')
    if not factors.index.equals(rf.index) or not rf.index.equals(crsp.index) or factors.isna().any().any():
        raise ValueError('Q2 factor/RF/CRSP month mismatch')
    premium=[]
    for month in factors.index[:-1]:
        mean=expanding_mean_forecast(factors,as_of=month,min_observations=60)
        alt=expanding_predictive_forecast(factors,factors,as_of=month,min_observations=60)
        market=expanding_mean_forecast(crsp,as_of=month,min_observations=60)
        row={'origin_month':month.to_timestamp(),'target_month':(month+1).to_timestamp(),
            'mean_ok':mean.status=='ok','var_ok':alt.status=='ok','crsp_ok':market.status=='ok',
            'CRSP_mean':market.value.iloc[0],'training_outcome_last':str(alt.last_outcome_month)}
        for f in FACTORS:row['mean_'+f]=mean.value[f];row['var_'+f]=alt.value[f];row['actual_'+f]=factors.loc[month+1,f]
        premium.append(row)
    premium=pd.DataFrame(premium)
    if not (folder/'premium_forecasts.csv').exists():save_csv(premium,folder/'premium_forecasts.csv')
    prem=premium.set_index('origin_month');forecast_files=[]
    with connection(product) as c:
        ids=c.execute('''SELECT DISTINCT CAST(permno AS INTEGER) permno FROM read_parquet(?)
          WHERE eligible AND me>0 AND month BETWEEN DATE '1963-06-01' AND DATE '2025-11-01' ORDER BY permno''',
          [str(io.ROOT/'data/processed/security_month.parquet')]).df()
        idvalues=ids.permno.to_numpy();c.register('requested_ids',ids)
        history=MonthlyJointHistory(len(ids),36,24)
        for year in range(1963,2026):
            yearfolder=product/str(year)
            if (yearfolder/'manifest.json').exists():
                record=json.loads((yearfolder/'manifest.json').read_text())
                for p in record['products']:
                    if io.sha256(yearfolder/p['file'])!=p['sha256']:raise ValueError('Q2 annual checksum mismatch')
                history=MonthlyJointHistory.load(yearfolder/'joint_state.npz')
                if (yearfolder/'forecasts.parquet').exists():forecast_files.append(str(yearfolder/'forecasts.parquet'))
                continue
            annual=c.execute('''SELECT s.permno,s.month,s.ret,s.eligible,s.me FROM read_parquet(?) s
               JOIN requested_ids u ON s.permno=u.permno
               WHERE s.month>=? AND s.month<? ORDER BY s.month,s.permno''',
               [str(io.ROOT/'data/processed/security_month.parquet'),f'{year}-01-01',f'{year+1}-01-01']).df()
            frames=[]
            for month in pd.period_range(max('1963-07',f'{year}-01'),min('2025-11',f'{year}-12'),freq='M'):
                t=month.to_timestamp();g=annual[annual.month.eq(t)]
                idx=np.searchsorted(idvalues,g.permno.to_numpy());y=np.full(len(ids),np.nan)
                r=g.ret.to_numpy(dtype=float);valid=np.isfinite(r)&(r>=-1)
                y[idx[valid]]=r[valid]-rf.loc[month]
                coef,n=history.advance(month.year*12+month.month-1,y,factors.loc[month].to_numpy())
                p=prem.loc[t]
                if not (p.mean_ok and p.var_ok and p.crsp_ok):continue
                take=g.eligible.to_numpy()&g.me.gt(0).to_numpy()&np.isfinite(coef[idx]).all(axis=1)
                where=idx[take];selected=g.loc[take]
                beta=coef[where,1:]
                frames.append(pd.DataFrame({'permno':selected.permno.to_numpy(),'origin_month':t,
                    'target_month':(month+1).to_timestamp(),'me':selected.me.to_numpy(),
                    'factor_mean':beta@np.array([p['mean_'+f] for f in FACTORS]),
                    'factor_VAR':beta@np.array([p['var_'+f] for f in FACTORS]),'CRSP_mean':p.CRSP_mean,
                    'beta_market':beta[:,0],'beta_value':beta[:,1],'beta_size':beta[:,2],
                    'n_history_months':n[where]}))
            yearfolder.mkdir(exist_ok=False)
            paths=[]
            if frames:
                frame=pd.concat(frames,ignore_index=True);path=yearfolder/'forecasts.parquet'
                with path.open('xb') as f:frame.to_parquet(f,index=False,compression='zstd')
                paths.append(path);forecast_files.append(str(path))
            statepath=yearfolder/'joint_state.npz'
            with statepath.open('xb') as f:history.save(f)
            paths.append(statepath)
            io.dump_new(yearfolder/'manifest.json',{'year':year,'forecast_rows':sum(map(len,frames)),
               'products':[{'file':p.name,'sha256':io.sha256(p)} for p in paths]})
            if year%10==0 or year==2025:print(f'Q2 exposures through{year}: {sum(map(len,frames))} forecast rows',flush=True)
        c.read_parquet(forecast_files).create_view('forecasts')
        c.read_parquet(str(io.ROOT/'data/processed/security_month.parquet')).create_view('securities')
        rf_frame=rf.rename('RF').reset_index();rf_frame.columns=['month','RF'];rf_frame['month']=rf_frame.month.dt.to_timestamp()
        c.register('RF',rf_frame)
        sql='''SELECT f.*,s.ret-r.RF actual FROM forecasts f
          JOIN securities s ON f.permno=s.permno AND f.target_month=s.month
          JOIN RF r ON f.target_month=r.month WHERE isfinite(s.ret) AND s.ret>=-1
          AND isfinite(f.factor_mean) AND isfinite(f.factor_VAR) AND isfinite(f.CRSP_mean)'''
        path=product/'matched_forecasts.parquet'
        if not path.exists():c.execute('COPY ('+sql+') TO ? (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 25000)',[str(path)])
        c.read_parquet(str(path)).create_view('panel')
        counts=c.execute('SELECT count(*),count(DISTINCT (permno,target_month)),count(DISTINCT target_month),min(target_month),max(target_month) FROM panel').fetchone()
        if counts[0]!=counts[1] or not counts[0]:raise ValueError('Q2 invalid empirical keys/sample')
        stock_metrics=[];uncertainty=[];models=['CRSP_mean','factor_mean','factor_VAR']
        for label,w in [('EW','1.0'),('VW','me')]:
            expressions=','.join(f'sum({w}*pow(actual-{m},2))/sum({w}) "{m}"' for m in models)
            loss=c.execute('SELECT target_month,count(*) n,'+expressions+' FROM panel GROUP BY target_month ORDER BY target_month').df()
            loss['month']=pd.to_datetime(loss.target_month).dt.to_period('M');save_csv(loss,folder/f'monthly_stock_losses_{label}.csv')
            for period,mask in [('IS',loss.target_month<pd.Timestamp(SPLIT)),('OOS',loss.target_month>=pd.Timestamp(SPLIT))]:
                g=loss.loc[mask];means=g[models].mean()
                for model in models:stock_metrics.append({'period':period,'weighting':label,'model':model,'months':len(g),'stock_months':int(g.n.sum()),
                    'MSE':means[model],'R2_vs_CRSP':1-means[model]/means.CRSP_mean,'R2_vs_factor_mean':1-means[model]/means.factor_mean})
                for model,base in [('factor_VAR','factor_mean'),('factor_mean','CRSP_mean')]:
                    uncertainty.append({'scope':'stocks','factor':'all','period':period,'weighting':label,'model':model,'benchmark':base,
                        **paired_loss_inference(g,model=model,benchmark=base,newey_west_lags=12)})
        factormetrics=[]
        matched_prem=premium[premium.mean_ok&premium.var_ok&premium.crsp_ok]
        for factor in FACTORS:
            loss=pd.DataFrame({'month':pd.to_datetime(matched_prem.target_month).dt.to_period('M'),
                'mean':(matched_prem['actual_'+factor]-matched_prem['mean_'+factor])**2,
                'VAR':(matched_prem['actual_'+factor]-matched_prem['var_'+factor])**2})
            for period,mask in [('IS',loss.month<pd.Period(SPLIT,freq='M')),('OOS',loss.month>=pd.Period(SPLIT,freq='M'))]:
                g=loss.loc[mask]
                for model in ('mean','VAR'):factormetrics.append({'factor':factor,'period':period,'model':model,'months':len(g),
                   'MSE':g[model].mean(),'pseudo_R2':1-g[model].mean()/g['mean'].mean()})
                uncertainty.append({'scope':'factor','factor':factor,'period':period,'weighting':'one observation/month','model':'VAR','benchmark':'mean',
                   **paired_loss_inference(g,model='VAR',benchmark='mean',newey_west_lags=12)})
        for name,frame in [('stock_metrics',pd.DataFrame(stock_metrics)),('factor_metrics',pd.DataFrame(factormetrics)),('paired_losses_NW',pd.DataFrame(uncertainty))]:save_csv(frame,folder/f'{name}.csv')
        plt=plot_setup(out);fig,ax=plt.subplots(figsize=(6,3))
        plot=pd.DataFrame(factormetrics);plot=plot[(plot.period=='OOS')&(plot.model=='VAR')]
        ax.bar(plot.factor,plot.pseudo_R2);ax.axhline(0,color='k',lw=.8);ax.set(title='Q2: OOS factor VAR pseudo-R-squared versus expanding mean',ylabel='Pseudo-R-squared')
        fig.tight_layout()
        if not (folder/'factor_OOS_R2.png').exists():fig.savefig(folder/'factor_OOS_R2.png',dpi=160)
        plt.close(fig)
        report={'status':'computed','matched_stock_months':counts[0],'evaluation_months':counts[2],'first_target':str(counts[3]),'last_target':str(counts[4]),
            'split':SPLIT,'exposures':'Joint monthly36-calendar-month OLS with intercept, minimum24 matched months; alpha excluded from forecasts.',
            'factor_source':'Read-only PS1 q2_factors: constructed traded Mkt-RF,HML,SMB. Monthly RF from ref_ff5_0; CRSP baseline from crsp_index.vwretd minus same RF.',
            'alternative':'Predeclared expanding VAR(1) on lagged realized factors, minimum60 completed training pairs. Specification fixed before OOS; coefficients update using outcomes through t only.',
            'comparison':'Identical joint exposure snapshot and stocks/ME_t across premium methods; month-normalized EW/VW losses, equal averaging across months.',
            'warmup':'First factor data July1963; alternative needs60 completed lagged pairs. All compared methods use the resulting common forecast sample.',
            'NW_lags':12,'elapsed_seconds':time.perf_counter()-begin,'product':str(path.relative_to(io.ROOT)),'product_sha256':io.sha256(path)}
        io.dump_new(folder/'manifest.json',report);print('Q2_COMPLETE '+json.dumps(report),flush=True)
    return report
