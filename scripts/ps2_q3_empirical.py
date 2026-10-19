"""Local, month-bounded Q3 empirical WLS and joint signal purification."""
import json,time,uuid
from pathlib import Path
import numpy as np,pandas as pd,pyarrow as pa,pyarrow.parquet as pq
import ps2_extract_daily as io
from ps2_empirical import connection,save_csv,plot_setup,year_beta_files,SPLIT
from ps2.residualization import q3_design,wls,q3_fwl,CHARACTERISTICS
from ps2.factor_forecasts import paired_loss_inference


def mean_hac(series):
    x=series.to_numpy(dtype=float);n=len(x);u=x-x.mean();variance=float(u@u/n)
    for lag in range(1,13):variance+=2*(1-lag/13)*float(u[lag:]@u[:-lag]/n)
    se=float(np.sqrt(max(variance,0)/n))
    return {'n_months':n,'mean':float(x.mean()),'standard_error':se,'t_statistic':float(x.mean()/se),'NW_lags':12}


def q3(beta_root,sic_path,out,data):
    out,data=out.resolve(),data.resolve()
    started=time.perf_counter();folder=out/'q3';folder.mkdir(exist_ok=True)
    product=data/'q3';product.mkdir(exist_ok=True)
    if (folder/'manifest.json').exists():
        done=json.loads((folder/'manifest.json').read_text())
        if io.sha256(io.ROOT/done['product'])!=done['product_sha256']:raise ValueError('Q3 checksum mismatch')
        return done
    mapping=pd.read_parquet(io.ROOT/'data/processed/ps2/french/20261019T032947505510Z/ff12_ranges.parquet')
    clauses=' '.join(f'WHEN h.siccd BETWEEN {int(r.sic_start)} AND {int(r.sic_end)} THEN {int(r.ff12)}' for r in mapping.itertuples())
    classification=f'CASE WHEN h.siccd IS NULL OR h.siccd<100 OR h.siccd>9999 THEN NULL {clauses} ELSE 12 END'
    monthly=[];diagnostics=[];omitted=[];industry=[];part_files=[]
    signal_path=product/'matched_signals.parquet'
    with connection(product) as c:
        for name,path in [('securities','data/processed/security_month.parquet'),('formation','data/processed/formation.parquet'),('rf','data/processed/ref_ff5_0.parquet')]:
            c.read_parquet(str(io.ROOT/path)).create_view(name)
        c.read_parquet(year_beta_files(beta_root)).create_view('betas')
        c.read_parquet(str(sic_path)).create_view('historical_sic')
        c.execute('''CREATE VIEW origins AS SELECT s.*,year(s.month)-CASE WHEN month(s.month)<6 THEN 1 ELSE 0 END origin_formation
          FROM securities s WHERE s.eligible AND s.me>0 AND s.month BETWEEN DATE '1963-06-01' AND DATE '2025-11-01' ''')
        sql=f'''SELECT s.permno,s.month origin_month,s.month+INTERVAL 1 MONTH target_month,s.me,
          f.bm,f.op,f.inv,f.datadate,s.origin_formation,b.welch_256_cal beta,
          h.as_of_date,h.siccd,{classification} ff12,t.ret-r.RF actual
          FROM origins s
          LEFT JOIN formation f ON s.permco=f.permco AND s.origin_formation=f.formation_year
          LEFT JOIN betas b ON s.permno=b.permno AND s.month=b.month
          LEFT JOIN historical_sic h ON s.permno=h.permno AND s.month=h.observation_month
          LEFT JOIN securities t ON s.permno=t.permno AND s.month+INTERVAL 1 MONTH=t.month AND isfinite(t.ret) AND t.ret>=-1
          LEFT JOIN rf r ON t.month=r.month'''
        c.execute('CREATE VIEW candidates AS '+sql)
        counts=c.execute('''SELECT count(*),count(DISTINCT (permno,origin_month)),
           count(*) FILTER(WHERE bm IS NULL OR NOT isfinite(bm) OR bm<=0),
           count(*) FILTER(WHERE op IS NULL OR NOT isfinite(op)),count(*) FILTER(WHERE inv IS NULL OR NOT isfinite(inv)),
           count(*) FILTER(WHERE beta IS NULL OR NOT isfinite(beta)),count(*) FILTER(WHERE ff12 IS NULL),
           count(*) FILTER(WHERE actual IS NULL OR NOT isfinite(actual)),
           count(*) FILTER(WHERE datadate>=make_date(origin_formation,1,1)),
           count(*) FILTER(WHERE as_of_date IS NULL OR as_of_date<>last_day(origin_month)) FROM candidates''').fetchone()
        if counts[0]!=counts[1] or counts[8] or counts[9]:raise ValueError('Q3 key or timing validation failed: '+str(counts))
        valid='bm>0 AND '+ ' AND '.join(f'isfinite({x})' for x in ['me','bm','op','inv','beta','actual'])+' AND ff12 IS NOT NULL'
        c.execute('CREATE VIEW matched AS SELECT * FROM candidates WHERE '+valid)
        for period in pd.period_range('1963-06','2025-11',freq='M'):
            partition=product/str(period);partition.mkdir(exist_ok=True)
            if (partition/'manifest.json').exists():
                cached=json.loads((partition/'manifest.json').read_text())
                p=partition/cached['file']
                if io.sha256(p)!=cached['sha256']:raise ValueError('Q3 monthly checksum mismatch')
                monthly.append(cached['coefficients']);diagnostics.append(cached['diagnostics']);omitted.append(cached['omitted']);industry.extend(cached['industries']);part_files.append(str(p))
                continue
            g=c.execute('SELECT * FROM matched WHERE origin_month=? ORDER BY permno',[period.to_timestamp()]).df().set_index('permno')
            if not g.index.is_unique or len(g)<20:raise ValueError('Q3 invalid/insufficient cross section '+str(period))
            d=q3_design(g.me,g.bm,g.op,g.inv,g.beta,g.ff12,standardization='equal')
            fit=wls(g.actual,d.matrix,d.objective_weights)
            affine=d.matrix.copy();affine.loc[:,list(CHARACTERISTICS)]=2*affine.loc[:,list(CHARACTERISTICS)]+3
            normalized=wls(g.actual,affine,d.objective_weights)
            if not np.allclose(normalized.fitted,fit.fitted,rtol=1e-8,atol=1e-10):raise ArithmeticError('Q3 affine span identity failed')
            coeferr=float(np.max(np.abs(2*normalized.coefficients.loc[list(CHARACTERISTICS)]-fit.coefficients.loc[list(CHARACTERISTICS)])))
            without=wls(g.actual,d.matrix.drop(columns='profitability'),d.objective_weights)
            controls=d.matrix.drop(columns='log_bm')
            fwl=q3_fwl(g.actual,d.matrix.log_bm,controls,d.objective_weights)
            root=np.sqrt(d.objective_weights.to_numpy());cx=controls.to_numpy()*root[:,None]
            z=d.matrix.log_bm.to_numpy()*root
            relative=np.abs(cx.T@(fwl.projection.fit.residuals.to_numpy()*root))/(np.linalg.norm(cx,axis=0)*np.linalg.norm(z))
            target=(period+1).to_timestamp()
            monthly.append({'target_month':target,'n':len(g),**fit.coefficients.to_dict()})
            diagnostics.append({'target_month':target,'n':len(g),'FWL_slope_error':fwl.slope_difference,
                'full_value_slope':fwl.full.coefficients['__signal__'],'pure_value_slope':fwl.pure.coefficients['__signal__'],
                'projection_weighted_R2':fwl.projection.weighted_r_squared,'max_relative_orthogonality':float(relative.max()),
                'affine_coefficient_error':coeferr,'affine_max_fit_difference':float(np.max(np.abs(normalized.fitted-fit.fitted))),
                'condition_number':fit.condition_number,'represented_industries':12-len(d.unrepresented_industries)})
            omitted.append({'target_month':target,'full_value_slope':fit.coefficients.log_bm,'omit_OP_value_slope':without.coefficients.log_bm,
                'weighted_fit_change':np.average((fit.fitted-without.fitted)**2,weights=d.objective_weights)})
            for j,n in g.ff12.value_counts().items():industry.append({'target_month':target,'ff12':j,'n':n})
            sample=g[['origin_month','target_month','as_of_date','siccd','ff12','me','bm','op','inv','beta','actual']].copy()
            sample['standardized_log_bm']=d.matrix.log_bm;sample['pure_log_bm']=fwl.projection.fit.residuals
            sample['objective_weight']=d.objective_weights
            p=partition/(uuid.uuid4().hex+'.parquet')
            with p.open('xb') as f:sample.reset_index().to_parquet(f,index=False,compression='zstd',row_group_size=25000)
            part_files.append(str(p))
            serial=lambda row:{k:(v.isoformat() if isinstance(v,pd.Timestamp) else int(v) if isinstance(v,np.integer) else v) for k,v in row.items()}
            io.dump_new(partition/'manifest.json',{'file':p.name,'sha256':io.sha256(p),'coefficients':serial(monthly[-1]),
                'diagnostics':serial(diagnostics[-1]),'omitted':serial(omitted[-1]),'industries':[serial(v) for v in industry[-g.ff12.nunique():]]})
            if period.month==11 and period.year%10==0:print(f'Q3 through{period}: {len(g)} matched stocks',flush=True)
        c.read_parquet(part_files).create_view('signal_parts')
        if not signal_path.exists():c.execute('COPY signal_parts TO ? (FORMAT PARQUET, COMPRESSION ZSTD,ROW_GROUP_SIZE 25000)',[str(signal_path)])
    coefficients=pd.DataFrame(monthly).set_index('target_month')
    coefficients.index=pd.to_datetime(coefficients.index)
    diag=pd.DataFrame(diagnostics);omit=pd.DataFrame(omitted);omit['target_month']=pd.to_datetime(omit.target_month);summaries=[]
    for label,mask in [('IS',coefficients.index<pd.Timestamp(SPLIT)),('OOS',coefficients.index>=pd.Timestamp(SPLIT)),('ALL',np.ones(len(coefficients),dtype=bool))]:
        for char in CHARACTERISTICS:
            s=coefficients.loc[mask,char]
            summaries.append({'period':label,'characteristic':char,**mean_hac(s)})
    for name,frame in [('monthly_coefficients',coefficients.reset_index()),('mean_coefficients_NW',pd.DataFrame(summaries)),('FWL_diagnostics',diag),('omitted_profitability',omit),('industry_counts',pd.DataFrame(industry))]:save_csv(frame,folder/f'{name}.csv')
    plt=plot_setup(out);fig,ax=plt.subplots(figsize=(7,3))
    ax.plot(coefficients.index,coefficients.log_bm.rolling(60).mean(),label='Full controls')
    ax.plot(omit.target_month,omit.omit_OP_value_slope.rolling(60).mean(),label='Omit profitability',alpha=.8)
    ax.axhline(0,color='k',lw=.7);ax.set(title='Q3: 60-month average value coefficient',ylabel='Decimal return per cross-sectional SD');ax.legend();fig.tight_layout();fig.savefig(folder/'value_coefficients.png',dpi=160);plt.close(fig)
    report={'status':'computed','candidate_stock_months':counts[0],'matched_stock_months':int(coefficients.n.sum()),'evaluation_months':len(coefficients),
      'marginal_exclusion_counts':dict(zip(['nonpositive_missing_BM','missing_OP','missing_INV','missing_beta','missing_industry','missing_target_return'],counts[2:8])),
      'first_target':str(coefficients.index.min()),'last_target':str(coefficients.index.max()),'min_monthly_stocks':int(coefficients.n.min()),
      'max_FWL_slope_error':float(diag.FWL_slope_error.abs().max()),'max_relative_orthogonality':float(diag.max_relative_orthogonality.max()),
      'max_affine_fit_error':float(diag.affine_max_fit_difference.max()),'max_affine_coefficient_error':float(diag.affine_coefficient_error.max()),
      'projection_R2_mean':float(diag.projection_weighted_R2.mean()),'elapsed_seconds':time.perf_counter()-started,
      'accounting_timing':'PS1 annual characteristics held from June-end origin, latest formation year y-(month<6); prior-calendar-year statements. No actual release-date vintage exists. BM uses PS1 prior-December company ME; ME control/weights use current PERMNO ME.',
      'beta':'Untuned Welch 2/256 calendar-age beta observed at origin t; never IS-fitted shrinkage for earlier origins.',
      'classification':'Historical SIC at actual calendar month-end; official FF12 inclusive ranges, residual Other only for valid 0100-9999; missing/invalid excluded explicitly.',
      'standardization':'Equal-weight population SD on the matched cross section, ddof=0; all represented industry dummies span constant.',
      'weights':'Objective sqrt(ME), row multiplier ME^0.25, identical projection/full/pure samples. Residual signal retains units.',
      'identity':'FWL and affine-span equalities are algebraic identities, not evidence of predictive returns.',
      'product':str(signal_path.relative_to(io.ROOT)),'product_sha256':io.sha256(signal_path),'sic_source_sha256':io.sha256(sic_path)}
    io.dump_new(folder/'manifest.json',report);print('Q3_COMPLETE '+json.dumps(report),flush=True)
    return report
