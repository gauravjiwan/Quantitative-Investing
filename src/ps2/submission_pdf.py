"""Lossless page assembly for this repository's classic-xref ReportLab PDFs.

This deliberately rejects object streams, encryption and incremental revisions.
It is not a general PDF parser. Compressed page/image/font streams remain bytes.
"""
from dataclasses import dataclass
import re


@dataclass
class ClassicPDF:
    objects: dict
    pages: list


def read_classic(data):
    last=re.search(rb'startxref\s+(\d+)\s+%%EOF\s*$',data)
    if not data.startswith(b'%PDF-') or not last:raise ValueError('Not a complete classic PDF')
    tail=data[int(last[1]):]
    header=re.match(rb'xref\s+0\s+(\d+)\s*\r?\n',tail)
    if not header:raise ValueError('Only single classic xref tables are supported')
    lines=tail[header.end():].splitlines();count=int(header[1]);offsets={}
    for i,line in enumerate(lines[:count]):
        row=re.fullmatch(rb'(\d{10}) (\d{5}) ([fn])\s*',line)
        if not row:raise ValueError('Invalid xref entry')
        if row[3]==b'n':
            if row[2]!=b'00000':raise ValueError('Nonzero object generation')
            offsets[i]=int(row[1])
    trailer=tail[header.end():].split(b'trailer',1)[1]
    if re.search(rb'/(Encrypt|Prev|XRefStm)\b',trailer):raise ValueError('Unsupported PDF trailer')
    root=re.search(rb'/Root\s+(\d+)\s+0\s+R',trailer)
    if not root:raise ValueError('Missing PDF root')
    objects={};ordered=sorted(offsets.items(),key=lambda item:item[1])
    for pos,(number,start) in enumerate(ordered):
        end=ordered[pos+1][1] if pos+1<len(ordered) else int(last[1])
        chunk=data[start:end];h=re.match(str(number).encode()+rb' 0 obj\s*\r?\n',chunk)
        if not h or not chunk.rstrip().endswith(b'endobj'):raise ValueError('Object boundary mismatch')
        objects[number]=chunk[h.end():chunk.rfind(b'endobj')]
    pages_root=re.search(rb'/Pages\s+(\d+)\s+0\s+R',objects[int(root[1])])
    if not pages_root:raise ValueError('Missing page tree')
    visited=set()
    def visit(n):
        if n in visited:raise ValueError('Cyclic page tree')
        visited.add(n);body=objects[n]
        if re.search(rb'/Type\s*/Page\b',body):return [n]
        kids=re.search(rb'/Kids\s*\[(.*?)\]',body,re.S)
        if not kids:raise ValueError('Unsupported page tree')
        result=[]
        for child in re.findall(rb'(\d+)\s+0\s+R',kids[1]):result.extend(visit(int(child)))
        return result
    pages=visit(int(pages_root[1]));return ClassicPDF(objects,pages)


def rewrite_references(data,mapping):
    """Rewrite references outside PDF literal/hex strings and comments."""
    parts=[];i=0
    while i<len(data):
        start=i;c=data[i]
        if c==40:
            i+=1;depth=1
            while i<len(data) and depth:
                if data[i]==92:i+=2;continue
                if data[i]==40:depth+=1
                elif data[i]==41:depth-=1
                i+=1
        elif c==37:
            end=data.find(b'\n',i);i=len(data) if end<0 else end+1
        elif data[i:i+2]==b'<<':i+=2
        elif c==60:
            end=data.find(b'>',i)
            if end<0:raise ValueError('Unterminated hex string')
            i=end+1
        elif 48<=c<=57 and (i==0 or data[i-1] in b' \t\r\n[<>'):
            ref=re.match(rb'(\d+)\s+0\s+R\b',data[i:])
            if ref:
                if int(ref[1]) not in mapping:raise ValueError('Dangling PDF reference')
                parts.append(f'{mapping[int(ref[1])]} 0 R'.encode());i+=ref.end();continue
            i+=1
        else:i+=1
        parts.append(data[start:i])
    return b''.join(parts)


def split_stream(body):
    marker=re.search(rb'\bstream\r?\n',body)
    if not marker:return body,b'',b''
    length=re.search(rb'/Length\s+(\d+)\s*(?=/|>>)',body[:marker.start()])
    if not length:raise ValueError('Only direct stream lengths are supported')
    start=marker.end();end=start+int(length[1])
    if not re.match(rb'\s*endstream',body[end:]):raise ValueError('Stream length mismatch')
    return body[:start],body[start:end],body[end:]


def stream_bytes(body):return split_stream(body)[1]


def combine(main_data,baseline_data,main_count=4):
    main=read_classic(main_data);baseline=read_classic(baseline_data)
    if len(main.pages)!=main_count or len(baseline.pages)!=15:raise ValueError('Unexpected baseline/main page counts')
    documents=[main,baseline];mappings=[];next_number=1
    for doc in documents:
        mapping={n:i+next_number for i,n in enumerate(sorted(doc.objects))};mappings.append(mapping);next_number+=len(mapping)
    page_root,catalog=next_number,next_number+1
    selected=[(0,n) for n in main.pages]+[(1,n) for n in baseline.pages[4:]]
    selected_ids={(d,n) for d,n in selected};objects={}
    for d,doc in enumerate(documents):
        for n,body in doc.objects.items():
            head,stream,tail=split_stream(body)
            head=rewrite_references(head,mappings[d]);tail=rewrite_references(tail,mappings[d])
            if (d,n) in selected_ids:
                head,substitutions=re.subn(rb'/Parent\s+\d+\s+0\s+R',f'/Parent {page_root} 0 R'.encode(),head)
                if substitutions!=1:raise ValueError('Expected one page parent')
            objects[mappings[d][n]]=head+stream+tail
    kids=' '.join(f'{mappings[d][n]} 0 R' for d,n in selected)
    objects[page_root]=f'<< /Type /Pages /Count {len(selected)} /Kids [ {kids} ] >>\n'.encode()
    objects[catalog]=f'<< /Type /Catalog /Pages {page_root} 0 R >>\n'.encode()
    output=bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n');offsets=[0]
    for n in range(1,catalog+1):
        offsets.append(len(output));output.extend(f'{n} 0 obj\n'.encode()+objects[n]+b'\nendobj\n')
    start=len(output);output.extend(f'xref\n0 {catalog+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:output.extend(f'{offset:010d} 00000 n \n'.encode())
    output.extend(f'trailer\n<< /Size {catalog+1} /Root {catalog} 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    result=bytes(output);merged=read_classic(result)
    if len(merged.pages)!=15:raise ValueError('Assembled page count differs')
    preserved=[]
    for n in baseline.pages[4:]:
        old=re.search(rb'/Contents\s+(\d+)\s+0\s+R',baseline.objects[n])
        if not old:raise ValueError('Expected one original exhibit content stream')
        old_id=int(old[1]);new_id=mappings[1][old_id]
        if stream_bytes(baseline.objects[old_id])!=stream_bytes(merged.objects[new_id]):raise ValueError('Exhibit page stream changed')
        preserved.append(new_id)
    return result,{'main_pages':4,'total_pages':15,'exhibit_pages':11,'original_exhibit_content_streams_preserved':len(preserved)}
