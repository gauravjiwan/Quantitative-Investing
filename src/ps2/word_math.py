"""Native, editable Office Math (OMML), authored from the PS2 equation sources."""
from lxml import etree as E
from copy import deepcopy
M='http://schemas.openxmlformats.org/officeDocument/2006/math'
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS={'m':M,'w':W}


def node(tag,*children,**attrs):
    element=E.Element('{'+M+'}'+tag)
    for k,v in attrs.items():element.set('{'+M+'}'+k,str(v))
    for c in children:element.append(deepcopy(c))
    return element


def r(text,plain=False):
    result=node('r')
    if plain:result.append(node('rPr',node('sty',val='p')))
    t=node('t');t.text=text;t.set('{http://www.w3.org/XML/1998/namespace}space','preserve');result.append(t)
    return result


def seq(*items):return node('e',*(r(x,True) if isinstance(x,str) else x for x in items))
def sub(base,index):return node('sSub',node('e',base),node('sub',r(index) if isinstance(index,str) else index))
def sup(base,index):return node('sSup',node('e',base),node('sup',r(index) if isinstance(index,str) else index))
def scripts(base,index,power):return node('sSubSup',node('e',base),node('sub',r(index)),node('sup',r(power)))
def fraction(a,b):return node('f',node('fPr',node('type',val='bar')),node('num',r(a) if isinstance(a,str) else a),node('den',r(b) if isinstance(b,str) else b))
def delim(e,left='(',right=')'):return node('d',node('dPr',node('begChr',val=left),node('endChr',val=right)),e)
def radical(e):return node('rad',node('radPr',node('degHide',val='1')),node('deg'),e)
def var(name,index=None,power=None):
    if index is not None and power is not None:return scripts(r(name),index,power)
    if index is not None:return sub(r(name),index)
    if power is not None:return sup(r(name),power)
    return r(name)
def total(index,e):return node('nary',node('naryPr',node('chr',val='∑'),node('limLoc',val='subSup'),node('supHide',val='1')),node('sub',r(index)),node('sup'),e)


def factor_vector():
    cells=[node('e',var(name,'s')) for name in ['Mkt−RF','HML','SMB']]
    matrix=node('m',node('mPr',node('baseJc',val='center'),node('mcs',node('mc',node('mcPr',node('count',val='3'),node('mcJc',val='center'))))),node('mr',*cells))
    return seq(var('F','s'),' = ',sup(delim(node('e',matrix),left='[',right=']'),'′'))


def display_equations():
    """Nine original displays, plus an explicit definition of their factor vector."""
    daily=seq(var('r','i,d','e'),' = ',var('α','i'),' + ',var('β','i'),' ',var('r','m,d','e'),' + ',var('ε','i,d'))
    predictive=seq(var('β','i,t+1','real'),' = ',var('γ','0'),' + ',var('γ','1'),' ',var('b','i,t'),' + ',var('u','i,t+1'))
    error=seq(var('β','i,t+1','real'),' − ',var('b','i,t'))
    rmse=seq(r('RMSE',True),' = ',radical(seq(fraction('1','T'),' ',total('t',seq(total('i',seq(var('ω','i,t'),' ',sup(delim(error),'2'))))))))
    joint=seq(var('r','i,s','e'),' = ',var('α','i,t'),' + ',var('b','i,t','′'),' ',var('F','s'),' + ',var('ε','i,s'),';  ',r('forecast ',True),var('r','i,t+1','e'),' = ',var('b','i,t','′'),' ',var('λ','t+1|t'))
    forecast=seq(var('F','s+1'),' = a + A ',var('F','s'),' + ',var('η','s+1'),';   ',var('λ','t+1|t'),' = ',var('a','t'),' + ',var('A','t'),' ',var('F','t'))
    pseudo=seq(r('Pseudo-',True),sup(r('R'),'2'),' = 1 − ',fraction(sub(r('MSE',True),'model'),sub(r('MSE',True),'benchmark')))
    objective=seq(var('r','t+1','e'),' = ',var('X','t'),' ',var('f','t+1'),' + ',var('u','t+1'),';   ',node('limLow',node('e',r('min',True)),node('lim',r('f'))),' ',total('i',seq(radical(seq(var('ME','i,t'))),' ',sup(delim(seq(var('r','i,t+1','e'),' − ',var('X','i,t'),' f')),'2'))))
    projection=seq('a = ',sup(delim(seq('C′WC')),'−1'),'C′Wz;   ',sup(r('z'),'⊥'),' = z − Ca;   C′W',sup(r('z'),'⊥'),' = 0')
    fwl=seq(var('r','t+1','e'),' = Cδ + γz + u;   ',var('r','t+1','e'),' = ',sup(r('α'),'⊥'),'1 + ',sup(r('γ'),'⊥'),sup(r('z'),'⊥'),' + v')
    return [daily,predictive,rmse,joint,forecast,pseudo,objective,projection,fwl]


def omath(e):return node('oMath',*list(e))
def display(e):return node('oMathPara',node('oMathParaPr',node('jc',val='center')),omath(e))
