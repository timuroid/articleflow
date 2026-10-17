"""Whole-document mutation controls, including the reported table-gap defect."""
from .docx_engine import NS,load_package,parse_xml,xml_bytes,write_package
from .typography019 import tag
from .templateagent022 import _negative_controls
from .research import render_pdf,compare_pixels
from .integrity023 import check


def verify(source,golden,folder):
    result=_negative_controls(source,golden,folder)
    parts=load_package(source);root=parse_xml(parts['word/document.xml']);body=root.find('w:body',NS)
    for i,node in enumerate(body):
        if i and body[i-1].tag==tag('tbl') and node.tag==tag('p'):
            spacing=node.find('w:pPr/w:spacing',NS)
            if spacing is not None and int(spacing.get(tag('before'),'0'))>0:
                spacing.set(tag('before'),'0');parts['word/document.xml']=xml_bytes(root)
                path=folder/'negative-table-before.docx';write_package(path,parts)
                metric=compare_pixels(golden,render_pdf(path,folder/'negative-table-before'))
                result.append({'kind':'after_table_paragraph_space_before','detected':not metric['pixel_exact']});break
    parts=load_package(source);root=parse_xml(parts['word/document.xml']);text=root.find('.//w:t',NS)
    if text is not None:
        text.text=(text.text or '')+' CHANGED';parts['word/document.xml']=xml_bytes(root)
        path=folder/'negative-content.docx';write_package(path,parts)
        result.append({'kind':'scientific_content_change','detected':not check(source,path)['content_exact']})
    return result
