"""Render the saved English report using the bundled ReportLab runtime."""
from pathlib import Path
from xml.sax.saxutils import escape
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4,landscape
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Image,LongTable,TableStyle,PageBreak,KeepTogether
from reportlab.lib.enums import TA_LEFT
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'
PAGE=landscape(A4);WIDTH=PAGE[0]-80
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='BodyPS1',fontName='Helvetica',fontSize=9.2,leading=13,spaceAfter=8,allowWidows=0,allowOrphans=0))
styles.add(ParagraphStyle(name='CellPS1',fontName='Helvetica',fontSize=7,leading=9))
styles.add(ParagraphStyle(name='HeadCellPS1',fontName='Helvetica-Bold',fontSize=7,leading=9,textColor=colors.white))
styles['Heading1'].fontSize=22;styles['Heading1'].leading=26;styles['Heading1'].textColor=colors.HexColor('#143852')
styles['Heading2'].fontSize=15;styles['Heading2'].textColor=colors.HexColor('#143852');styles['Heading2'].spaceBefore=14
styles['Heading3'].fontSize=11;styles['Heading3'].textColor=colors.HexColor('#143852')
for heading in ['Heading1','Heading2','Heading3']:styles[heading].keepWithNext=True

def inline(t):
 t=escape(t).replace('—','-').replace('–','-').replace('−','-').replace('×','x').replace('’',"'").replace('“','"').replace('”','"')
 t=re.sub(r'\*\*(.*?)\*\*',r'<b>\1</b>',t);t=re.sub(r'`([^`]+)`',r'<font name="Courier">\1</font>',t)
 t=re.sub(r'\[([^]]+)\]\((https://[^)]+)\)',r'<link href="\2" color="#176c9b">\1</link>',t)
 return t

story=[];table_rows=[]
def flush_table():
 if not table_rows:return
 rows=[table_rows[0]]+table_rows[2:];n=len(rows[0]);weights=[]
 for j in range(n):weights.append(min(23,max(9,max(len(row[j]) if j<len(row) else 0 for row in rows))))
 widths=[WIDTH*x/sum(weights) for x in weights]
 rendered=[[Paragraph(inline(cell.replace('_',' ') if i==0 else cell),styles['HeadCellPS1' if i==0 else 'CellPS1']) for cell in row] for i,row in enumerate(rows)]
 t=LongTable(rendered,colWidths=widths,repeatRows=1,hAlign='LEFT')
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#143852')),('VALIGN',(0,0),(-1,-1),'TOP'),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f0f4f7')]),('LINEBELOW',(0,0),(-1,0),.5,colors.HexColor('#cad4dc')),('BOTTOMPADDING',(0,0),(-1,-1),3),('TOPPADDING',(0,0),(-1,-1),3),('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4)]))
 story.extend([t,Spacer(1,10)]);table_rows.clear()

for line in (OUT/'ps1_report.md').read_text().splitlines():
 if line.startswith('|'):table_rows.append([x.strip() for x in line.strip('|').split('|')]);continue
 flush_table()
 if not line.strip():continue
 image=re.fullmatch(r'!\[([^]]+)\]\((figures/[^)]+)\)',line)
 if image:
  im=Image(str(OUT/image.group(2)));scale=min(WIDTH/im.imageWidth,330/im.imageHeight);im.drawWidth=im.imageWidth*scale;im.drawHeight=im.imageHeight*scale
  story.append(KeepTogether([im,Spacer(1,4),Paragraph(inline(image.group(1)),styles['BodyPS1'])]));continue
 if line.startswith('#'):
  level=len(line)-len(line.lstrip('#'))
  if level==2 and line.startswith('## Question'):story.append(PageBreak())
  story.append(Paragraph(inline(line[level:].strip()),styles['Heading'+str(min(3,level))]));continue
 story.append(Paragraph(inline(line),styles['BodyPS1']))
flush_table()
def footer(canvas,doc):
 canvas.saveState();canvas.setFillColor(colors.HexColor('#667788'));canvas.setFont('Helvetica',8);canvas.drawString(40,22,'Quantitative Investing PS1 | WRDS/French snapshots: 2026-09-27');canvas.drawRightString(PAGE[0]-40,22,str(doc.page));canvas.restoreState()
path=OUT/'ps1_report.pdf'
SimpleDocTemplate(str(path),pagesize=PAGE,rightMargin=40,leftMargin=40,topMargin=34,bottomMargin=36,title='Quantitative Investing Problem Set 1').build(story,onFirstPage=footer,onLaterPages=footer)
print(path)
