"""Inventory downloaded DOCX without exposing its text; optionally render page counts."""
import argparse,json
from pathlib import Path
from collections import Counter
from articleflow.docx_engine import load_package,parse_xml,NS,digest,dump
from articleflow.research import render_pdf


def inventory(source,render_folder=None):
    parts=load_package(source,allow_unsupported=True)
    stories=[parse_xml(raw) for name,raw in parts.items() if name=='word/document.xml' or name.startswith(('word/header','word/footer')) and name.endswith('.xml')]
    queries={'paragraphs':'.//w:p','tables':'.//w:tbl','sections':'.//w:sectPr','fields':'.//w:fldChar','drawings':'.//w:drawing','floating_drawings':'.//wp:anchor','text_boxes':'.//w:txbxContent','content_controls':'.//w:sdt','proofing':'.//w:proofErr'}
    row={'id':source.stem,'sha256':digest(source.read_bytes()),'counts':{k:sum(len(r.xpath(q,namespaces=NS)) for r in stories) for k,q in queries.items()}}
    if render_folder is not None:
        import pymupdf as fitz
        pdf=render_pdf(source,render_folder)
        with fitz.open(pdf) as document:row['pages']=len(document)
    return row

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('inputs',type=Path,nargs='+');p.add_argument('--output',type=Path,required=True);p.add_argument('--render-root',type=Path)
    a=p.parse_args();rows=[]
    for source in a.inputs:
        try:rows.append(inventory(source,a.render_root/source.stem if a.render_root else None))
        except Exception as e:rows.append({'id':source.stem,'status':'failed','code':str(e) if type(e).__name__=='DocumentError' else type(e).__name__})
    dump(a.output,rows)
