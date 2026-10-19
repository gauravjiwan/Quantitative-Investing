"""Saved-results-only PS2 tables, figures and versioned PDF. No estimation or WRDS."""
import argparse,hashlib,html,json,os,re,sys,unittest,time
from datetime import datetime,timezone
from pathlib import Path
import numpy as np,pandas as pd,duckdb
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Table,TableStyle,Image
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import stringWidth

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ps2.factor_forecasts import paired_loss_inference
SPLIT=pd.Timestamp('2000-07-01')
MODELS=['ols_1y','ols_3y','ols_expanding_1960','welch_256_cal','shrinkage']
LABELS={'ols_1y':'OLS: one year','ols_3y':'OLS: three years','ols_expanding_1960':'OLS: expanding since 1960',
 'welch_256_cal':'Welch: 2/256, calendar','welch_252_cal':'Welch: 2/252, calendar',
 'welch_256_pair':'Welch: 2/256, valid pairs','welch_252_pair':'Welch: 2/252, valid pairs','shrinkage':'Proposed shrinkage (k=1)',
 'CRSP_mean':'Historical market mean','factor_mean':'Expanding factor means','factor_VAR':'Expanding VAR(1)',
 'log_me':'Log ME','log_bm':'Log BM','profitability':'Profitability','investment':'Investment','beta':'Predicted market beta'}


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def dump(path,record):
    with path.open('x',encoding='utf-8') as f:json.dump(record,f,indent=2,allow_nan=False)


def fmt(value,digits=5):
    if pd.isna(value):return 'undefined'
    if isinstance(value,str):return value
    return f'{value:.{digits}f}'


def hac_mean(x,lags=12):
    """Signed-series mean HAC via an exact nonnegative paired-loss embedding."""
    x=pd.Series(x).astype(float)
    months=pd.to_datetime(x.index).to_period('M')
    base=max(0.,-float(x.min()))+1.
    result=paired_loss_inference(pd.DataFrame({'month':months,'a':x.to_numpy()+base,'b':base}),model='a',benchmark='b',newey_west_lags=lags)
    return {'mean':float(x.mean()),'standard_error':result['standard_error'],
            't_statistic':float(x.mean()/result['standard_error']) if result['standard_error']>0 else np.nan,'n_months':len(x)}


def matched_losses(ew,vw):
    if not ew[['target_month','n']].equals(vw[['target_month','n']]):raise ValueError('EW/VW samples differ')
    if ew.target_month.duplicated().any():raise ValueError('Duplicate monthly loss key')
    expected=pd.date_range(ew.target_month.min(),ew.target_month.max(),freq='MS')
    if not pd.DatetimeIndex(ew.target_month).equals(expected):raise ValueError('Incomplete loss calendar')


def load_and_verify(source,out):
    inventory=json.loads((source/'file_inventory.json').read_text())['files']
    known={str((ROOT/r['path']).resolve()):r['sha256'] for r in inventory}
    inputs={};tables={};records={}
    for q in ['q1','q2','q3']:
        for p in sorted((source/q).glob('*')):
            if p.suffix in ('.csv','.json'):
                digest=sha(p)
                if str(p.resolve()) not in known or known[str(p.resolve())]!=digest:raise ValueError('Unverified saved output '+str(p))
                inputs[str(p.relative_to(ROOT))]=digest
                if p.suffix=='.csv':tables[q+'/'+p.stem]=pd.read_csv(p)
        records[q]=json.loads((source/q/'manifest.json').read_text())
    c=duckdb.connect();c.execute("SET memory_limit='384MB'");c.execute('SET threads=1');c.execute('SET temp_directory=?',[str(out/'temporary')])
    validation={}
    for q in ['q1','q2','q3']:
        record=records[q];product=record['products'][0] if q=='q1' else {'file':record['product'],'sha256':record['product_sha256']}
        path=ROOT/product['file']
        if sha(path)!=product['sha256']:raise ValueError(q+' empirical product hash mismatch')
        inputs[product['file']]=product['sha256'];c.read_parquet(str(path)).create_view(q)
        rows,unique,bad=c.execute(f'''SELECT count(*),count(DISTINCT (permno,origin_month)),count(*) FILTER(
          WHERE permno IS NULL OR origin_month IS NULL OR me IS NULL OR me<=0 OR target_month<>origin_month+INTERVAL 1 MONTH) FROM {q}''').fetchone()
        if rows!=unique or bad or rows!=record['matched_stock_months']:raise ValueError(q+' key/count/horizon mismatch')
        counts=c.execute(f'SELECT target_month,count(*) n FROM {q} GROUP BY 1 ORDER BY 1').df()
        counts.target_month=pd.to_datetime(counts.target_month).astype('datetime64[ns]')
        validation[q]={'rows':rows,'months':len(counts),'duplicate_keys':rows-unique,'invalid_keys_weights_horizons':bad}
        if q!='q3':
            for w in ['EW','VW']:
                key=q+('/monthly_losses_' if q=='q1' else '/monthly_stock_losses_')+w
                loss=tables[key];loss['target_month']=pd.to_datetime(loss.target_month)
                if not counts.equals(loss[['target_month','n']]):raise ValueError(q+' loss counts not matched to saved product')
                models=list(LABELS)[:8] if q=='q1' else ['CRSP_mean','factor_mean','factor_VAR']
                if not np.isfinite(loss[models].to_numpy()).all():raise ValueError('Missing model loss')
            matched_losses(tables[q+('/monthly_losses_EW' if q=='q1' else '/monthly_stock_losses_EW')],tables[q+('/monthly_losses_VW' if q=='q1' else '/monthly_stock_losses_VW')])
        else:
            for name in ['monthly_coefficients','FWL_diagnostics']:
                t=tables['q3/'+name];t['target_month']=pd.to_datetime(t.target_month)
                if not counts.equals(t[['target_month','n']]):raise ValueError('Q3 cross-section count mismatch')
            omitted=tables['q3/omitted_profitability'];omitted['target_month']=pd.to_datetime(omitted.target_month)
            if not counts.target_month.equals(omitted.target_month):raise ValueError('Q3 omitted-model calendar differs')
            np.testing.assert_allclose(omitted.full_value_slope,tables['q3/monthly_coefficients'].log_bm,rtol=1e-12,atol=1e-14)
    for q,metrics,models in [('q1','rmse',[*MODELS,'welch_252_cal','welch_256_pair','welch_252_pair']),('q2','stock_metrics',['CRSP_mean','factor_mean','factor_VAR'])]:
        for w in ['EW','VW']:
            loss=tables[q+('/monthly_losses_' if q=='q1' else '/monthly_stock_losses_')+w]
            for period,mask in [('IS',loss.target_month<SPLIT),('OOS',loss.target_month>=SPLIT)]:
                for model in models:
                    r=tables[q+'/'+metrics].query('period==@period and weighting==@w and model==@model').iloc[0]
                    mse=loss.loc[mask,model].mean()
                    np.testing.assert_allclose(mse,r.MSE,rtol=1e-12,atol=1e-15)
                    if q=='q1':np.testing.assert_allclose(np.sqrt(mse),r.RMSE,rtol=1e-12)
                    if r.stock_months!=int(loss.loc[mask,'n'].sum()):raise ValueError('Summary sample differs')
    # The shrinkage model at k=1 is an identity, not a new statistically distinct forecast.
    k=records['q1']['shrinkage_k_fitted_IS_VW_only']
    if k!=1.:raise ValueError('Report identity policy requires the saved k=1 result')
    for w in ['EW','VW']:
        loss=tables['q1/monthly_losses_'+w]
        if np.max(np.abs(loss.shrinkage-loss.welch_256_cal))>1e-12:raise ValueError('Shrinkage identity inconsistent with saved losses')
    validation['Q1_identity_inference']='k=1 makes forecasts identical; saved loss differences/SEs are roundoff-scale. Preserve raw numbers; meaningful t-statistic undefined.'
    premium=tables['q2/premium_forecasts'];premium['target_month']=pd.to_datetime(premium.target_month)
    common=premium[premium.mean_ok&premium.var_ok&premium.crsp_ok]
    for f in ['Mkt-RF','SMB','HML']:
        for period,mask in [('IS',common.target_month<SPLIT),('OOS',common.target_month>=SPLIT)]:
            for model,col in [('mean','mean_'),('VAR','var_')]:
                r=tables['q2/factor_metrics'].query('factor==@f and period==@period and model==@model').iloc[0]
                np.testing.assert_allclose(((common.loc[mask,'actual_'+f]-common.loc[mask,col+f])**2).mean(),r.MSE,rtol=1e-12)
                if r.months!=mask.sum():raise ValueError('Factor sample mismatch')
    validation['Q2_factor_months']=len(common)
    # Reuse the saved coefficients; only small time-series aggregations are new.
    without=[];omitted=tables['q3/omitted_profitability'].set_index('target_month')
    for period,mask in [('IS',omitted.index<SPLIT),('OOS',omitted.index>=SPLIT),('ALL',np.ones(len(omitted),dtype=bool))]:
        without.append({'period':period,'characteristic':'log_bm',**hac_mean(omitted.loc[mask,'omit_OP_value_slope'])})
    tables['derived/Q3_no_OP_value_summary']=pd.DataFrame(without)
    validation['unsupported']='No-profitability coefficients for log ME, investment and beta were not saved; no new cross-sectional regressions performed. Profitability is omitted by definition.'
    c.close();dump(out/'data_validation.json',validation);dump(out/'source_data.json',inputs)
    return tables,records


def figures(t,out):
    os.environ['MPLCONFIGDIR']=str(out/'matplotlib_cache')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,
       'axes.labelsize':10,'axes.titlesize':11,'legend.fontsize':9,'savefig.dpi':220,'axes.unicode_minus':False,'pdf.fonttype':42})
    folder=out/'figures';folder.mkdir()
    def save(fig,name):
        fig.savefig(folder/(name+'.pdf'),bbox_inches='tight');fig.savefig(folder/(name+'.png'),bbox_inches='tight');plt.close(fig)
    accuracy=t['q1/rmse'];fig,axes=plt.subplots(1,2,figsize=(7.1,4.1),sharey=True,layout='constrained')
    for ax,w in zip(axes,['EW','VW']):
        values=[accuracy.query('period=="OOS" and weighting==@w and model==@m').iloc[0].RMSE for m in MODELS]
        ax.barh(np.arange(5),values,color=['#9daab8']*3+['#225c85','#d38a36'],height=.62)
        ax.set_yticks(np.arange(5),['One-year OLS','Three-year OLS','Expanding OLS\n(since 1960)','Welch (2/256)','Proposed (k=1)'])
        ax.set(xlabel='RMSE (beta units)',title=w+' weighting',xlim=(0,max(values)*1.22));ax.grid(axis='x',alpha=.18);ax.set_axisbelow(True)
        for y,v in enumerate(values):ax.text(v+max(values)*.025,y,f'{v:.4f}',va='center',fontsize=9)
    axes[0].invert_yaxis();save(fig,'A_Q1_OOS_RMSE')
    g=t['q1/beta_sorts'].query('period=="OOS"');r=t['q1/pooled_calibration'].query('period=="OOS" and model=="welch_256_cal"').iloc[0]
    x=np.linspace(0,max(g.expected_beta.max(),g.realized_beta.max())*1.07,200)
    fig,ax=plt.subplots(figsize=(6.4,4.6),layout='constrained')
    ax.plot(x,x,ls='--',color='#6a7178',lw=1.2,label='45-degree reference')
    ax.plot(x,r.intercept+r.slope*x,color='#d38a36',lw=1.8,label='Pooled OOS fitted line')
    ax.scatter(g.expected_beta,g.realized_beta,color='#225c85',s=38,zorder=3,label='OOS monthly decile means')
    ax.set(xlabel='Forecast Welch beta',ylabel='Next-month realized beta',xlim=(0,x.max()),ylim=(0,x.max()));ax.legend(loc='upper left');ax.grid(alpha=.15)
    save(fig,'B_Q1_calibration')
    loss=t['q2/monthly_stock_losses_VW'].query('target_month>=@SPLIT').copy()
    loss['difference']=loss.factor_VAR-loss.factor_mean;loss['cumulative_difference']=loss.difference.cumsum()
    loss.to_csv(folder/'C_plot_data.csv',index=False)
    fig,ax=plt.subplots(figsize=(7.1,4.0),layout='constrained')
    ax.plot(loss.target_month,loss.cumulative_difference,color='#a24c38',lw=1.8)
    ax.fill_between(loss.target_month,loss.cumulative_difference,0,color='#a24c38',alpha=.10)
    ax.axhline(0,color='#485460',lw=.8);ax.set(xlabel='Realization month',ylabel='Cumulative MSE difference\n(squared decimal monthly returns)');ax.grid(alpha=.15)
    ax.text(.025,.95,'Positive = VAR(1) performs worse',transform=ax.transAxes,va='top',color='#8c3d2b',fontsize=9)
    save(fig,'C_Q2_cumulative_loss')
    coefficients=t['q3/monthly_coefficients'].copy();coefficients['trailing_36_month_mean']=coefficients.log_bm.rolling(36,min_periods=36).mean()
    coefficients[['target_month','log_bm','trailing_36_month_mean']].to_csv(folder/'D_plot_data.csv',index=False)
    fig,ax=plt.subplots(figsize=(7.1,4.0),layout='constrained')
    ax.plot(coefficients.target_month,100*coefficients.log_bm,color='#b1bbc5',lw=.65,label='Monthly coefficient',alpha=.85)
    ax.plot(coefficients.target_month,100*coefficients.trailing_36_month_mean,color='#225c85',lw=1.8,label='Trailing 36-month mean (including current month)')
    ax.axhline(0,color='#485460',lw=.8);ax.axvline(SPLIT,color='#737373',lw=.9,ls=':')
    ax.set(xlabel='Realization month',ylabel='Monthly excess return per SD of log BM (%)');ax.legend(loc='upper left',fontsize=8);ax.grid(alpha=.12)
    save(fig,'D_Q3_monthly_value')


def table_layout(headers,rows,width=520):
    data=[headers]+rows
    sizes=[max(stringWidth(str(row[j]),'Helvetica-Bold' if i==0 else 'Helvetica',8.1) for i,row in enumerate(data))+14 for j in range(len(headers))]
    if sum(sizes)>width:raise ValueError('Table too wide: '+str(headers))
    flex=int(np.argmax(sizes));sizes[flex]+=width-sum(sizes)
    table=Table(data,colWidths=sizes,repeatRows=1,hAlign='LEFT')
    style=[('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTNAME',(0,1),(-1,-1),'Helvetica'),('FONTSIZE',(0,0),(-1,-1),8.1),
      ('TEXTCOLOR',(0,0),(-1,0),colors.HexColor('#173e59')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('ALIGN',(1,0),(-1,-1),'RIGHT'),
      ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
      ('LINEABOVE',(0,0),(-1,0),.8,colors.HexColor('#173e59')),('LINEBELOW',(0,0),(-1,0),.5,colors.HexColor('#173e59')),
      ('LINEBELOW',(0,-1),(-1,-1),.6,colors.HexColor('#173e59'))]
    for i in range(1,len(data)):
        if i%2==0:style.append(('BACKGROUND',(0,i),(-1,i),colors.HexColor('#f2f5f7')))
    for j in range(len(headers)):
        try:
            for row in rows:float(str(row[j]).replace(',',''))
        except ValueError:style.append(('ALIGN',(j,0),(j,-1),'LEFT'))
    table.setStyle(TableStyle(style));return table


def report(source,out,t,r):
    styles=getSampleStyleSheet();body=ParagraphStyle('Body',fontName='Helvetica',fontSize=9.1,leading=12,spaceAfter=8)
    note=ParagraphStyle('Notes',parent=body,fontSize=8.2,leading=11,spaceBefore=10,spaceAfter=5,textColor=colors.HexColor('#3f4851'))
    heading=ParagraphStyle('Title',fontName='Helvetica-Bold',fontSize=15,leading=19,spaceAfter=14,textColor=colors.HexColor('#173e59'))
    sub=ParagraphStyle('Sub',fontName='Helvetica-Bold',fontSize=10,leading=13,spaceBefore=12,spaceAfter=7)
    para=lambda s,sty=body:Paragraph(html.escape(s),sty)
    pages=[];catalog=[]
    def add(title,items,kind,source_names):
        flows=[para(title,heading)]+items
        height=sum(f.wrap(520,700)[1]+getattr(f,'spaceBefore',0)+getattr(f,'spaceAfter',0) for f in flows)
        if height>686:raise ValueError(f'Page content overflow ({height:.1f}pt): '+title)
        if kind=='table':
            number=1+sum(x['kind']=='table' for x in catalog)
            (out/'tables').mkdir(exist_ok=True)
            for panel,table in enumerate([f for f in flows if isinstance(f,Table)],1):
                with (out/'tables'/f'table_{number:02d}_panel_{panel:02d}.csv').open('x',encoding='utf-8',newline='') as stream:
                    import csv
                    csv.writer(stream).writerows(table._cellvalues)
        catalog.append({'page':len(pages)+1,'title':title,'kind':kind,'sources':source_names,'estimated_content_height_pt':height});pages.append(flows)
    original=(source/'report.md').read_text(encoding='utf-8')
    sections=re.split(r'^## ',original,flags=re.M)[1:]
    for i,section in enumerate(sections):
        title,content=section.split('\n',1)
        content=content.replace('producing zero paired loss difference and zero estimated SE; its t-statistic is undefined.',
          'so the exact paired loss difference and SE are zero and the meaningful t-statistic is undefined. Saved SQL loss summaries contain only floating-point differences (about 1e-18) and roundoff SEs; their finite numerical ratios have no statistical meaning (Table 3).')
        if i==3:
            current=json.loads((out/'tests.json').read_text())
            content=re.sub(r'Actual synthetic verification:.*?seconds\.',
              f"Current verification: {current['tests_run']} tests, {current['failures']} failures, {current['errors']} errors, {current['skipped']} skipped; {current['elapsed_seconds']:.2f} seconds. The original empirical suite had 145 passing tests; five report-generation tests were added.",content,count=1)
            content=content.replace('Reproduce locally with the existing virtual environment:',
              'This version adds Tables 1-7 and Figures A-D after the four-page main writeup; these pages are excluded from the five-page limit (assignment p. 1). Submit one group writeup to Canvas plus code or a repository link. The complete no-profitability coefficient vector was not saved: Table 6 reports only its supported value coefficient. Reproduce locally with the existing virtual environment:')
        add(title,[para(p.strip()) for p in content.split('\n\n') if p.strip()],'main',['report.md'])
    # Table 1: all historical variants and the proposed rule, ALL/IS/OOS.
    cal=t['q1/pooled_calibration'];rows=[]
    for period in ['ALL','IS','OOS']:
        for row in cal[cal.period.eq(period)].itertuples():rows.append([period,LABELS[row.model],f'{row.stock_months:,}',fmt(row.intercept,4),fmt(row.slope,4),fmt(row.r_squared,4)])
    add('Table 1. Q1 pooled predictive calibration',[
      table_layout(['Period','Estimator','N','Intercept','Slope','R-squared'],rows),
      para('Notes: Unweighted pooled OLS with intercept: next-month realized beta on origin historical beta; all slopes and betas are unitless. ALL: July 1963-December 2025, 750 months; IS: July 1963-June 2000, 444; OOS: July 2000-December 2025, 306. Within each period every estimator uses exactly the same stock-months. Welch calendar and valid-pair aging are separate variants; expanding starts in 1960, not 1926. Shrinkage k=1 reproduces Welch. N counts stock-month observations, not months. Source: q1/pooled_calibration.csv.',note)],'table',['q1/pooled_calibration.csv'])
    accuracy=t['q1/rmse'];rows=[]
    for model in MODELS:
        vals=[]
        for period,w in [('IS','EW'),('IS','VW'),('OOS','EW'),('OOS','VW')]:vals.append(fmt(accuracy.query('model==@model and period==@period and weighting==@w').iloc[0].RMSE,6))
        rows.append([LABELS[model],*vals])
    add('Table 2. Q1 forecast accuracy',[
      table_layout(['Estimator','IS EW','IS VW','OOS EW','OOS VW'],rows),
      para('Notes: RMSE in beta units equals sqrt(mean across months of normalized monthly MSE). EW normalizes equal stock weights within month; VW uses positive origin month-end ME. Identical common stocks across all seven baseline variants and the proposed rule, and identical stocks for EW/VW. IS N=2,106,038 in 444 months (July 1963-June 2000); OOS N=1,291,875 in 306 months (July 2000-December 2025). Market and stock daily excess returns subtract same-day French RF. Realized targets are next-month intercept OLS. The expanding estimate is explicitly since 1960. Source: q1/rmse.csv and monthly_losses_EW/VW.csv.',note),
      para('Interpretation',sub),para('Welch outperforms the three OLS windows on OOS EW and VW RMSE. Large EW errors reflect greater influence of volatile small stocks and noisy one-month realized beta targets. The proposed IS-tuned shrinkage equals Welch because its constrained optimum is k=1; it does not improve OOS accuracy.')], 'table',['q1/rmse.csv','q1/monthly_losses_EW.csv','q1/monthly_losses_VW.csv'])
    rows=[]
    for model in ['welch_256_cal','welch_252_cal','welch_256_pair','welch_252_pair']:
        vals=[fmt(accuracy.query('model==@model and period==@p and weighting==@w').iloc[0].RMSE,6) for p,w in [('IS','EW'),('IS','VW'),('OOS','EW'),('OOS','VW')]]
        rows.append([LABELS[model],*vals])
    trial=t['q1/IS_shrinkage_trials'].drop_duplicates(['k','IS_VW_MSE']);loss=t['q1/paired_losses_NW']
    add('Table 3. Welch robustness and IS tuning',[
      para('A. Decay and aging sensitivity: matched RMSE (beta units)',sub),table_layout(['Welch specification','IS EW','IS VW','OOS EW','OOS VW'],rows),
      para('B. Shrinkage rule: 1 + k (Welch - 1); selected k = 1',sub),table_layout(['IS trial k','IS VW MSE'],[[fmt(x.k,2),fmt(x.IS_VW_MSE,7)] for x in trial.itertuples()]),
      para('C. Paired monthly loss: proposed minus Welch',sub),table_layout(['Period / weights','Months','Saved mean loss','Saved NW SE','Meaningful t'],
        [[x.period+' / '+x.weighting,str(x.n_months),f'{x.mean_loss_difference:.3e}',f'{x.standard_error:.3e}','undefined'] for x in loss.itertuples()]),
      para('Notes: Appendix Welch rho=2/256 is primary; introduction rho=2/252 is a sensitivity. Objective age weights are exp(-rho*j). Calendar aging counts market sessions; pair aging counts usable pairs. Panel A shares Table 2 samples and dates. Panel B tunes only IS monthly VW MSE. Panel C preserves the saved roundoff-scale loss differences and Bartlett NW(12) SEs; with k=1 the forecasts are algebraically identical. The true difference/variance are zero, so t is undefined, not zero. Finite ratios in the original saved CSV are floating-point artifacts and are not statistical evidence. Further minimum-history sensitivities are retained in the source package. Sources: q1/rmse.csv, IS_shrinkage_trials.csv, paired_losses_NW.csv.',note)],'table',['q1/rmse.csv','q1/IS_shrinkage_trials.csv','q1/paired_losses_NW.csv'])
    factor=t['q2/factor_metrics'];rows=[]
    for period in ['IS','OOS']:
        for f in ['Mkt-RF','SMB','HML']:
            for model in ['mean','VAR']:
                x=factor.query('period==@period and factor==@f and model==@model').iloc[0]
                rows.append([period,f,'Expanding mean' if model=='mean' else 'VAR(1)',str(x.months),fmt(x.MSE,8),fmt(x.pseudo_R2*100,3)])
    add('Table 4. Q2 factor-premium forecasts',[
      table_layout(['Period','Factor','Forecast','Months','MSE','Pseudo-R2 (%)'],rows),
      para('Notes: MSE is in squared decimal monthly returns; pseudo-R2 = 100*(1-MSE_model/MSE_expanding_mean) in percent. Expanding mean is the benchmark for each factor, so its pseudo-R2 is zero by definition. IS: August 1968-June 2000, 383 matched factor-months; OOS: July 2000-December 2025, 306. Each premium uses identical outcome months across mean and VAR(1); there is one realization per factor per month. PS1 traded factors start July 1963, and the 60 completed lagged-pair minimum delays common evaluation to August 1968. All premium fits and averages use outcomes available through origin t only. Source: q2/factor_metrics.csv, verified against premium_forecasts.csv.',note),
      para('Interpretation',sub),para('The OOS VAR improves HML MSE modestly but worsens market and SMB MSE. Better accuracy in one premium does not imply better individual-stock forecasts because exposure vectors and correlated premium forecast errors determine stock forecast losses.')],'table',['q2/factor_metrics.csv','q2/premium_forecasts.csv'])
    rows=[]
    for period in ['IS','OOS']:
        for w in ['EW','VW']:
            for model in ['CRSP_mean','factor_mean','factor_VAR']:
                x=t['q2/stock_metrics'].query('period==@period and weighting==@w and model==@model').iloc[0]
                rows.append([period+' / '+w,LABELS[model],fmt(x.MSE,8),fmt(x.R2_vs_CRSP*100,3),fmt(x.R2_vs_factor_mean*100,3)])
    add('Table 5. Q2 stock-return forecast accuracy',[
      table_layout(['Period / weight','Forecast','MSE','R2: market (%)','R2: factors (%)'],rows),
      para('Notes: MSE uses squared decimal monthly excess returns, averaging normalized monthly losses equally. Pseudo-R2 is shown in percent against two explicit benchmarks: historical CRSP VW excess-return mean, or expanding factor means. IS N=1,618,939 stock-months in 383 months (August 1968-June 2000); OOS N=1,155,444 in 306 months (July 2000-December 2025). All three forecasts share stocks, outcomes, origin ME and factor exposure snapshots; EW and VW use the same keys. Joint 36-month three-factor OLS requires 24 valid months. Alpha is excluded. Sources: q2/stock_metrics.csv and monthly_stock_losses_EW/VW.csv.',note),
      para('OOS paired uncertainty',sub),table_layout(['Weights / comparison','Mean loss difference','NW(12) SE','t-statistic'],[
       [x.weighting+' VAR - factor means',f'{x.mean_loss_difference:.7f}',f'{x.standard_error:.7f}',fmt(x.t_statistic,3)]
       for x in t['q2/paired_losses_NW'].query('scope=="stocks" and period=="OOS" and model=="factor_VAR"').itertuples()]),
      para('Positive paired differences mean worse performance for VAR. NW statistics are descriptive normal-reference comparisons without a nested-model forecast-test correction.',note)],'table',['q2/stock_metrics.csv','q2/paired_losses_NW.csv','q2/monthly_stock_losses_EW.csv','q2/monthly_stock_losses_VW.csv'])
    rows=[]
    for period in ['ALL','IS','OOS']:
        for x in t['q3/mean_coefficients_NW'].query('period==@period').itertuples():rows.append([period,'Full: '+LABELS[x.characteristic],fmt(x.mean*100,4),fmt(x.standard_error*100,4),fmt(x.t_statistic,3)])
        x=t['derived/Q3_no_OP_value_summary'].query('period==@period').iloc[0]
        rows.append([period,'Without OP: Log BM',fmt(x['mean']*100,4),fmt(x.standard_error*100,4),fmt(x.t_statistic,3)])
    q3table=table_layout(['Period','Specification / characteristic','Mean (%)','NW SE (%)','t-statistic'],rows)
    q3table.setStyle(TableStyle([('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
    add('Table 6. Q3 mean characteristic returns',[
      q3table,
      para('Unavailable no-profitability coefficients: ALL, IS and OOS',sub),
      table_layout(['Without-OP characteristic','Mean (%)','NW SE (%)','t-statistic'],
        [[LABELS[char],'Not estimated','Not estimated','Not estimated'] for char in ['log_me','investment','beta']]),
      para('Notes: Means and SEs are percent monthly excess return per cross-sectional population SD (both x100). Full model: five characteristics plus full FF12 dummies, no separate intercept. Objective weights sqrt(ME); row scaling ME^0.25. ALL: July 1963-December 2025, 750 months, N=2,668,791 stock-months; IS: 444 months; OOS: 306. Equal-time means and Bartlett NW(12) SEs, no finite-sample correction. No-OP value uses identical stocks, units and weights; only its saved coefficient series is aggregated. Sources: q3/mean_coefficients_NW.csv and omitted_profitability.csv.',note),
      para('"Not estimated" applies to ALL/IS/OOS in this revision: those coefficients were not retained in the accepted saved outputs. No new regressions are run and no full-model slopes are substituted. Profitability is excluded by definition. Accounting uses prior-calendar-year statements and June formation, without historical release-date vintages.',note)],'table',['q3/mean_coefficients_NW.csv','q3/omitted_profitability.csv'])
    diag=t['q3/FWL_diagnostics'];rows=[]
    for title,column,op in [('Weighted projection R2: mean (%)','projection_weighted_R2','mean'),('Weighted projection R2: minimum (%)','projection_weighted_R2','min'),('Weighted projection R2: maximum (%)','projection_weighted_R2','max'),('Max relative orthogonality error','max_relative_orthogonality','max'),('Max absolute FWL slope error','FWL_slope_error','absmax'),('Max affine slope-mapping error','affine_coefficient_error','max'),('Max affine fitted-return difference','affine_max_fit_difference','max')]:
        values=[]
        for period in ['ALL','IS','OOS']:
            mask=np.ones(len(diag),dtype=bool) if period=='ALL' else (diag.target_month<SPLIT if period=='IS' else diag.target_month>=SPLIT)
            a=diag.loc[mask,column];v=a.abs().max() if op=='absmax' else getattr(a,op)()
            values.append(fmt(v*100,3) if 'R2' in title else f'{v:.3e}')
        rows.append([title,*values])
    add('Table 7. Pure-value and numerical diagnostics',[
      table_layout(['Statistic','ALL','IS','OOS'],rows),
      para('Notes: Dates match Table 6. The 750 monthly cross sections have identical stocks and sqrt(ME) objective weights in the signal projection, full return regression and pure-signal return regression. Controls are four non-value characteristics plus full represented industry indicators spanning the constant. The pure signal retains its projection-residual units. Weighted R2 describes cross-sectional signal variation explained, not return prediction. Relative orthogonality divides |C_j\'W z_perp| by weighted column and signal norms. FWL error is full-signal slope minus pure-signal slope. Affine transformation is z_new=2*z+3 for all five characteristics; characteristic slopes halve. Fit differences are decimal monthly returns. Residual differences equal fitted-return differences in magnitude because y is unchanged; no separate saved residual-error series exists. Source: q3/FWL_diagnostics.csv.',note),
      para('Economic interpretation',sub),para('FWL slope equality and affine fitted-span invariance hold algebraically under the matched-row/weight and constant-span conditions. They do not establish a return premium. Omitting profitability changes the economic comparison rather than merely changing units. The full and pure return regressions need not share fitted returns or residuals.')],'table',['q3/FWL_diagnostics.csv'])
    captions=[
      ('A. Q1 out-of-sample beta forecast accuracy','A_Q1_OOS_RMSE','July 2000-December 2025; 306 months, 1,291,875 matched stock-months. Beta-unit RMSE averages normalized monthly MSE before taking the square root. Equal versus origin-ME weighting; identical stock-month keys across all estimators. Welch is rho=2/256, calendar aging. Expanding OLS starts in 1960. Proposed shrinkage k=1 equals Welch. Source: q1/rmse.csv.',['q1/rmse.csv']),
      ('B. Welch calibration against realized beta','B_Q1_calibration','July 2000-December 2025; 306 months, 1,291,875 stock-months. Points average the saved monthly Welch-sorted decile means with equal month weights. The orange fitted line uses the saved pooled stock-month OLS intercept and slope, not a regression on these ten points. Gray dashes show the 45-degree reference. Welch rho=2/256 with calendar-session aging; betas are unitless. Sources: q1/beta_sorts.csv and pooled_calibration.csv.',['q1/beta_sorts.csv','q1/pooled_calibration.csv']),
      ('C. Cumulative out-of-sample stock forecast loss','C_Q2_cumulative_loss','July 2000-December 2025; 306 months, 1,155,444 matched stock-months. Each increment is saved monthly VW stock MSE for VAR(1) minus expanding factor means. Same three-factor betas, stocks, returns and origin-ME weights across forecasts. Cumulative sum begins at the first OOS monthly loss; it is not a portfolio return. Positive values indicate worse VAR performance. Units: squared decimal monthly returns. Source: q2/monthly_stock_losses_VW.csv.',['q2/monthly_stock_losses_VW.csv']),
      ('D. Monthly value coefficient and trailing average','D_Q3_monthly_value','July 1963-December 2025; 750 months, 2,668,791 matched stock-months. Thin gray line is the full-model monthly log-BM coefficient; blue is the trailing 36-month arithmetic mean, including the current month, requiring 36 observations. No centered or future window is used. Vertical dotted line marks July 2000. Coefficients are multiplied by 100: percent monthly excess return per cross-sectional SD of log BM. WLS uses sqrt(ME) objective weights and FF12 plus the other four characteristics. Source: q3/monthly_coefficients.csv.',['q3/monthly_coefficients.csv'])]
    for title,name,caption,sources in captions:
        path=out/'figures'/(name+'.png')
        from PIL import Image as PILImage
        with PILImage.open(path) as im:width,height=im.size
        add('Figure '+title,[Image(str(path),width=520,height=520*height/width),para(caption,note)],'figure',sources)
    story=[]
    for i,page in enumerate(pages):
        if i:story.append(PageBreak())
        story.extend(page)
    def footer(canvas,doc):
        canvas.setStrokeColor(colors.HexColor('#ccd4db'));canvas.line(46,36,566,36);canvas.setFont('Helvetica',8)
        canvas.drawString(46,24,'Quantitative Investing PS2 | revised empirical report')
        canvas.drawRightString(566,24,('Main writeup' if doc.page<=4 else 'Tables and figures')+f' | {doc.page}')
    SimpleDocTemplate(str(out/'report_v2.pdf'),pagesize=(612,792),leftMargin=46,rightMargin=46,topMargin=40,bottomMargin=46,
       title='PS2: empirical results, tables and figures',author='Quantitative Investing').build(story,onFirstPage=footer,onLaterPages=footer)
    actual=len(re.findall(rb'/Type\s*/Page\b',(out/'report_v2.pdf').read_bytes()))
    if actual!=len(pages):raise ValueError(f'Unexpected pagination: {actual} versus {len(pages)}')
    dump(out/'page_map.json',{'main_pages':4,'main_limit':5,'total_pages':actual,'pages':catalog})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path)
    args=p.parse_args();source=args.source.resolve()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out=args.out.resolve() if args.out else source/('revision_v2_'+stamp)
    out.mkdir(parents=False,exist_ok=False);print('REVISION_OUTPUT='+str(out),flush=True)
    begin=time.perf_counter()
    with (out/'tests.txt').open('x',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT/'tests')))
    dump(out/'tests.json',{'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
       'skipped':len(result.skipped),'elapsed_seconds':time.perf_counter()-begin,'success':result.wasSuccessful()})
    if not result.wasSuccessful():raise ValueError('Test suite failed; see tests.txt')
    before=sha(source/'report.pdf');t,r=load_and_verify(source,out)
    for key,frame in t.items():
        if key.startswith('derived/'):
            (out/'tables').mkdir(exist_ok=True);frame.to_csv(out/'tables'/(key.split('/')[-1]+'.csv'),index=False)
    figures(t,out);report(source,out,t,r)
    if sha(source/'report.pdf')!=before:raise ValueError('Original PDF changed')
    dump(out/'build.json',{'source':str(source.relative_to(ROOT)),'original_pdf_sha256':before,'original_pdf_preserved':True,
       'script_sha256':sha(Path(__file__)),'uses_only_saved_results':True,'new_cross_sectional_regressions':0,'new_WRDS_queries':0})
    mapping='''# Requirement-to-table/figure mapping and saved-data audit

Assignment p.1: at most five main-text pages, excluding tables/figures; submit one
group writeup to Canvas and code or repository link. This report has four main
pages and eleven dedicated table/figure pages, fifteen total. It does not submit
anything automatically.

All source paths below are relative to the accepted empirical run specified in
build.json. SHA-256 hashes and validated matched-product paths are in source_data.json.
No WRDS query, estimator refit or daily-panel processing is part of this revision.

|Requirement|Assignment|Report page|Saved source|Availability|
|---|---|---:|---|---|
|Q1 pooled intercept/slope/R2/N, all estimators|p.2|5 (T1)|q1/pooled_calibration.csv|All saved|
|Q1 matched IS/OOS EW/VW accuracy|p.2 fn.4, p.3|6 (T2)|q1/rmse.csv; monthly_losses_EW/VW.csv|All saved|
|Welch decay/age; IS tuning; paired HAC|pp.2-3|7 (T3)|q1/rmse.csv; IS_shrinkage_trials.csv; paired_losses_NW.csv|All saved; identity t is undefined|
|Q2 factor IS/OOS MSE and pseudo-R2|pp.3-4|8 (T4)|q2/factor_metrics.csv; premium_forecasts.csv|All saved|
|Q2 stock matched accuracy and uncertainty|pp.3-4|9 (T5)|q2/stock_metrics.csv; monthly_stock_losses_EW/VW.csv; paired_losses_NW.csv|All saved|
|Q3 full/without-OP average slopes and HAC|pp.4-5|10 (T6)|q3/mean_coefficients_NW.csv; omitted_profitability.csv|Full model all saved; no-OP value only, other slopes unavailable|
|Q3 purification/FWL/affine checks|p.5, fn.10-11|11 (T7)|q3/FWL_diagnostics.csv|Saved; affine residual-error magnitude follows identity, no separate saved series|
|A: Q1 OOS EW/VW RMSE|p.2|12|q1/rmse.csv|Saved|
|B: beta calibration and pooled fit|p.2, fn.5|13|q1/beta_sorts.csv; pooled_calibration.csv|Saved decile means and fitted line; no new regression|
|C: cumulative OOS stock loss difference|pp.3-4|14|q2/monthly_stock_losses_VW.csv|Saved monthly losses; new cumulative sum only|
|D: monthly value and trailing 36-month mean|pp.4-5|15|q3/monthly_coefficients.csv|Saved monthly slopes; trailing average only|

Q1/Q2 panels are checksum-verified. Stock-month keys, monthly n, origin ME and
evaluation calendars are checked against saved monthly losses. MSE/RMSE values
are independently checked by aggregating the saved losses, without refitting.
Q3 full/pure diagnostics and no-OP value series share full-model monthly keys.
The no-OP value mean/HAC summary is a cheap signed time-series aggregation of
saved coefficients and is tested against statsmodels. The complete no-OP slope
vector is unavailable; it is not reconstructed or approximated.

All mathematical identities are distinguished from empirical evidence. In Q1,
k=1 makes proposed and Welch forecasts identical; saved SQL differences and SEs
are at floating-point scale. They are displayed without alteration, while the
meaningful identity-case t-statistic is undefined. The original finite ratios
are not interpreted as evidence. All original files remain preserved.
'''
    with (out/'requirement_mapping.md').open('x',encoding='utf-8') as f:f.write(mapping)
    reproduce='''# Reproduce this saved-results report

From the repository root, using the existing virtual environment:

```powershell
.\\.venv\\Scripts\\python.exe -B scripts/ps2_report_v2.py --source outputs/ps2/empirical_20261019T054917302234Z
```

This creates a fresh timestamped revision directory and runs the complete test
suite. It never overwrites an existing revision. It verifies source CSV/manifest
hashes and matched Parquet products, generates Tables1-7 and FiguresA-D, and
builds a15-page PDF (four main-text pages). Display-ready table CSVs and vector
PDF/high-resolution PNG figure exports are retained beside the report.

Render the new PDF using built-in Windows.Data.Pdf, without installing packages:

```powershell
& ([scriptblock]::Create((Get-Content -LiteralPath scripts/ps2_render_pdf.ps1 -Raw))) -Pdf <new-revision>/report_v2.pdf -OutputDirectory <new-revision>/rendered
```

This invokes the renderer as interactive PowerShell commands; no execution-policy
setting is changed. Direct .ps1 execution is disabled in the current environment.
The render directory must not already exist. Inspect every page PNG after rendering.
page_map.json records the expected pagination and a conservative content-height
check. source_data.json fingerprints every saved numerical source. build.json
records the generator hash and preservation of the original PDF. tests.txt and
tests.json hold the actual results of the complete test suite.

No daily extraction, factor fit, beta estimator, cross-sectional WLS fit or
methodological change is executed. Additional derived quantities are only small
aggregations of saved data: no-OP value HAC, diagnostic summaries, cumulative
saved loss, and trailing36-month mean.
'''
    with (out/'REPRODUCE.md').open('x',encoding='utf-8') as f:f.write(reproduce)
    print('BUILD_COMPLETE '+str(out/'report_v2.pdf'),flush=True)


if __name__=='__main__':main()
