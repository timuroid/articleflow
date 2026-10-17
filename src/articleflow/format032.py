"""Independent exact property audit; complements pixels without relying on font substitution."""
import argparse,json
from pathlib import Path
from articleflow.docx_engine import NS,load_package,parse_xml,paragraph_text,dump,digest
from articleflow.typography019 import Resolver
from articleflow.stories026 import roots


def properties(node):
    if node is None:return None
    attrs=tuple(sorted((k,v) for k,v in node.attrib.items() if not k.rsplit('}',1)[-1].startswith('rsid')))
    children=[properties(c) for c in node]
    if node.tag in {'{'+NS['w']+'}pPr','{'+NS['w']+'}rPr'} and not attrs and not children and not node.text:return None
    # OOXML property ordering is retained; this audit never rounds values.
    return [node.tag,attrs,node.text or '',children]


def fingerprint(source):
    parts=load_package(source);resolver=Resolver(parts);result={}
    for name,root in roots(parts):
        paragraphs=[];drawings=[]
        for p in root.findall('.//w:p',NS):
            pp,_=resolver.resolve(p);spans=[]
            for r in p.xpath('.//w:r[not(ancestor::m:oMath)]',namespaces=NS):
                _,rp=resolver.resolve(p,r);fmt=properties(rp);length=len(paragraph_text(r))
                if length:
                    if spans and spans[-1][1]==fmt:spans[-1][0]+=length
                    else:spans.append([length,fmt])
                for drawing in r.findall('w:drawing',NS):drawings.append([fmt,properties(drawing)])
            paragraphs.append([properties(pp),spans])
        layout=[properties(n) for n in root.xpath('.//w:tblPr | .//w:tblGrid | .//w:trPr | .//w:tcPr | .//w:sdtPr | .//w:sdtEndPr | ./w:sectPr',namespaces=NS)]
        result[name]={'paragraphs':paragraphs,'layout':layout,'drawings':drawings}
    resources={name:digest(raw) for name,raw in parts.items() if name in {'word/styles.xml','word/numbering.xml','word/settings.xml','word/fontTable.xml'} or name.startswith('word/theme/')}
    return {'stories':result,'resources':resources}


def audit(source,target):
    left_fp,right_fp=fingerprint(source),fingerprint(target);a,b=left_fp['stories'],right_fp['stories'];rows=[]
    resources_exact=left_fp['resources']==right_fp['resources']
    for name in sorted(set(a)|set(b)):
        left,right=a.get(name,{}),b.get(name,{})
        rows.append({'part':name,**{group+'_exact':left.get(group)==right.get(group) for group in ['paragraphs','layout','drawings']},'paragraph_count_source':len(left.get('paragraphs',[])),'paragraph_count_target':len(right.get('paragraphs',[]))})
    return {'resources_exact':resources_exact,'property_exact':resources_exact and all(all(row[g+'_exact'] for g in ['paragraphs','layout','drawings']) for row in rows),'parts':rows,'scope':'Resolved paragraph/run properties and direct table/section/content-control/drawing properties. Does not certify arbitrary unsupported Word features or cross-renderer pagination.'}

