"""Rewrite main text; copy accepted report_v2 exhibit pages losslessly. No estimates."""
import argparse,hashlib,html,json,sys,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from reportlab.platypus import SimpleDocTemplate,Paragraph,PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import matplotlib
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from ps2.submission_pdf import combine,read_classic


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path,value):
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--baseline',type=Path,required=True)
    a=parser.parse_args();baseline=a.baseline.resolve();source=baseline.parent
    if baseline.name!='report_v2.pdf' or len(read_classic(baseline.read_bytes()).pages)!=15:raise ValueError('Expected accepted15-page report_v2')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out=source.parent/('submission_'+stamp);out.mkdir(exist_ok=False)
    before={str(p.relative_to(ROOT)):sha(p) for p in source.rglob('*') if p.is_file()}
    narrative_path=ROOT/'docs/ps2_submission_narrative.json';narrative=json.loads(narrative_path.read_text(encoding='utf-8'))
    fontdir=Path(matplotlib.get_data_path())/'fonts/ttf'
    for name,file in [('Academic','DejaVuSerif.ttf'),('AcademicBold','DejaVuSerif-Bold.ttf'),('AcademicItalic','DejaVuSerif-Italic.ttf')]:
        pdfmetrics.registerFont(TTFont(name,str(fontdir/file)))
    pdfmetrics.registerFontFamily('Academic',normal='Academic',bold='AcademicBold',italic='AcademicItalic',boldItalic='AcademicBold')
    ink=colors.HexColor('#18394b')
    styles={
      'title':ParagraphStyle('title',fontName='AcademicBold',fontSize=15,leading=20,spaceAfter=12,textColor=ink),
      'heading':ParagraphStyle('heading',fontName='AcademicBold',fontSize=10.3,leading=14,spaceBefore=7,spaceAfter=4,textColor=ink),
      'body':ParagraphStyle('body',fontName='Academic',fontSize=10.0,leading=13.0,spaceAfter=6),
      'equation':ParagraphStyle('equation',fontName='Academic',fontSize=10.0,leading=16,spaceBefore=2,spaceAfter=9,alignment=1),
      'references':ParagraphStyle('references',fontName='Academic',fontSize=8.1,leading=10.8,spaceBefore=7,spaceAfter=0)}
    story=[];heights=[]
    for i,page in enumerate(narrative['pages']):
        if i:story.append(PageBreak())
        blocks=[Paragraph(html.escape(page['title']),styles['title'])]
        for kind,text in page['blocks']:blocks.append(Paragraph(text,styles[kind]))
        height=sum(x.wrap(504,700)[1]+x.getSpaceBefore()+x.getSpaceAfter() for x in blocks)
        if height>680:raise ValueError(f'Main-page overflow: {i+1}, {height:.1f}pt')
        heights.append(height);story.extend(blocks)
    def footer(canvas,doc):
        canvas.setStrokeColor(colors.HexColor('#ccd4db'));canvas.line(48,36,564,36);canvas.setFont('Helvetica',8)
        canvas.drawString(48,24,'Quantitative Investing | Problem Set 2');canvas.drawRightString(564,24,f'Main writeup | {doc.page}')
    main_path=out/'main_writeup.pdf'
    SimpleDocTemplate(str(main_path),pagesize=(612,792),leftMargin=48,rightMargin=48,topMargin=38,bottomMargin=46,
      title='Quantitative Investing: Problem Set2',author='').build(story,onFirstPage=footer,onLaterPages=footer)
    assembled,record=combine(main_path.read_bytes(),baseline.read_bytes())
    with (out/'PS2_final_submission.pdf').open('xb') as stream:stream.write(assembled)
    (out/'main_writeup.json').write_text(json.dumps(narrative,ensure_ascii=False,indent=2),encoding='utf-8')
    markdown='# Quantitative Investing — Problem Set2\n\n'
    for page in narrative['pages']:
        markdown+='## '+page['title']+'\n\n'
        for kind,text in page['blocks']:markdown+=('### ' if kind=='heading' else '')+text+'\n\n'
    with (out/'main_writeup.md').open('x',encoding='utf-8') as stream:stream.write(markdown)
    started=time.perf_counter()
    with (out/'tests.txt').open('x',encoding='utf-8') as stream:
        tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT/'tests')))
    test_result={'tests':tests.testsRun,'failures':len(tests.failures),'errors':len(tests.errors),'skipped':len(tests.skipped),
      'success':tests.wasSuccessful(),'seconds':time.perf_counter()-started}
    dump(out/'tests.json',test_result)
    if not tests.wasSuccessful():raise ValueError('Submission tests failed')
    for name,digest in before.items():
        if sha(ROOT/name)!=digest:raise ValueError('Accepted artifact changed: '+name)
    record.update({'baseline':str(baseline.relative_to(ROOT)),'baseline_sha256':before[str(baseline.relative_to(ROOT))],
      'baseline_files_verified_unchanged':len(before),'main_page_heights_pt':heights,'tables':7,'figures':4,
      'financial_estimation_executed':False,'exhibits_regenerated':False,'new_WRDS_queries':0,'tests':test_result,
      'sources':{str(p.relative_to(ROOT)):sha(p) for p in [narrative_path,Path(__file__),ROOT/'src/ps2/submission_pdf.py',ROOT/'docs/ps2.pdf']}})
    dump(out/'build.json',record)
    with (out/'REPRODUCIBILITY.md').open('x',encoding='utf-8') as stream:stream.write('''# Reproducibility and submission notes

The starting point is the accepted report_v2.pdf identified and hashed in build.json.
Its11 exhibit pages are imported directly; no table or plot is regenerated.
All original page-content streams remain byte-identical. New main text is stored
in main_writeup.md/JSON and authored in docs/ps2_submission_narrative.json.
The PDF assembler supports only the repository's classic-xref ReportLab files;
unsupported/encrypted/incrementally updated PDFs are rejected. It renumbers
object references outside strings/streams, attaches a new page tree, and checks
all11 exhibit content streams against the accepted baseline.

Reproduce with the existing virtual environment (no package installation):

```powershell
.\\.venv\\Scripts\\python.exe -B scripts/ps2_polish_submission.py --baseline outputs/ps2/empirical_20261019T054917302234Z/revision_v2_20261019T112854522734Z/report_v2.pdf
```

The command creates a fresh version directory, runs the full test suite, and
checks that every accepted baseline artifact is unchanged. Rendering uses
scripts/ps2_render_pdf.ps1 with Windows.Data.Pdf; inspect all generated pages.
Its interactive invocation is documented in the accepted revision's REPRODUCE.md.
No estimates, daily data processing, premium forecasts, WLS regressions or WRDS
queries are executed by this report-only command.

Existing numerical provenance, validation/test logs, source hashes, elapsed times,
memory/storage measures and preserved failed technical attempts remain in the
accepted empirical run and revision directories. In particular:

- source_data.json fingerprints saved tables, manifests and matched products.
- data_validation.json documents common keys, monthly counts and forecast horizons.
- The parent empirical run's final_validation.json covers accepted daily hashes.
- The parent runtime_and_storage.json records processing performance and qualifications.
- Original failures (local SIC memory/join attempts, beta date conversion, SQL alias
  and Q2 finalization path) remain audit history; they are not submission narrative.

Numerical policies: daily same-date RF; monthly PS1 RF for monthly models; PERMNO
security returns and current security ME; annual PS1 company fundamentals linked
at the origin. Positive origin ME and common stock-month samples are required.
Daily beta eligibility retains valid NA missing flags and D1-D4/DU single-trading-
period durations, with minimum counts stated in the main writeup. Monthly losses
normalize EW/VW within month and average months equally. HAC uses Bartlett lags12
without finite-sample correction. Accounting follows prior-year/June formation,
without historical release-date vintages; missing/invalid SIC is not Other.

Q1 k=1 makes the shrinkage rule identical to Welch. Original saved SQL summaries
contain roundoff-scale nonzero loss differences and SEs; their ratios are not
meaningful t-statistics. Table3 preserves these raw numbers and states undefined
for the identity-case t. Q3 no-profitability coefficients other than value were
not saved and remain Not estimated. No additional regressions populate them.

Submission still requires the group's Canvas upload plus code or a repository
link, as stated on assignment p.1. This script does not upload or submit anything.
''')
    with (out/'requirement_review.md').open('x',encoding='utf-8') as stream:stream.write('''# Review against the exact assignment

Read against docs/ps2.pdf, pp.1-5. Four main-text pages satisfy the five-page
limit; Tables1-7 and FiguresA-D occupy11 excluded exhibit pages. No cover page.
Submit one group writeup on Canvas and code or a repository link (p.1).

|Assignment task|Main-writeup location|Retained exhibit|
|---|---|---|
|Q1 daily excess-return historical windows and Welch (pp.1-2)|p.1 Historical estimation|Tables1,3|
|Pooled calibration and matched EW/VW RMSE; mean monthly MSE first (p.2 fn.4)|p.1 Calibration and accuracy|Tables1-2, FiguresA-B|
|IS-only alternative, justified split, OOS test and paired NW loss (pp.2-3)|p.1 Proposed improvement|Table3|
|Q2 joint traded-factor exposures and expanding historical averages (p.3)|p.2 Joint exposures|Table5|
|Premium alternative, economics, matched factor/stock IS/OOS MSE and pseudo-R2 (pp.3-4)|p.2 Alternative and evaluation|Tables4-5, FigureC|
|Statistical uncertainty and limits to return forecasting (p.4)|p.2 Paired-loss discussion|Table5|
|Q3 historical FF12, five standardized characteristics, sqrt(ME) objective (p.4 fn.9-10)|p.3 Monthly regressions|Table6|
|Value interpretation, units versus control omission (p.5)|p.3 Economic magnitude and normalization|Tables6-7, FigureD|
|Joint projection, constant span, weighted orthogonality/variation (p.5)|p.4 Residualization|Table7|
|Matched full/pure WLS, residual units, FWL and economic interpretation (p.5 fn.11)|p.4 FWL comparison|Table7|

## Substantive qualifications retained, without new estimation

1. Full-available-history beta is approximated by expanding since1960, explicitly
   approved by the user. This is a disclosed departure from an untruncated CRSP
   history. No pre1960 acquisition is authorized or required for this revision.
2. Q2's common forecast sample startsAugust1968, notJuly1963, because of60
   completed lagged-pair initialization with the existing monthly factors.
3. Accounting uses inherited June formation/prior-year statements; historical
   release-date vintages are unavailable. No claim of full point-in-time data.
4. Welch's2/252 versus2/256 and missing-session age policies are disclosed; both
   saved sensitivities are retained. These do not settle the paper's ambiguity.
5. The proposed Q1 rule selects k=1 and yields no distinct improvement. Q2's VAR
   worsens OOS stock errors. Negative findings are results, not omitted tasks.
6. Only the no-profitability value series was saved. Other coefficients remain
   Not estimated under the user's saved-results-only instruction. The available
   value comparison is matched; no omitted slopes are fabricated.
7. The weaker OOS value coefficient is emphasized; no formal structural-break
   test is claimed. FWL equality is an algebraic identity, not predictive evidence.

No additional substantive requirement is silently filled. Authors/group details
and the actual Canvas/code submission remain the group's administrative actions.
''')
    print('SUBMISSION_COMPLETE='+str(out/'PS2_final_submission.pdf'),flush=True)


if __name__=='__main__':main()
