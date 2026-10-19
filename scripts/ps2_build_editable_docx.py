"""Build a native DOCX from source narrative, saved CSV panels and original PNGs.

No PDF text extraction, estimators, external services, installations or WRDS.
Uses lxml plus zipfile instead of requiring python-docx.
"""
import argparse,ast,csv,hashlib,html,json,re,sys,time,unittest,zipfile
from datetime import datetime,timezone
from pathlib import Path
from copy import deepcopy
from lxml import etree as E
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from ps2.word_math import M,W,NS,display_equations,factor_vector,display,omath,seq,r,var,sup,sub,fraction,radical,delim
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG='http://schemas.openxmlformats.org/package/2006/relationships'
WP='http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
A='http://schemas.openxmlformats.org/drawingml/2006/main'
PIC='http://schemas.openxmlformats.org/drawingml/2006/picture'
N={'w':W,'m':M,'r':R,'wp':WP,'a':A,'pic':PIC}


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def put(path,obj):
    with path.open('x',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,indent=2)
def x(prefix,tag,**attrs):
    result=E.Element('{'+N[prefix]+'}'+tag)
    for k,v in attrs.items():result.set(('{'+N[prefix]+'}'+k) if prefix in ['w','m'] else k,str(v))
    return result
def xml(e):return E.tostring(e,encoding='UTF-8',xml_declaration=True,standalone=True)


def run(text,bold=False):
    element=x('w','r')
    if bold:pr=x('w','rPr');pr.append(x('w','b'));element.append(pr)
    t=x('w','t');t.text=text;t.set('{http://www.w3.org/XML/1998/namespace}space','preserve');element.append(t);return element


def paragraph(text='',style='Normal',page_break=False,align=None):
    p=x('w','p');pr=x('w','pPr');pr.append(x('w','pStyle',val=style))
    if page_break:pr.append(x('w','pageBreakBefore'))
    if align:pr.append(x('w','jc',val=align))
    p.append(pr)
    if text:add_inline(p,text)
    return p


def add_inline(p,text):
    special={
      'b*=1+k(b<sup>Welch</sup>−1), 0≤k≤1':seq('b* = 1 + k ',delim(seq(sup(r('b'),'Welch'),' − 1')),', 0 ≤ k ≤ 1'),
      'γ=γ<sup>⊥</sup>':seq('γ = ',sup(r('γ'),'⊥')),
    }
    for token,expression in special.items():
        if token in text:
            before,after=text.split(token,1);add_inline(p,before);p.append(omath(expression));add_inline(p,after);return
    # Source HTML subscripts/superscripts become structural Word math, not text.
    pattern=r'([A-Za-zΑ-Ωα-ω0-9]+)((?:<(?:sup|sub)>[^<]*</(?:sup|sub)>){1,2})'
    last=0
    for match in re.finditer(pattern,text):
        add_text_math(p,html.unescape(text[last:match.start()]))
        scripts={kind:html.unescape(value) for kind,value in re.findall(r'<(sup|sub)>(.*?)</(?:sup|sub)>',match[2])}
        base=r(match[1]);power=scripts.get('sup');index=scripts.get('sub')
        if index is not None:base=sub(base,index)
        if power is not None:base=sup(base,fraction(*power.split('/')) if '/' in power else power)
        p.append(omath(seq(base)));last=match.end()
    add_text_math(p,html.unescape(text[last:]))


def add_text_math(p,text):
    replacements={
      'R²':seq(sup(r('R'),'2')),
      'ρ=2/256':seq('ρ = ',fraction('2','256')),
      '2/252':seq(fraction('2','252')),
      'exp(−ρj)':seq('exp(−ρj)'),
      'z_new=2z+3':seq(var('z','new'),' = 2z + 3'),
      'W=diag(√ME)':seq('W = ',r('diag',True),delim(seq(radical(seq(r('ME')))))),
      '√ME':seq(radical(seq(r('ME')))),
    }
    regex='|'.join(re.escape(k) for k in replacements);last=0
    for m in re.finditer(regex,text):
        if m.start()>last:p.append(run(text[last:m.start()]))
        p.append(omath(replacements[m[0]]));last=m.end()
    if last<len(text):p.append(run(text[last:]))


def source_metadata(script):
    tree=ast.parse(script.read_text(encoding='utf-8'));function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='report')
    tables=[];captions=None
    for n in ast.walk(function):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='add' and isinstance(n.args[0],ast.Constant) and str(n.args[0].value).startswith('Table '):
            items=[]
            for item in n.args[1].elts:
                if isinstance(item,ast.Call) and isinstance(item.func,ast.Name) and item.func.id=='para' and isinstance(item.args[0],ast.Constant):
                    items.append({'kind':'heading' if len(item.args)>1 and isinstance(item.args[1],ast.Name) and item.args[1].id=='sub' else 'text','text':item.args[0].value})
                elif isinstance(item,ast.Name) or isinstance(item,ast.Call) and isinstance(item.func,ast.Name) and item.func.id=='table_layout':items.append({'kind':'table'})
            tables.append({'title':n.args[0].value,'items':items})
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='captions' for t in n.targets):captions=ast.literal_eval(n.value)
    if len(tables)!=7 or len(captions or [])!=4:raise ValueError('Unsupported report-source structure')
    return tables,captions


def table_native(panels,metadata):
    cols=max(len(panel[0]) for panel in panels);width=10400
    # Widths favor the descriptive column; numbers retain room for scientific notation.
    title=metadata['title']
    if title.startswith('Table 1.'):widths=[680,3800,1600,1450,1450,1420]
    elif title.startswith('Table 4.'):widths=[650,950,3200,1100,2250,2250]
    elif title.startswith('Table 5.'):widths=[1300,3400,1900,1900,1900]
    elif title.startswith('Table 6.'):widths=[650,3950,1900,1900,1900]
    elif cols==5:widths=[3800,1650,1650,1650,1650]
    else:widths=[5000]+[1800]*(cols-1)
    widths=[int(v*width/sum(widths)) for v in widths];widths[-1]+=width-sum(widths)
    tbl=x('w','tbl');props=x('w','tblPr');props.append(x('w','tblW',w=width,type='dxa'));props.append(x('w','tblLayout',type='fixed'))
    margins=x('w','tblCellMar')
    for side in ['top','bottom']:margins.append(x('w',side,w='40',type='dxa'))
    for side in ['left','right']:margins.append(x('w',side,w='65',type='dxa'))
    props.append(margins);tbl.append(props)
    grid=x('w','tblGrid')
    for v in widths:grid.append(x('w','gridCol',w=v))
    tbl.append(grid)
    expected=[];panel_index=0;trailing=[];seen_panel=False
    def add_row(values,heading=False,merged=False,panel=-1):
        tr=x('w','tr');trpr=x('w','trPr');trpr.append(x('w','cantSplit'))
        if heading and not seen_panel:trpr.append(x('w','tblHeader'))
        tr.append(trpr)
        if merged:spans=[cols]
        else:spans=[1]*len(values);spans[0]+=cols-len(values)
        offset=0
        for j,(value,span) in enumerate(zip(values,spans)):
            cell=x('w','tc');pr=x('w','tcPr');pr.append(x('w','tcW',w=sum(widths[offset:offset+span]),type='dxa'))
            if span>1:pr.append(x('w','gridSpan',val=span))
            pr.append(x('w','vAlign',val='center'))
            if heading:pr.append(x('w','shd',fill='E8EEF2'))
            borders=x('w','tcBorders')
            if heading:borders.append(x('w','bottom',val='single',sz='5',color='648096'))
            pr.append(borders);cell.append(pr)
            p=paragraph(style='TableHeader' if heading else 'TableText')
            alignment_value=value
            if heading and panel>0 and len(panels[panel-1])>1:alignment_value=panels[panel-1][1][j]
            try:float(alignment_value.replace(',',''));alignment='right' if j>0 else 'left'
            except ValueError:alignment='left'
            p.find('{'+W+'}pPr').append(x('w','jc',val=alignment))
            p.append(run(value,heading));cell.append(p);tr.append(cell);offset+=span
        tbl.append(tr);expected.append({'panel':panel,'heading':heading,'merged':merged,'cells':values})
    for item in metadata['items']:
        if item['kind']=='table':
            panel=panels[panel_index]
            for i,row in enumerate(panel):add_row(row,heading=i==0,panel=panel_index+1)
            seen_panel=True;panel_index+=1
        elif item['kind']=='heading' and panel_index<len(panels):add_row([item['text']],heading=True,merged=True)
        else:trailing.append(item)
    if panel_index!=len(panels):raise ValueError('Saved table-panel count mismatch')
    return tbl,trailing,expected


def styles_xml():
    root=x('w','styles');default=x('w','docDefaults');rp=x('w','rPrDefault');rp.append(x('w','rPr'));default.append(rp);root.append(default)
    settings=[('Normal','Normal',21,268,110,False,'Times New Roman'),('Heading1','Heading 1',29,340,180,True,'Times New Roman'),
      ('Heading2','Heading 2',22,280,65,True,'Times New Roman'),('Equation','Equation',21,0,110,False,'Cambria Math'),
      ('Caption','Caption',25,300,140,True,'Arial'),('Notes','Table and figure notes',17,215,70,False,'Arial'),
      ('TableText','Table text',16,195,0,False,'Arial'),('TableHeader','Table header',16,195,0,True,'Arial'),
      ('PanelHeading','Panel heading',19,230,70,True,'Arial'),('References','References',17,215,50,False,'Times New Roman'),('Footer','Footer',16,200,0,False,'Arial')]
    for ident,label,size,line,after,bold,font in settings:
        s=x('w','style',type='paragraph',styleId=ident)
        if ident=='Normal':s.set('{'+W+'}default','1')
        s.append(x('w','name',val=label))
        if ident!='Normal':s.append(x('w','basedOn',val='Normal'))
        p=x('w','pPr');spacing=x('w','spacing',after=after)
        if line:spacing.set('{'+W+'}line',str(line));spacing.set('{'+W+'}lineRule','exact')
        if ident in ['Normal','Notes','References']:spacing.set('{'+W+'}lineRule','atLeast')
        if ident=='Equation':spacing.set('{'+W+'}line','240');spacing.set('{'+W+'}lineRule','auto')
        if ident in ['Heading1','Heading2','Caption','PanelHeading']:
            p.append(x('w','keepNext'));p.append(x('w','keepLines'))
        if ident.startswith('Heading'):p.append(x('w','outlineLvl',val='0' if ident=='Heading1' else '1'))
        p.append(spacing);p.append(x('w','widowControl'));s.append(p)
        rp=x('w','rPr');rp.append(x('w','rFonts',ascii=font,hAnsi=font,eastAsia=font));rp.append(x('w','sz',val=size));rp.append(x('w','szCs',val=size))
        if bold:rp.append(x('w','b'))
        if ident in ['Heading1','Heading2','Caption','PanelHeading']:rp.append(x('w','color',val='18394B'))
        s.append(rp);root.append(s)
    return root


def image_run(path,rid,number):
    with Image.open(path) as im:width,height=im.size
    cx=int(7.0*914400);cy=int(cx*height/width)
    drawing=x('w','drawing');inline=x('wp','inline',distT='0',distB='0',distL='0',distR='0')
    inline.append(x('wp','extent',cx=cx,cy=cy));inline.append(x('wp','docPr',id=number,name=path.name))
    graphic=x('a','graphic');data=x('a','graphicData',uri=PIC);pic=x('pic','pic')
    nv=x('pic','nvPicPr');nv.append(x('pic','cNvPr',id='0',name=path.name));nv.append(x('pic','cNvPicPr'));pic.append(nv)
    fill=x('pic','blipFill');blip=x('a','blip');blip.set('{'+R+'}embed',rid);fill.append(blip)
    stretch=x('a','stretch');stretch.append(x('a','fillRect'));fill.append(stretch);pic.append(fill)
    sp=x('pic','spPr');transform=x('a','xfrm');transform.append(x('a','off',x='0',y='0'));transform.append(x('a','ext',cx=cx,cy=cy));sp.append(transform)
    geom=x('a','prstGeom',prst='rect');geom.append(x('a','avLst'));sp.append(geom);pic.append(sp)
    data.append(pic);graphic.append(data);inline.append(graphic);drawing.append(inline)
    element=x('w','r');element.append(drawing);return element


def build(submission,revision,out):
    out.mkdir(exist_ok=False);narrative_path=submission/'main_writeup.json';narrative=json.loads(narrative_path.read_text(encoding='utf-8'))
    input_paths=[narrative_path,submission/'PS2_final_submission.pdf',revision/'report_v2.pdf',ROOT/'scripts/ps2_report_v2.py']
    known={str((ROOT/f['path']).resolve()):f['sha256'] for f in json.loads((revision/'files_created.json').read_text())['files']}
    metadata,captions=source_metadata(ROOT/'scripts/ps2_report_v2.py')
    root=E.Element('{'+W+'}document',nsmap=N);body=x('w','body');root.append(body)
    equations=display_equations();eq_index=0;bookmark_id=1;paragraph_sources=[]
    for page_index,page in enumerate(narrative['pages']):
        title=paragraph(page['title'],'Heading1',page_index>0);body.append(title)
        for kind,text in page['blocks']:
            if kind=='equation':
                p=paragraph(style='Equation');p.append(display(equations[eq_index]));body.append(p)
                paragraph_sources.append({'type':'equation','source':text,'equation_index':eq_index});eq_index+=1
                if eq_index==4:
                    p=paragraph(style='Equation');p.append(display(factor_vector()));body.append(p)
            else:
                p=paragraph(text,{'heading':'Heading2','references':'References'}.get(kind,'Normal'));body.append(p)
                paragraph_sources.append({'type':kind,'source':text})
    if eq_index!=9:raise ValueError('Narrative equation count changed')
    # End marker permits Word's actual pagination to enforce the main-writeup limit.
    last=body[-1];start=x('w','bookmarkStart',id='1',name='MainEnd');end=x('w','bookmarkEnd',id='1');last.append(start);last.append(end)
    table_expected=[]
    for number,meta in enumerate(metadata,1):
        body.append(paragraph(meta['title'],'Caption',True))
        paths=sorted((revision/'tables').glob(f'table_{number:02d}_panel_*.csv'));panels=[]
        for path in paths:
            if known.get(str(path.resolve()))!=sha(path):raise ValueError('Unverified saved table '+str(path))
            input_paths.append(path)
            with path.open(newline='',encoding='utf-8') as f:panels.append(list(csv.reader(f)))
        table,notes,expected=table_native(panels,meta);body.append(table);table_expected.append(expected)
        for item in notes:body.append(paragraph(item['text'],'PanelHeading' if item['kind']=='heading' else 'Notes'))
    images=[]
    for i,(title,name,caption,_) in enumerate(captions,1):
        body.append(paragraph('Figure '+title,'Caption',True));path=revision/'figures'/(name+'.png')
        if known.get(str(path.resolve()))!=sha(path):raise ValueError('Unverified figure image')
        input_paths.append(path);p=paragraph(align='center');p.append(image_run(path,'figure'+str(i),i));body.append(p)
        body.append(paragraph(caption,'Notes'));images.append(path)
    sect=x('w','sectPr');header=x('w','headerReference',type='default');header.set('{'+R+'}id','header');sect.append(header)
    footer=x('w','footerReference',type='default');footer.set('{'+R+'}id','footer');sect.append(footer)
    sect.append(x('w','pgSz',w='12240',h='15840'));sect.append(x('w','pgMar',top='760',bottom='800',left='850',right='850',header='300',footer='360',gutter='0'));body.append(sect)
    settings=x('w','settings');settings.append(x('w','updateFields',val='true'))
    compat=x('w','compat');compat.append(x('w','compatSetting',name='compatibilityMode',uri='http://schemas.microsoft.com/office/word',val='15'));settings.append(compat)
    math=E.Element('{'+M+'}mathPr');math.append(E.Element('{'+M+'}mathFont',attrib={'{'+M+'}val':'Cambria Math'}));settings.append(math)
    footer=x('w','ftr');p=paragraph('Quantitative Investing · Problem Set 2   |   ','Footer',align='center')
    field=x('w','fldSimple',instr=' PAGE ');field.append(run('1'));p.append(field);footer.append(p)
    header=x('w','hdr');header.append(paragraph('Quantitative Investing · Fall 2026','Footer',align='right'))
    rels=E.Element('{'+PKG+'}Relationships')
    for ident,target,kind in [('styles','styles.xml','styles'),('settings','settings.xml','settings'),('footer','footer1.xml','footer'),('header','header1.xml','header')]+[(f'figure{i}',f'media/figure{i}.png','image') for i in range(1,5)]:
        rel=E.SubElement(rels,'{'+PKG+'}Relationship',Id=ident,Target=target,Type=R+'/'+kind)
    package_rels=E.Element('{'+PKG+'}Relationships');E.SubElement(package_rels,'{'+PKG+'}Relationship',Id='doc',Type=R+'/officeDocument',Target='word/document.xml')
    ct=E.Element('{http://schemas.openxmlformats.org/package/2006/content-types}Types',nsmap={None:'http://schemas.openxmlformats.org/package/2006/content-types'})
    for ext,kind in [('rels','application/vnd.openxmlformats-package.relationships+xml'),('xml','application/xml'),('png','image/png')]:E.SubElement(ct,'{'+ct.nsmap[None]+'}Default',Extension=ext,ContentType=kind)
    parts={'word/document.xml':root,'word/styles.xml':styles_xml(),'word/settings.xml':settings,'word/header1.xml':header,'word/footer1.xml':footer,'word/_rels/document.xml.rels':rels,'_rels/.rels':package_rels}
    for part,kind in [('document','document.main'),('styles','styles'),('settings','settings'),('header1','header'),('footer1','footer')]:
        E.SubElement(ct,'{'+ct.nsmap[None]+'}Override',PartName='/word/'+part+'.xml',ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.'+kind+'+xml')
    docx=out/'PS2_editable_submission.docx'
    with zipfile.ZipFile(docx,'x',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',xml(ct))
        for path,element in parts.items():z.writestr(path,xml(element))
        for i,path in enumerate(images,1):z.writestr(f'word/media/figure{i}.png',path.read_bytes())
    # Check native structures and every CSV cell, without numerical recomputation.
    with zipfile.ZipFile(docx) as z:
        tree=E.fromstring(z.read('word/document.xml'));tables=tree.findall('.//{'+W+'}tbl')
        if len(tables)!=7:raise ValueError('Expected exactly seven native editable tables')
        checked_cells=0
        for table,expected in zip(tables,table_expected):
            rows=table.findall('{'+W+'}tr')
            for row,record in zip(rows,expected):
                cells=[''.join(c.itertext()) for c in row.findall('{'+W+'}tc')]
                if cells!=record['cells']:raise ValueError('DOCX table differs from saved CSV')
                checked_cells+=len(cells)
            if len(rows)!=len(expected):raise ValueError('Word table row count mismatch')
        for i,path in enumerate(images,1):
            if z.read(f'word/media/figure{i}.png')!=path.read_bytes():raise ValueError('Embedded figure changed')
        if len(tree.findall('.//{'+M+'}oMathPara'))!=10:raise ValueError('Display equations missing')
    put(out/'table_expected.json',table_expected);put(out/'equation_sources.json',paragraph_sources)
    put(out/'build.json',{'docx':docx.name,'native_tables':7,'display_OMML_equations':10,'inline_OMML_expressions':len(tree.findall('.//{'+M+'}oMath'))-10,
        'verified_table_cells':checked_cells,'original_images':4,'new_regressions':0,'PDF_text_extraction':False,
        'source_hashes':{str(p.relative_to(ROOT)):sha(p) for p in input_paths},'notes':'Nine original display equations plus a native matrix definition of the same three-factor vector; all original textual content retained.'})
    print('DOCX_CREATED='+str(docx),flush=True);return out


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--submission',type=Path,required=True);p.add_argument('--revision',type=Path,required=True)
    args=p.parse_args();stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    build(args.submission.resolve(),args.revision.resolve(),args.submission.resolve().parent/('word_submission_'+stamp))
