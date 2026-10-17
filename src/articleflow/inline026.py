"""Validated semantic inline ranges; source typography never defines a runtime role."""
import copy
import re
from .docx_engine import DocumentError


def validate(response, blocks, definitions=None):
    if definitions is None:
        definitions=response.get('inline_roles',{})
    if not isinstance(definitions,dict) or len(definitions)>40:
        raise DocumentError('INLINE_ROLES_SCHEMA')
    for role,description in definitions.items():
        if not re.fullmatch('[a-z][a-z0-9_]{0,63}',role) or role=='plain' or not isinstance(description,str) or not 3<=len(description)<=600:
            raise DocumentError('INLINE_ROLE_INVALID')
    rows=response.get('inline',[])
    if not isinstance(rows,list) or len(rows)>20000:raise DocumentError('INLINE_SCHEMA')
    result={b['id']:[] for b in blocks}
    for row in rows:
        if not isinstance(row,dict) or set(row) not in ({'paragraph','start','end','role','quote'},{'paragraph','occurrence','role','quote'}):raise DocumentError('INLINE_SCHEMA')
        n=row['paragraph']
        if type(n)!=int or not 1<=n<=len(blocks):raise DocumentError('INLINE_RANGE')
        b=blocks[n-1];text=b['text']
        if 'occurrence' in row:
            occurrence=row['occurrence'];quote=row['quote']
            if type(occurrence)!=int or not 1<=occurrence<=len(text) or not isinstance(quote,str) or not quote:raise DocumentError('INLINE_ANCHOR_INVALID')
            a=-1
            for _ in range(occurrence):
                a=text.find(quote,a+1)
                if a<0:raise DocumentError('INLINE_ANCHOR_NOT_FOUND')
            z=a+len(quote)
        else:a,z=row['start'],row['end']
        if any(type(v)!=int for v in (a,z)) or not 0<=a<z<=len(text) or row['role'] not in definitions:raise DocumentError('INLINE_RANGE')
        if text[a:z]!=row['quote']:raise DocumentError('INLINE_QUOTE_MISMATCH')
        result[b['id']].append({'start':a,'end':z,'role':row['role']})
    for spans in result.values():
        spans.sort(key=lambda s:s['start'])
        if any(a['end']>b['start'] for a,b in zip(spans,spans[1:])):raise DocumentError('INLINE_OVERLAP')
    return result


def overlay(semantics, annotations):
    result={}
    for bid,spans in semantics.items():
        marks=annotations.get(bid,[]);out=[]
        for span in spans:
            boundaries=sorted({span['start'],span['end']}|{v for m in marks for v in (m['start'],m['end']) if span['start']<v<span['end']})
            for a,z in zip(boundaries,boundaries[1:]):
                role=next((m['role'] for m in marks if m['start']<=a and z<=m['end']),'plain')
                out.append({'start':a,'end':z,'features':{**span['features'],'inline_role':role}})
        result[bid]=out
    return result
