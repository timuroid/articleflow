"""Portable inter-block spacing evidence; empty paragraphs belong to boundaries."""
import copy
from .docx_engine import NS, paragraph_text, parse_xml
from . import typography019 as t
from .representation021 import plain


def empty_paragraph(node):
    return plain(node) and not paragraph_text(node) and node.find('w:pPr/w:numPr',NS) is None and node.find('w:pPr/w:sectPr',NS) is None


def preceding_profiles(body, index, resolver):
    nodes=[]
    while index>0 and empty_paragraph(body[index-1]):
        index-=1; nodes.insert(0,body[index])
    return [t.measure(n,resolver,'body.spacing') for n in nodes]


def following_profiles(body, index, resolver):
    nodes=[]; index+=1
    while index<len(body) and empty_paragraph(body[index]):
        nodes.append(body[index]); index+=1
    return [t.measure(n,resolver,'body.spacing') for n in nodes]


def spacing_node(profile, resolver):
    node=t.prop('p');t.apply(node,profile,resolver,'body.spacing')
    return node


def apply_boundaries(ordered, pending, resolver):
    changes=[];warnings=[]
    for node, block, _, key, style in pending:
        if style and node.tag==t.tag('tbl') and 'trailing_spacing' in style:
            wanted=style['trailing_spacing'];index=ordered.index(node)+1;end=index
            while end<len(ordered) and empty_paragraph(ordered[end]):end+=1
            existing=ordered[index:end]
            if len(wanted)>3 or len(existing)>len(wanted):
                warnings.append(f"Интервал после таблицы требует проверки ({block['id']})")
                continue
            for n,profile in zip(existing,wanted):t.apply(n,profile,resolver,'body.spacing')
            new=[spacing_node(p,resolver) for p in wanted[len(existing):]]
            ordered[end:end]=new
            if new:changes.append({'block_id':block['id'],'kind':'table_spacing','inserted_empty_paragraphs':len(new),'text_preserved':True})
            continue
        if not style or not key.startswith('body.heading.') or 'leading_spacing' not in style:continue
        wanted=style['leading_spacing']
        if len(wanted)>3:
            warnings.append(f"Интервал перед заголовком требует проверки ({block['id']})");continue
        index=ordered.index(node); start=index
        while start>0 and empty_paragraph(ordered[start-1]):start-=1
        existing=ordered[start:index]
        if len(existing)>len(wanted):
            warnings.append(f"Перед заголовком больше пустых строк, чем в образце ({block['id']})");continue
        # Existing empty source paragraphs remain accounted for; no double gaps.
        for n,profile in zip(existing,wanted):t.apply(n,profile,resolver,'body.spacing')
        new=[spacing_node(p,resolver) for p in wanted[len(existing):]]
        for n in new:
            # Keep a pure layout spacer with its following heading on a page break.
            pp=n.find('w:pPr',NS)
            if t.child(pp,'keepNext') is None:pp.append(t.prop('keepNext'))
            t._replace(n,'pPr',parse_xml(t.stable_xml(pp).encode()))
        ordered[index:index]=new
        if new:changes.append({'block_id':block['id'],'kind':'heading_spacing','inserted_empty_paragraphs':len(new),'text_preserved':True})
    return changes,warnings
