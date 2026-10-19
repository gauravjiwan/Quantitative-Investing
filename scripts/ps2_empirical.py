"""PS2 empirical stages. Local data only; every run writes a fresh PS2 directory."""
import argparse,json,os,sys,time
from datetime import datetime,timezone
from pathlib import Path
import duckdb,numpy as np,pandas as pd
import ps2_extract_daily as io
sys.path.insert(0,str(io.ROOT/'src'))
from ps2.beta_history import WELCH_COLUMNS
from ps2.empirical_metrics import pooled_calibration,frozen_shrinkage
from ps2.factor_forecasts import paired_loss_inference

SPLIT='2000-07-01'
MODELS=['ols_1y','ols_3y','ols_expanding_1960',*WELCH_COLUMNS]


def save_csv(frame,path):
    with path.open('x',encoding='utf-8',newline='') as f:frame.to_csv(f,index=False)


def connection(folder):
    c=duckdb.connect();c.execute("SET memory_limit='512MB'");c.execute('SET threads=1')
    c.execute('SET preserve_insertion_order=false');c.execute('SET temp_directory=?',[str(folder/'temporary')])
    return c


def year_beta_files(root):
    done=json.loads((root/'completion.json').read_text())
    if done['status']!='complete':raise ValueError('Beta cache incomplete')
    paths=[]
    for y in range(1960,2026):
        record=json.loads((root/str(y)/'manifest.json').read_text())
        f=next(f for f in record['products'] if Path(f['file']).name=='monthly_betas.parquet')
        p=root/str(y)/f['file']
        if io.sha256(p)!=f['sha256']:raise ValueError('Monthly beta cache checksum mismatch')
        paths.append(str(p))
    return paths


def plot_setup(out):
    os.environ['MPLCONFIGDIR']=str(out/'matplotlib_cache')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    return plt


def q1(beta_root,out,data):
    started=time.perf_counter();folder=out/'q1';folder.mkdir(exist_ok=False)
    product=data/'q1';product.mkdir(exist_ok=False)
    with connection(product) as c:
        c.read_parquet(year_beta_files(beta_root)).create_view('betas')
        c.read_parquet(str(io.ROOT/'data/processed/security_month.parquet')).create_view('securities')
        cols=','.join('a.'+x for x in MODELS)
        query=f'''SELECT s.permno,CAST(s.month AS DATE) origin_month,
          CAST(s.month+INTERVAL 1 MONTH AS DATE) target_month,s.me,{cols},
          a.n_1y,a.n_3y,a.n_expanding,b.realized_beta,b.n_realized,b.calendar_days
          FROM securities s LEFT JOIN betas a ON s.permno=a.permno AND s.month=a.month
          LEFT JOIN betas b ON s.permno=b.permno AND s.month+INTERVAL 1 MONTH=b.month
          WHERE s.eligible AND s.me>0
           AND s.month BETWEEN DATE '1963-06-01' AND DATE '2025-11-01' '''
        c.execute('CREATE VIEW candidates AS '+query)
        valid=' AND '.join(f'isfinite({x})' for x in [*MODELS,'realized_beta','me'])
        c.execute('COPY (SELECT * FROM candidates WHERE '+valid+') TO ? (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 25000)',[str(product/'matched_forecasts.parquet')])
        c.read_parquet(str(product/'matched_forecasts.parquet')).create_view('panel')
        counts=c.execute('''SELECT (SELECT count(*) FROM candidates),count(*),
           count(DISTINCT (permno,origin_month)),count(DISTINCT target_month),
           min(target_month),max(target_month) FROM panel''').fetchone()
        if counts[1]!=counts[2] or counts[3]!=750:raise ValueError('Q1 duplicate keys or monthly coverage failure')
        cross=c.execute(f'''SELECT target_month,sum(me*(realized_beta-1)*(welch_256_cal-1))/sum(me) train_cross,
          sum(me*pow(welch_256_cal-1,2))/sum(me) train_variance FROM panel
          WHERE target_month<DATE '{SPLIT}' GROUP BY target_month ORDER BY target_month''').df()
        k=frozen_shrinkage(cross['train_cross'],cross['train_variance'])
        c.execute(f'CREATE VIEW evaluated AS SELECT *,1+{k}*(welch_256_cal-1) shrinkage FROM panel')
        models=[*MODELS,'shrinkage'];metrics=[];calibration=[];loss_frames={};uncertainty=[]
        for weighting,weight in [('EW','1.0'),('VW','me')]:
            expressions=','.join(f'sum({weight}*pow(realized_beta-{model},2))/sum({weight}) "{model}"' for model in models)
            loss=c.execute('SELECT target_month,count(*) n,'+expressions+' FROM evaluated GROUP BY target_month ORDER BY target_month').df()
            loss['month']=pd.to_datetime(loss.target_month).dt.to_period('M')
            loss_frames[weighting]=loss
            save_csv(loss,folder/f'monthly_losses_{weighting}.csv')
            for label,mask in [('IS',loss.target_month<pd.Timestamp(SPLIT)),('OOS',loss.target_month>=pd.Timestamp(SPLIT)),('ALL',np.ones(len(loss),dtype=bool))]:
                section=loss.loc[mask]
                for model in models:metrics.append({'period':label,'weighting':weighting,'model':model,
                    'months':len(section),'stock_months':int(section.n.sum()),'MSE':section[model].mean(),'RMSE':np.sqrt(section[model].mean())})
                if label!='ALL':
                    nw=paired_loss_inference(section,model='shrinkage',benchmark='welch_256_cal',newey_west_lags=12)
                    uncertainty.append({'period':label,'weighting':weighting,**nw})
        for label,condition in [('IS',f"target_month<DATE '{SPLIT}'"),('OOS',f"target_month>=DATE '{SPLIT}'"),('ALL','TRUE')]:
            for model in models:
                sums=c.execute(f'''SELECT count(*),sum({model}),sum(realized_beta),sum(pow({model},2)),
                   sum({model}*realized_beta),sum(pow(realized_beta,2)) FROM evaluated WHERE {condition}''').fetchone()
                calibration.append({'period':label,'model':model,'stock_months':sums[0],**pooled_calibration(*sums)})
        trial=[]
        for kk in [0,.25,.5,.75,1,k]:
            loss=c.execute(f'''SELECT target_month,sum(me*pow(realized_beta-(1+{kk}*(welch_256_cal-1)),2))/sum(me) loss
              FROM panel WHERE target_month<DATE '{SPLIT}' GROUP BY target_month''').df()
            trial.append({'k':kk,'IS_VW_MSE':loss.loss.mean(),'selection':'analytic optimum' if kk==k else 'predeclared grid diagnostic'})
        sensitivity=[]
        for histmin,targetmin in [(20,15),(20,20),(60,10),(126,10)]:
            filt=f'n_1y>={histmin} AND n_3y>={histmin} AND n_expanding>={histmin} AND n_realized>={targetmin}'
            expressions=','.join(f'sum(me*pow(realized_beta-{m},2))/sum(me) "{m}"' for m in models)
            loss=c.execute('SELECT target_month,count(*) n,'+expressions+' FROM evaluated WHERE '+filt+' GROUP BY target_month').df()
            for label,mask in [('IS',loss.target_month<pd.Timestamp(SPLIT)),('OOS',loss.target_month>=pd.Timestamp(SPLIT))]:
                for m in models:sensitivity.append({'history_min':histmin,'target_min':targetmin,'period':label,'model':m,
                    'months':int(mask.sum()),'stock_months':int(loss.loc[mask,'n'].sum()),'VW_RMSE':np.sqrt(loss.loc[mask,m].mean())})
        sorts=c.execute('''WITH ranked AS (SELECT *,ntile(10) OVER(PARTITION BY target_month ORDER BY welch_256_cal,permno) decile FROM evaluated),
          monthly AS (SELECT target_month,decile,avg(welch_256_cal) expected,avg(realized_beta) realized FROM ranked GROUP BY 1,2)
          SELECT CASE WHEN target_month<DATE '2000-07-01' THEN 'IS' ELSE 'OOS' END period,
            decile,avg(expected) expected_beta,avg(realized) realized_beta FROM monthly GROUP BY 1,2 ORDER BY 1,2''').df()
        for name,frame in [('rmse',pd.DataFrame(metrics)),('pooled_calibration',pd.DataFrame(calibration)),
            ('paired_losses_NW',pd.DataFrame(uncertainty)),('IS_shrinkage_trials',pd.DataFrame(trial)),
            ('minimum_history_sensitivity',pd.DataFrame(sensitivity)),('beta_sorts',sorts)]:save_csv(frame,folder/f'{name}.csv')
        plt=plot_setup(out)
        fig,ax=plt.subplots(figsize=(6,4))
        for label,g in sorts.groupby('period'):ax.plot(g.expected_beta,g.realized_beta,'o-',label=label)
        limits=[float(sorts.expected_beta.min()),float(sorts.expected_beta.max())];ax.plot(limits,limits,'k--',lw=.8)
        ax.set(xlabel='Forecast Welch beta (decile mean)',ylabel='Next-month realized OLS beta',title='Q1: beta persistence and mean reversion');ax.legend();fig.tight_layout();fig.savefig(folder/'beta_sorts.png',dpi=160);plt.close(fig)
        loss=loss_frames['VW'];fig,ax=plt.subplots(figsize=(8,3))
        ax.plot(pd.to_datetime(loss.target_month),(loss.shrinkage-loss.welch_256_cal).cumsum())
        ax.axvline(pd.Timestamp(SPLIT),color='k',ls='--');ax.axhline(0,color='gray',lw=.8)
        ax.set(title='Q1: cumulative monthly VW loss difference (shrinkage minus Welch)',ylabel='Cumulative squared beta loss');fig.tight_layout();fig.savefig(folder/'paired_loss.png',dpi=160);plt.close(fig)
        report={'status':'computed','candidate_origins':counts[0],'matched_stock_months':counts[1],'excluded_origins':counts[0]-counts[1],
          'evaluation_months':counts[3],'first_target':str(counts[4]),'last_target':str(counts[5]),'split':SPLIT,
          'shrinkage_k_fitted_IS_VW_only':k,'shrinkage_rule':'1+k*(Welch_256_calendar-1); k constrained0--1, frozen OOS',
          'primary_calibration':'pooled OLS with intercept; no monthly cross-sectional averaging of coefficients',
          'NW_lags':12,'elapsed_seconds':time.perf_counter()-started,'beta_cache':str(beta_root.relative_to(io.ROOT)),
          'initialization':'Expanding since1960, explicitly approved; not full CRSP1926 history.',
          'missing_rule':'Common sample across all7 baseline variants; all positive origin ME; finite next-month realized beta; same stocks for EW/VW.',
          'timing':'Forecast uses daily returns through actual month-end t. Target is OLS during t+1. ME is t. IS shrinkage is fitted, not a historical real-time IS forecast; frozen OOS is genuine OOS.',
          'products':[{'file':str(p.relative_to(io.ROOT)),'sha256':io.sha256(p)} for p in product.glob('*.parquet')]}
        io.dump_new(folder/'manifest.json',report)
        print('Q1_COMPLETE '+json.dumps(report),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--beta-cache',type=Path,required=True)
    a=p.parse_args();stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out=io.ROOT/'outputs/ps2'/('empirical_'+stamp);data=io.ROOT/'data/processed/ps2'/('empirical_'+stamp)
    out.mkdir(exist_ok=False);data.mkdir(exist_ok=False)
    io.dump_new(out/'run_config.json',{'beta_cache':str(a.beta_cache),'split':SPLIT,'started_utc':io.utc()})
    print('EMPIRICAL_OUTPUT='+str(out.relative_to(io.ROOT)),flush=True)
    q1(a.beta_cache.resolve(),out,data)


if __name__=='__main__':main()
