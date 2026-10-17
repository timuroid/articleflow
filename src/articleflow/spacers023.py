"""Learn empty layout paragraphs from semantic boundaries, never positions."""
import copy
from collections import defaultdict
from .docx_engine import DocumentError
from .rules023 import key


def boundaries(content,assignments):
    by_id={b['id']:b for b in content['blocks']}
    def empty(n):return n['kind']=='paragraph' and not by_id[n['id']]['text'] and not by_id[n['id']]['atoms'] and not by_id[n['id']].get('section_boundary')
    def label(n):
        if n is None:return 'EDGE'
        if n['kind']=='paragraph':return 'paragraph:'+assignments[n['id']]
        return n['kind']
    previous=None;gap=[];rows=[]
    for n in content['structure']:
        if empty(n):gap.append(n['id']);continue
        if n['kind']=='marker':
            # A bookmark is scientific structure, not a disposable spacer.
            previous=n;gap=[];continue
        rows.append({'when':{'previous':label(previous),'next':label(n)},'ids':gap,'before':n['id']})
        previous=n;gap=[]
    rows.append({'when':{'previous':label(previous),'next':'EDGE'},'ids':gap,'before':None})
    return rows


def fit(samples):
    groups=defaultdict(list)
    for content,plan in samples:
        assignments={b['id']:b['role'] for b in plan['blocks']};by_id={b['id']:b for b in plan['blocks']}
        for boundary in boundaries(content,assignments):
            target=[{'role':assignments[bid],'style':by_id[bid]['paragraph_style']} for bid in boundary['ids']]
            groups[key(boundary['when'])].append(target)
    rules=[];conflicts=[]
    for condition,examples in sorted(groups.items()):
        if len({key(v) for v in examples})!=1:
            conflicts.append({'kind':'spacer_boundary','when':__import__('json').loads(condition),'variants':len({key(v) for v in examples})})
        elif examples[0]:
            rules.append({'when':__import__('json').loads(condition),'paragraphs':examples[0]})
    return rules,conflicts


def restore(content,assignments,semantics,package,template):
    result=copy.deepcopy(content);assigned=dict(assignments);semantic=copy.deepcopy(semantics)
    forced={};inserted=[];observed=boundaries(content,assignments)
    for rule in package.get('spacers',[]):
        if set(rule)!= {'when','paragraphs'} or set(rule['when'])!={'previous','next'}:
            raise DocumentError('SPACER_RULE_INVALID')
        for boundary in observed:
            if boundary['when']!=rule['when']:continue
            if boundary['ids']:
                # Existing intentional blanks are not silently destroyed or doubled.
                if len(boundary['ids'])!=len(rule['paragraphs']):raise DocumentError('SPACER_INPUT_AMBIGUOUS')
                for bid,profile in zip(boundary['ids'],rule['paragraphs']):
                    assigned[bid]=profile['role'];semantic[bid]=[];forced[bid]=profile['style']
                continue
            index=next((i for i,n in enumerate(result['structure']) if n.get('id')==boundary['before']),len(result['structure']))
            for offset,profile in enumerate(rule['paragraphs']):
                role=template['roles'].get(profile['role'])
                if role is None or profile['style'] not in role['paragraph_styles']:raise DocumentError('SPACER_STYLE_INVALID')
                bid=f'spacer-added-{len(inserted)+1}'
                if any(b['id']==bid for b in result['blocks']):raise DocumentError('SPACER_ID_COLLISION')
                result['blocks'].append({'id':bid,'text':'','atoms':[]})
                result['structure'].insert(index+offset,{'kind':'paragraph','id':bid})
                assigned[bid]=profile['role'];semantic[bid]=[];forced[bid]=profile['style'];inserted.append(bid)
    positions=[i for i,n in enumerate(result['structure']) if n.get('id') in inserted]
    return result,assigned,semantic,forced,positions
