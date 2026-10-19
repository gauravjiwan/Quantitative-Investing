from __future__ import annotations
import argparse
from pathlib import Path
from .core import ROOT, DataError

def main():
    p=argparse.ArgumentParser(description='PS1 staged local research pipeline; no fabricated empirical results.')
    p.add_argument('stage',choices=['inventory','extract','references','import','panel','q1','characteristics','q2','q3','q4','report','all'])
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--pilot',action='store_true',help='extract only first months, outside production raw directories')
    p.add_argument('--kind',choices=['crsp_monthly','crsp_names','crsp_index','compustat_annual','ccm_link'])
    p.add_argument('--file',type=Path)
    a=p.parse_args()
    try:
        from . import ingestion
        if a.stage in {"panel", "characteristics", "all"}: from . import panel
        if a.stage in {"q1", "q2", "q3", "q4", "all"}: from . import analysis
        if a.stage in {"report", "all"}: from . import report
        if a.stage=='inventory': ingestion.inventory(a.root)
        elif a.stage=='extract': ingestion.extract(a.root,a.pilot)
        elif a.stage=='references': ingestion.references(a.root)
        elif a.stage=='import':
            if not a.kind or not a.file: p.error('import requires --kind and --file')
            ingestion.import_export(a.kind,a.file,a.root)
        elif a.stage=='panel': panel.build(a.root)
        elif a.stage=='characteristics': panel.characteristics(a.root)
        elif a.stage=='report': report.build(a.root)
        elif a.stage=='all':
            ingestion.references(a.root); panel.build(a.root); analysis.q1(a.root); panel.characteristics(a.root)
            analysis.q2(a.root); analysis.q3(a.root); analysis.q4(a.root); report.build(a.root)
        else: getattr(analysis,a.stage)(a.root)
    except DataError as e: p.exit(2,f'DATA GATE: {e}\n')
    except (EOFError,KeyboardInterrupt): p.exit(130,'Authentication cancelled; no credential saved by this pipeline.\n')

if __name__=='__main__': main()
