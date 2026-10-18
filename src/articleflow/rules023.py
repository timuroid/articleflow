"""Lossless property rules keyed only by semantic and structural features.

Training assignments never enter the runtime package. Conflicting observations
are explicit unresolved groups, not majority choices. Inline emphasis is an
announced additional DOCX input (not pure-text reconstruction).
"""
import copy
import json
import unicodedata
from collections import defaultdict
from pathlib import Path

from .catalogue import VERSION, validate_catalogue_plan
from .docx_engine import NS, DocumentError, digest, flag, load_package, paragraph_text, parse_xml
from .typography019 import Resolver, tag


def key(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def semantic_spans(source):
    from .sandbox034 import ACTIVE
    if ACTIVE.get():
        from .engine034 import simple
        return simple(ACTIVE.get(),"semantics",{}, {"source.docx":source})
    parts = load_package(source)
    root = parse_xml(parts['word/document.xml'])
    resolver = Resolver(parts)
    result = {}
    from .stories026 import paragraphs
    for i, p in enumerate(paragraphs(parts)):
        spans = []; offset = 0
        for r in p.xpath('.//w:r[not(ancestor::m:oMath)]', namespaces=NS):
            text = paragraph_text(r)
            if not text: continue
            _, rp = resolver.resolve(p, r)
            va = rp.find('w:vertAlign', NS)
            language=rp.find('w:lang',NS)
            attrs = {'bold': bool(flag(rp, 'b')), 'italic': bool(flag(rp, 'i')),
                     'vertical': va.get(tag('val')) if va is not None else 'baseline',
                     'language':key(dict(language.attrib)) if language is not None else '',
                     'hyperlink': bool(r.xpath('ancestor::w:hyperlink', namespaces=NS)),
                     'field_control': ','.join(n.get(tag('fldCharType'),'instruction') for n in r if n.tag in {tag('fldChar'),tag('instrText')}) or 'none'}
            end = offset + len(text)
            if spans and spans[-1]['features'] == attrs: spans[-1]['end'] = end
            else: spans.append({'start': offset, 'end': end, 'features': attrs})
            offset = end
        result[f'b-{i+1:06d}'] = spans
    return result


def features(content, assignments):
    from .sandbox034 import ACTIVE
    if ACTIVE.get():
        from .engine034 import simple
        return simple(ACTIVE.get(),"features",{"content":content,"assignments":assignments},{})
    if set(assignments) != {b['id'] for b in content['blocks']}:
        raise DocumentError('SEMANTIC_COVERAGE')
    result = {'paragraph': {}, 'layout': {}, 'drawing': {}}
    texts={b['id']:b['text'] for b in content['blocks']}
    structural={b['id']:{'list_level':b.get('list_level',-1),'list_kind':b.get('list_kind','none'),'field_commands':b.get('field_commands','')} for b in content['blocks']}
    boundaries={b['id']:bool(b.get('section_boundary')) for b in content['blocks']}
    def language(text):
        cyr=sum('\u0400'<=c<='\u052f' for c in text)
        latin=sum('a'<=c.lower()<='z' for c in text)
        return 'cyrillic' if cyr>latin else 'latin' if latin else 'other'
    def roles(n):
        return [assignments[n['id']]] if n['kind']=='paragraph' else [r for c in n.get('children',[]) for r in roles(c)]
    def walk(nodes, depth=0, columns=0, column=0, band='outside', story_kind='body'):
        visible = [n for n in nodes if n['kind'] != 'marker']
        role_run=None;transition_language='other';previous_nonempty_language='other'
        for i,n in enumerate(visible):
            kind=n['kind']
            f={'depth': depth, 'columns': columns, 'column': column, 'row_band': band, 'story_kind':story_kind}
            if kind=='paragraph':
                current_role=assignments[n['id']]
                if texts[n['id']].strip():
                    if current_role!=role_run:
                        transition_language=previous_nonempty_language
                        role_run=current_role
                    previous_nonempty_language=language(texts[n['id']])
                f.update(role=assignments[n['id']],section_boundary=boundaries[n['id']], previous_kind=visible[i-1]['kind'] if i else 'START',
                         next_kind=visible[i+1]['kind'] if i+1<len(visible) else 'END',
                         previous_role=assignments.get(visible[i-1].get('id'),'OBJECT') if i else 'START',
                         next_role=assignments.get(visible[i+1].get('id'),'OBJECT') if i+1<len(visible) else 'END',
                         language=language(texts[n['id']]),role_transition_language=transition_language)
                f.update(structural[n['id']])
                result['paragraph'][n['id']]=f
            else:
                children=n.get('children',[])
                f.update(kind=kind, roles=','.join(sorted(set(roles(n)))))
                if kind=='table':
                    f['columns']=max((len(c.get('children',[])) for c in children if c['kind']=='row'),default=0)
                result['layout'][n['id']]=f
                if kind=='table':
                    for j,row in enumerate(children):
                        rb='only' if len(children)==1 else 'first' if j==0 else 'last' if j==len(children)-1 else 'middle'
                        walk([row],depth+1,f['columns'],0,rb,story_kind)
                elif kind=='row':
                    for j,cell in enumerate(children): walk([cell],depth,len(children),j,band,story_kind)
                else: walk(children,depth,columns,column,band,story_kind)
    walk(content['structure'])
    for story in content.get('stories',[]):
        walk(story['structure'],story_kind='header' if 'header' in story['part'] else 'footer')
    def atoms(sequence):
        for a in sequence:
            yield a
            yield from atoms(a.get('children',[]))
    for b in content['blocks']:
        for a in atoms(b['atoms']):
            if a['kind']=='drawing': result['drawing'][a['object_id']]=result['paragraph'][b['id']].copy()
    return result


def training_examples(content, plan, semantics):
    f=features(content,{b['id']:b['role'] for b in plan['blocks']})
    rows=[]
    content_by_id={b['id']:b for b in content['blocks']}
    for b in plan['blocks']:
        bid=b['id'];pf=f['paragraph'][bid]
        source=content_by_id[bid]
        if source['text'] or source['atoms'] or pf['depth'] or source.get('section_boundary') or pf['story_kind']!='body':
            rows.append({'kind':'paragraph','when':pf,'set':{'style':b['paragraph_style']},'id':bid,
                         'source_text_digest':digest(source['text'].encode())})
        for span in b['spans']:
            for semantic in semantics[bid]:
                a=max(span['start'],semantic['start']);z=min(span['end'],semantic['end'])
                if a<z: rows.append({'kind':'character','when':{**pf,'script':pf['language'],**semantic['features']},
                                    'set':{'style':span['style']},'id':bid,'range':[a,z]})
    for b in plan['layout']:
        rows.append({'kind':'layout','when':f['layout'][b['id']],'set':{'style':b['style']},'id':b['id']})
    for b in plan['objects']:
        rows.append({'kind':'drawing','when':f['drawing'][b['id']],
                     'set':{'drawing_style':b['drawing_style'],'run_style':b['run_style']},'id':b['id']})
    return rows


SPAN_GRAMMAR_SCHEMA='content-span-grammar-036'
SPAN_GRAMMAR_FIELDS=('role','inline_role','character_class')


def _character_class(char):
    """A finite lexical class, never the character or source run style."""
    if char.isspace():return 'space'
    if char in '-‐‑‒–—−':return 'dash'
    name=unicodedata.name(char,'')
    if 'CYRILLIC' in name:return 'cyrillic'
    if 'LATIN' in name:return 'latin'
    if 'GREEK' in name:return 'greek'
    if 'CJK UNIFIED IDEOGRAPH' in name:return 'han'
    category=unicodedata.category(char)
    if category.startswith('N'):return 'number'
    if category.startswith('P'):return 'punctuation'
    if category.startswith('S'):return 'symbol'
    return 'other'


def span_grammar_segments(content, assignments, semantics):
    """Partition text using only content classes and predicted semantic marks.

    Incoming run boundaries and their bold/italic/font/size/language properties
    are deliberately discarded. ``semantics`` is read only for ``inline_role``;
    adjacent pieces with the same role and lexical class merge back together.
    """
    result={}
    for block in content['blocks']:
        bid=block['id'];text=block['text'];segments=[];cursor=0
        for source_span in semantics.get(bid,[]):
            a,z=source_span['start'],source_span['end']
            if a!=cursor or type(z)!=int or not a<z<=len(text):
                raise DocumentError('SPAN_GRAMMAR_COVERAGE')
            inline_role=source_span['features'].get('inline_role','plain')
            if not isinstance(inline_role,str):raise DocumentError('SPAN_GRAMMAR_INLINE_ROLE')
            for offset in range(a,z):
                when={'role':assignments[bid],'inline_role':inline_role,
                      'character_class':_character_class(text[offset])}
                if segments and segments[-1]['end']==offset and segments[-1]['when']==when:
                    segments[-1]['end']=offset+1
                else:segments.append({'start':offset,'end':offset+1,'when':when})
            cursor=z
        if cursor!=len(text):raise DocumentError('SPAN_GRAMMAR_COVERAGE')
        result[bid]=segments
    return result


def span_grammar_examples(content, plan, assignments, semantics):
    """Observe target styles against the source-independent span partition."""
    segments=span_grammar_segments(content,assignments,semantics)
    rows=[]
    for block in plan['blocks']:
        bid=block['id'];targets=block['spans']
        for segment in segments[bid]:
            cursor=segment['start']
            for target in targets:
                a=max(cursor,target['start']);z=min(segment['end'],target['end'])
                if a>=z:continue
                if a!=cursor:raise DocumentError('SPAN_GRAMMAR_TARGET_COVERAGE')
                rows.append({'kind':'character','when':segment['when'],
                             'set':{'style':target['style']},'id':bid,'range':[a,z]})
                cursor=z
                if cursor==segment['end']:break
            if cursor!=segment['end']:raise DocumentError('SPAN_GRAMMAR_TARGET_COVERAGE')
    return rows


def fit_span_grammar(examples):
    """Learn only unanimous content selectors; contradictory targets abstain."""
    groups=defaultdict(list)
    for row in examples:
        when=row['when']
        if set(when)!=set(SPAN_GRAMMAR_FIELDS) or row.get('kind')!='character':
            raise DocumentError('SPAN_GRAMMAR_EXAMPLE')
        groups[key(when)].append(row)
    rules=[];conflicts=[]
    for selector,rows in sorted(groups.items()):
        targets={key(row['set']) for row in rows}
        when=json.loads(selector)
        if len(targets)>1:
            conflicts.append({'kind':'character','when':when,'variants':len(targets),
                              'examples':[{k:row[k] for k in ('id','set','document','range') if k in row}
                                          for row in rows[:30]],'span_grammar':True})
        else:
            rule={'when':when,'set':rows[0]['set'],'support':len(rows)}
            rule['id']=digest(key(rule).encode())[:16]
            rules.append(rule)
    grammar={'schema':SPAN_GRAMMAR_SCHEMA,'status':'ambiguous' if conflicts else 'complete',
             'selector_fields':list(SPAN_GRAMMAR_FIELDS),'source_typography_used':False,
             'rules':rules,'unresolved_groups':len(conflicts)}
    return grammar,conflicts


def validate_span_grammar(grammar,template,package):
    if not isinstance(grammar,dict) or set(grammar)!={
            'schema','status','selector_fields','source_typography_used','rules','unresolved_groups'}:
        raise DocumentError('SPAN_GRAMMAR_SCHEMA')
    if (grammar['schema']!=SPAN_GRAMMAR_SCHEMA or grammar['status'] not in ('complete','ambiguous')
            or grammar['selector_fields']!=list(SPAN_GRAMMAR_FIELDS)
            or grammar['source_typography_used'] is not False
            or not isinstance(grammar['rules'],list)
            or type(grammar['unresolved_groups'])!=int or grammar['unresolved_groups']<0
            or (grammar['status']=='complete')!=(grammar['unresolved_groups']==0)):
        raise DocumentError('SPAN_GRAMMAR_SCHEMA')
    if any(rule['kind']=='character' for rule in package['rules']):
        raise DocumentError('SPAN_GRAMMAR_LEGACY_MIXED')
    seen=set()
    for rule in grammar['rules']:
        if not isinstance(rule,dict) or set(rule)!={'when','set','support','id'}:
            raise DocumentError('SPAN_GRAMMAR_RULE')
        when=rule['when']
        if not isinstance(when,dict) or set(when)!=set(SPAN_GRAMMAR_FIELDS):
            raise DocumentError('SPAN_GRAMMAR_RULE')
        if any(not isinstance(when[field],str) for field in SPAN_GRAMMAR_FIELDS):
            raise DocumentError('SPAN_GRAMMAR_RULE')
        if (when['role'] not in package['roles'] or when['inline_role'] not in
                {'plain',*package.get('inline_roles',{})}
                or when['character_class'] not in
                {'space','dash','cyrillic','latin','greek','han','number','punctuation','symbol','other'}):
            raise DocumentError('SPAN_GRAMMAR_RULE')
        selector=key(when)
        if selector in seen:raise DocumentError('SPAN_GRAMMAR_DUPLICATE')
        seen.add(selector)
        if (not isinstance(rule['set'],dict) or set(rule['set'])!={'style'}
                or rule['set']['style'] not in template['styles']['character']
                or type(rule['support'])!=int or rule['support']<1
                or rule['id']!=digest(key({k:rule[k] for k in ('when','set','support')}).encode())[:16]):
            raise DocumentError('SPAN_GRAMMAR_RULE')


ALLOWED={'role','previous_kind','next_kind','previous_role','next_role','depth','columns','column','row_band','kind','roles','bold','italic','vertical','hyperlink','language','script','inline_role','section_boundary','story_kind','field_control','list_level','list_kind','field_commands','role_transition_language'}


def fit(examples):
    rules=[];conflicts=[]
    # Back off only where ALL observations agree, never frequency-based.
    for kind in ('paragraph','character','layout','drawing'):
        rows=[r for r in examples if r['kind']==kind]
        coarse=['role'] if kind in ('paragraph','drawing') else ['kind','depth','columns','column','row_band','roles'] if kind=='layout' else ['role','bold','italic','vertical','hyperlink']
        if kind=='character' and any('field_control' in r['when'] for r in rows):coarse=coarse+['field_control']
        if kind=='character' and any('inline_role' in r['when'] for r in rows):coarse=coarse+['inline_role']
        groups=defaultdict(list)
        for row in rows: groups[key({k:row['when'][k] for k in coarse})].append(row)
        for condition,group in sorted(groups.items()):
            buckets={condition:group}
            if len({key(r['set']) for r in group})>1:
                buckets=defaultdict(list)
                for r in group: buckets[key({k:v for k,v in r['when'].items() if k!='role_transition_language'})].append(r)
            for cond,items in sorted(buckets.items()):
                targets={key(r['set']) for r in items}
                if len(targets)>1:
                    # This context feature is used only when it completely
                    # explains an otherwise contradictory selector. Partial
                    # splits increase rule count without making it safe.
                    separated=defaultdict(list)
                    for r in items:separated[key(r['when'])].append(r)
                    # The strongest evidence for a context-dependent rule is
                    # the *same* visible paragraph under two role transitions.
                    # Different text examples alone cannot establish that
                    # the transition, rather than their own content, matters.
                    same_text=(kind=='paragraph' and all(r.get('source_text_digest') for r in items)
                               and len({r['source_text_digest'] for r in items})==1)
                    if same_text and len(separated)>1 and all(len({key(r['set']) for r in group})==1 for group in separated.values()):
                        for exact,group in sorted(separated.items()):
                            rule={'kind':kind,'when':json.loads(exact),'set':group[0]['set'],'support':len(group)}
                            rule['id']=digest(key(rule).encode())[:16];rules.append(rule)
                        continue
                    conflicts.append({'kind':kind,'when':json.loads(cond),'variants':len(targets),
                                      'examples':[{k:r[k] for k in ('id','set','document','range') if k in r} for r in items[:30]]})
                else:
                    rule={'kind':kind,'when':json.loads(cond),'set':items[0]['set'],'support':len(items)}
                    rule['id']=digest(key(rule).encode())[:16];rules.append(rule)
    # Inline annotations are a prediction, not a mandatory style dependency.
    # Remove this selector only when EVERY compatible training observation agrees.
    # Conflicting observations remain in rows and prevent an unsafe broadening.
    for rule in rules:
        if rule['kind']!='character' or 'inline_role' not in rule['when']:continue
        condition={k:v for k,v in rule['when'].items() if k!='inline_role'}
        support=[r for r in examples if r['kind']=='character' and all(r['when'].get(k)==v for k,v in condition.items())]
        if support and all(r['set']==rule['set'] for r in support):
            rule['when']=condition;rule['support']=len(support)
            rule['id']=digest(key({k:v for k,v in rule.items() if k!='id'}).encode())[:16]
    unique={key({k:v for k,v in r.items() if k not in {'id','support'}}):r for r in rules}
    return list(unique.values()),conflicts


def validate_rules(rules,template):
    for r in rules:
        if r['kind'] not in {'paragraph','character','layout','drawing'} or not r['when'] or not set(r['when'])<=ALLOWED:
            raise DocumentError('RULE_SELECTOR_FORBIDDEN')
        target=r['set'];kind=r['kind']
        if kind=='drawing':
            if set(target)!={'drawing_style','run_style'} or target['drawing_style'] not in template['styles']['drawing'] or target['run_style'] not in template['styles']['character']:
                raise DocumentError('RULE_TARGET_INVALID')
        else:
            group=r['when'].get('kind') if kind=='layout' else kind
            if group not in template['styles'] or set(target)!={'style'} or target['style'] not in template['styles'][group]:
                raise DocumentError('RULE_TARGET_INVALID')


def compile_plan(template,content,package,assignments,semantics,forced_empty=None):
    validate_rules(package['rules'],template)
    grammar=package.get('span_grammar')
    if grammar is not None:
        validate_span_grammar(grammar,template,package)
        if grammar['status']!='complete':
            return None,[{'kind':'character','id':'template','code':'SPAN_GRAMMAR_AMBIGUOUS'}]
        grammar_rules={key(rule['when']):rule['set'] for rule in grammar['rules']}
        grammar_segments=span_grammar_segments(content,assignments,semantics)
    f=features(content,assignments);unresolved=[]
    def choose(kind,feat,item):
        matches=[r for r in package['rules'] if r['kind']==kind and all(feat.get(k)==v for k,v in r['when'].items())]
        if not matches:
            unresolved.append({'kind':kind,'id':item,'features':feat,'code':'NO_RULE'});return None
        rank=max(len(r['when']) for r in matches);matches=[r for r in matches if len(r['when'])==rank]
        if len({key(r['set']) for r in matches})!=1:
            unresolved.append({'kind':kind,'id':item,'features':feat,'code':'CONFLICT'});return None
        return matches[0]['set']
    blocks=[];layout=[];objects=[]
    for b in content['blocks']:
        bid=b['id'];spans=[]
        if bid in (forced_empty or {}):
            if b['text'] or b['atoms']:raise DocumentError('SPACER_NOT_EMPTY')
            target={'style':forced_empty[bid]}
        else:target=choose('paragraph',f['paragraph'][bid],bid)
        cursor=0
        for s in grammar_segments[bid] if grammar is not None else semantics[bid]:
            if s['start']!=cursor or not s['start']<s['end']<=len(b['text']):raise DocumentError('SEMANTIC_SPAN_COVERAGE')
            cursor=s['end']
            if grammar is not None:
                style=grammar_rules.get(key(s['when']))
                if style is None:
                    unresolved.append({'kind':'character','id':bid,'features':s['when'],
                                       'code':'NO_SPAN_GRAMMAR_RULE'})
            else:
                pf=f['paragraph'][bid]
                style=choose('character',{**pf,'script':pf['language'],**s['features']},bid)
            if style:
                if grammar is not None and spans and spans[-1]['end']==s['start'] and spans[-1]['style']==style['style']:
                    spans[-1]['end']=s['end']
                else:spans.append({'start':s['start'],'end':s['end'],'style':style['style']})
        if cursor!=len(b['text']):raise DocumentError('SEMANTIC_SPAN_COVERAGE')
        if target:blocks.append({'id':bid,'role':assignments[bid],'paragraph_style':target['style'],'spans':spans})
    for lid,feat in f['layout'].items():
        target=choose('layout',feat,lid)
        if target:layout.append({'id':lid,'kind':feat['kind'],**target})
    for oid,feat in f['drawing'].items():
        target=choose('drawing',feat,oid)
        if target:objects.append({'id':oid,**target})
    if unresolved:return None,unresolved
    plan={'schema_version':VERSION,'provenance':'student_semantics_context_rules_023',
          'blocks':blocks,'layout':layout,'objects':objects,'section_style':package['section_style']}
    validate_catalogue_plan(content,template,plan)
    return plan,[]
