"""Bounded teacher/student template learning with executable acceptance gates."""
import copy
import json
import shutil
import time
from pathlib import Path

from .catalogue import extract_catalogue, render_catalogue, placement_fingerprint
from .docx_engine import NS, DocumentError, digest, dump, load_package, parse_xml, content_fingerprint
from . import rules023 as rules
from .semantic023 import expand_groups, teacher_messages, student_messages, observed_inline_contexts
from .provider023 import call
from .research import render_pdf
from .templateagent022 import compare_all
from .roundtrip022 import neutralize


def question_evidence(questions, samples, labels):
    """Locate an observed role in the reference without inventing coordinates."""
    import pymupdf
    result=[]
    for question in questions:
        q=dict(question);q['evidence']=[]
        for index,(sample,assignment) in enumerate(zip(samples,labels)):
            block=next((b for b in sample['content']['blocks'] if assignment[b['id']]==q['role'] and b['text'].strip()),None)
            if block is None:continue
            evidence={'document':index+1,'block_id':block['id'],'excerpt':block['text'][:300],'page':None}
            with pymupdf.open(sample['golden']) as pdf:
                for page in pdf:
                    hits=page.search_for(block['text'][:60])
                    if hits:
                        evidence.update(page=page.number+1,bbox=list(hits[0]));break
            q['evidence'].append(evidence)
        result.append(q)
    return result


def extract_input(source,folder):
    from .sandbox034 import ACTIVE
    if ACTIVE.get():
        from .engine034 import extract
        return extract(ACTIVE.get(),source,folder)
    from .stories026 import paragraphs
    count=len(paragraphs(load_package(source)))
    if not 1<=count<=2000: raise DocumentError('AGENT_PARAGRAPH_LIMIT')
    labels={f'b-{i+1:06d}':'unclassified' for i in range(count)}
    extract_catalogue(source,labels,{'roles':{'unclassified':'Unclassified input'}},folder)
    return json.loads((folder/'content/content.json').read_text())


def relabel(extracted, labels, definitions):
    template=json.loads((extracted/'template/rules.json').read_text())
    plan=json.loads((extracted/'oracle-plan.json').read_text())
    template['roles']={r:{'description':d,'paragraph_styles':[],'character_styles':[]} for r,d in definitions.items()}
    for b in plan['blocks']:
        b['role']=labels[b['id']];role=template['roles'][b['role']]
        role['paragraph_styles'].append(b['paragraph_style'])
        role['character_styles'].extend(s['style'] for s in b['spans'])
    for role in template['roles'].values():
        for group in ('paragraph_styles','character_styles'):role[group]=sorted(set(role[group]))
    return template,plan


def build_package(samples,labels,definitions,destination,inline_roles=None,*,span_grammar=False):
    if type(span_grammar) is not bool:raise DocumentError('SPAN_GRAMMAR_MODE')
    from .sandbox034 import ACTIVE
    if ACTIVE.get():
        from .engine034 import build
        package,conflicts=build(ACTIVE.get(),samples,labels,definitions,destination,
                                inline_roles,span_grammar)
        # The candidate engine compiles formatting rules; the trusted
        # supervisor derives the student-only context hint from frozen labels.
        contexts=observed_inline_contexts(samples,labels,inline_roles)
        if contexts is not None:
            package['inline_role_contexts']=contexts
            dump(destination/'semantic.json',package)
        return package,conflicts
    destination.mkdir(parents=True,exist_ok=False)
    merged=None;examples=[];span_examples=[];sections=set();observed_top=set();spacer_samples=[]
    for document,(sample,assignment) in enumerate(zip(samples,labels),1):
        template,plan=relabel(sample['extracted'],assignment,definitions)
        if merged is None:
            merged=template
            shutil.copyfile(sample['extracted']/'template/resources.zip',destination/'resources.zip')
        else:
            if template['resource_sha256']!=merged['resource_sha256']:
                raise DocumentError('MULTI_REFERENCE_RESOURCE_CONFLICT')
            for group,values in template['styles'].items():merged['styles'][group].update(values)
            for role,props in template['roles'].items():
                for group in ('paragraph_styles','character_styles'):
                    merged['roles'][role][group]=sorted(set(merged['roles'][role][group]+props[group]))
        examples.extend({**r,'document':document} for r in rules.training_examples(sample['content'],plan,sample['semantics'])
                        if not span_grammar or r['kind']!='character')
        if span_grammar:
            span_examples.extend({**r,'document':document} for r in rules.span_grammar_examples(
                sample['content'],plan,assignment,sample['semantics']))
        f=rules.features(sample['content'],assignment)['paragraph']
        observed_top.update(assignment[b['id']] for b in sample['content']['blocks'] if b['text'].strip() and f[b['id']]['depth']==0)
        sections.add(plan['section_style'])
        spacer_samples.append((sample['content'],plan))
    if len(sections)!=1:raise DocumentError('SECTION_RULE_AMBIGUOUS')
    fitted,conflicts=rules.fit(examples)
    grammar=None
    if span_grammar:
        grammar,span_conflicts=rules.fit_span_grammar(span_examples)
        conflicts.extend(span_conflicts)
    from .diagnostics024 import explain
    conflicts=explain(conflicts,merged)
    from .spacers023 import fit as fit_spacers
    spacers,spacer_conflicts=fit_spacers(spacer_samples);conflicts.extend(spacer_conflicts)
    from .order024 import fit as fit_order
    order,order_conflicts=fit_order([(s['content'],a) for s,a in zip(samples,labels)])
    conflicts.extend(order_conflicts)
    package={'schema':'semantic-rules-023','status':'draft','roles':definitions,'rules':fitted,
             'section_style':next(iter(sections)),'training_documents':len(samples),
             'observed_top_level_roles':sorted(observed_top),'spacers':spacers,'order':order,
             'protocol':'DOCX content and semantic emphasis; no typography input',
             'unresolved_training_groups':len(conflicts),'reference_assignments_included':False}
    from .stories026 import binding_contract
    contracts=[s['content']['story_contract'] for s in samples if s['content'].get('story_contract')]
    if contracts and any(c!=contracts[0] for c in contracts):raise DocumentError('MULTI_REFERENCE_STORY_BINDING_CONFLICT')
    if contracts:package['story_contract']=contracts[0]
    if inline_roles:package['inline_roles']=inline_roles
    contexts=observed_inline_contexts(samples,labels,inline_roles)
    if contexts is not None:package['inline_role_contexts']=contexts
    if grammar is not None:package['span_grammar']=grammar
    dump(destination/'rules.json',merged);dump(destination/'semantic.json',package)
    return package,conflicts


def apply(source,template_dir,folder,config,*,caller=call):
    """Runtime needs only incoming source, frozen template and a model config."""
    from .sandbox034 import ACTIVE
    if ACTIVE.get():
        from .engine034 import apply as sandbox_apply
        return sandbox_apply(ACTIVE.get(),source,template_dir,folder,config,caller)
    folder.mkdir(parents=True,exist_ok=False)
    package=json.loads((template_dir/'semantic.json').read_text())
    adapter=None;original_hash=digest(source.read_bytes())
    if package.get('import_policy')=='annotations-028':
        from .adapters028 import normalize
        normalized=folder/'normalized.docx';adapter=normalize(source,normalized);source=normalized
    content=extract_input(source,folder/'input')
    dump(folder/'input-original.json',content)
    package=json.loads((template_dir/'semantic.json').read_text())
    template=json.loads((template_dir/'rules.json').read_text())
    inline_repair_attempts=config.get('inline_repair_attempts',0)
    if type(inline_repair_attempts) is not int or inline_repair_attempts not in (0,1):
        raise DocumentError('INLINE_REPAIR_LIMIT')
    from .stories026 import binding_contract
    if package.get('story_contract') and binding_contract(load_package(source))!=package['story_contract']:
        raise DocumentError('STORY_BINDING_INCOMPATIBLE')
    from .inline026 import validate as validate_inline, overlay
    captured={}
    def validate_response(response):
        # provider023 records an invalid first answer but does not return it.
        # Capture parsed JSON here solely for the bounded inline correction.
        captured['response']=copy.deepcopy(response)
        if package.get('inline_roles') and (not isinstance(response,dict) or 'inline' not in response):raise DocumentError('INLINE_RESPONSE_REQUIRED')
        expand_groups(response,content['blocks'],package['roles'])
        validate_inline(response,content['blocks'],package.get('inline_roles',{}))
        return response
    first_pass={'status':'valid','code':None}
    inline_repair={'status':'not_needed','model_invocations':0}
    first_meta=None
    try:
        response,meta=caller(config,student_messages(package['roles'],content,package.get('inline_roles'),
                                              package.get('inline_role_contexts')),folder/'student',
                             validate=validate_response)
        first_meta=meta
    except DocumentError as first_error:
        first_pass={'status':'invalid','code':str(first_error)}
        first_meta=json.loads((folder/'student/meta.json').read_text()) if (folder/'student/meta.json').exists() else None
        if not inline_repair_attempts or str(first_error) not in {
                'INLINE_ANCHOR_NOT_FOUND','INLINE_ANCHOR_INVALID','INLINE_QUOTE_MISMATCH',
                'INLINE_RANGE','INLINE_SCHEMA','INLINE_OVERLAP'} or 'response' not in captured:
            raise
        from .inline_repair036 import prepare,messages as repair_messages,merge
        inline_repair={'status':'preparing','model_invocations':0,'first_pass_code':str(first_error)}
        dump(folder/'inline-repair.json',inline_repair)
        try:
            context=prepare(captured['response'],content['blocks'],package.get('inline_roles',{}))
            repair_prompt=repair_messages(context)
            inline_repair.update(status='requesting',invalid_rows=len(context['invalid']),
                                 frozen_rows=len(context['frozen']),model_invocations=1)
            dump(folder/'inline-repair.json',inline_repair)
            def validate_correction(candidate):
                merge(context,candidate,package['roles'])
                return candidate
            repair_response,meta=caller(config,repair_prompt,folder/'student-inline-repair',
                                        max_tokens=4096,validate=validate_correction)
            # Validate again in the supervisor even when a custom caller ignores
            # its validate callback. Neither groups nor good rows may change.
            response=merge(context,repair_response,package['roles'])
            inline_repair.update(status='repaired',model_invocations=1,
                                 corrected_rows=len(context['invalid']))
            dump(folder/'inline-repair.json',inline_repair)
        except DocumentError as correction_error:
            inline_repair.update(status='failed',code=str(correction_error),
                                 model_invocations=inline_repair['model_invocations'])
            dump(folder/'inline-repair.json',inline_repair)
            raise
    assignments=expand_groups(response,content['blocks'],package['roles'])
    from .inline026 import validate as validate_inline, overlay
    inline=validate_inline(response,content['blocks'],package.get('inline_roles',{}))
    # Persist the strictly validated effective answer before compilation or
    # rendering. A repaired first pass has no student/validated.json because
    # the provider rejected it, but managed repair still needs its real final
    # labels and inline annotations for fixed-response replay.
    dump(folder/'effective-student.json',response)
    semantics=rules.semantic_spans(source)
    if package.get('inline_roles'):semantics=overlay(semantics,inline)
    from .order024 import arrange, expected_source
    content,permutation,moves,order_issues=arrange(content,assignments,package.get('order'),source)
    from .spacers023 import restore
    content,runtime_assignments,semantics,forced,inserted=restore(content,assignments,semantics,package,template)
    plan,unresolved=rules.compile_plan(template,content,package,runtime_assignments,semantics,forced)
    unresolved.extend(order_issues)
    if order_issues:plan=None
    report={'schema':'application-023','model':meta,'unresolved':unresolved,'status':'needs_review',
            'assignments':assignments,'structure_moves':moves,'structure_permutation':permutation,'source_sha256':original_hash,'input_adapter':adapter,
            'first_pass':first_pass,'first_pass_model':first_meta,'inline_repair':inline_repair,
            'model_invocations':1+inline_repair['model_invocations'],
            'strict_one_pass_eligible':first_pass['status']=='valid'}
    if plan:
        dump(folder/'input/content/content.json',content)
        plan['template_sha256']=digest((template_dir/'rules.json').read_bytes())
        plan['input_sha256']=digest((folder/'input/content/content.json').read_bytes())
        dump(folder/'plan.json',plan)
        output=folder/'result.docx';render_catalogue(template_dir,folder/'input/content',plan,output)
        from .integrity023 import check
        checked=output
        if inserted:
            from .docx_engine import write_package,xml_bytes
            parts=load_package(output);root=parse_xml(parts['word/document.xml']);body=root.find('w:body',NS)
            for index in sorted(inserted,reverse=True):
                node=body[index]
                if node.tag.rsplit('}',1)[-1]!='p' or node.findall('.//w:t',NS) or node.findall('.//w:drawing',NS):raise DocumentError('SPACER_NOT_EMPTY')
                body.remove(node)
            parts['word/document.xml']=xml_bytes(root);checked=folder/'integrity-without-inserted-spacers.docx';write_package(checked,parts)
        expected=expected_source(source,permutation,folder/'expected-content-order.docx')
        integrity=check(expected,checked);report.update(integrity);report['inserted_layout_paragraphs']=len(inserted)
        if not all(integrity.values()):
            report['status']='integrity_failed'
        else:
            report['status']='rendered_unverified'
            report['pdf']=str(render_pdf(output,folder/'render'))
    dump(folder/'result.json',report)
    return report


APPLICATION_INTEGRITY_GATES=('section_boundaries_exact','content_exact',
                             'placements_exact','nested_topology_exact',
                             'protected_vertical_exact')


def application_passed(public,trial):
    """Keep invisible DOCX structure and teacher labels in the acceptance gate."""
    return (trial.get('status')=='rendered_unverified' and
            public.get('role_correct')==public.get('role_total') and
            public.get('role_total',0)>0 and
            public.get('pixels',{}).get('pixel_exact') is True and
            public.get('format',{}).get('property_exact') is True and
            all(trial.get(name) is True for name in APPLICATION_INTEGRITY_GATES))


def run(references,folder,teacher,student,*,max_iterations=3,caller=call,progress=None,context='',resume_from=None,feedback_provider=None,acceptance_probe=None,adaptive=False):
    if not 1<=max_iterations<=(8 if adaptive else 5) or not 1<=len(references)<=10:raise DocumentError('AGENT_LIMIT')
    span_grammar=teacher.get('span_grammar',False)
    if type(span_grammar) is not bool:raise DocumentError('SPAN_GRAMMAR_MODE')
    folder.mkdir(parents=True,exist_ok=False)
    report={'schema':'teacher-student-023','status':'running','iterations':[],
            'training_documents':len(references),'student_model':student['model'],'teacher_model':teacher['model'],
            'held_out_transfer':'not_measured','pixel_tolerance':0,'dpi':144,
            'source_hashes':[digest(p.read_bytes()) for p in references],
            'implementation_hashes':{p.name:digest(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')}}
    def emit():
        dump(folder/'result.json',report)
        if progress:progress(copy.deepcopy(report))
    samples=[];observations=[];allblocks=[];feedback=None;feedback_images=[];start=time.monotonic();teacher_output_limit=8000
    last_conflicted_signature=None;last_conflict_fingerprint=None;conflict_history=[]
    report['stage']='extracting';emit()
    try:
        for i,source in enumerate(references):
            local=folder/f'reference-{i+1}';content=extract_input(source,local/'extracted')
            plan=json.loads((local/'extracted/oracle-plan.json').read_text())
            template=json.loads((local/'extracted/template/rules.json').read_text())
            sample={'source':source,'content':content,'extracted':local/'extracted',
                    'semantics':rules.semantic_spans(source),'golden':render_pdf(source,local/'reference')}
            samples.append(sample)
            report['extracted_documents']=len(samples);emit()
            geometry=rules.features(content,{b['id']:'unknown' for b in content['blocks']})['paragraph']
            for b,p in zip(content['blocks'],plan['blocks']):
                bid=f'{i}:{b["id"]}';allblocks.append({'id':bid,'text':b['text']})
                observations.append({'n':len(observations)+1,'document':i+1,'text':b['text'],'structure':{k:v for k,v in geometry[b['id']].items() if k not in {'role','previous_role','next_role'}},
                                     'paragraph_style':p['paragraph_style'],'character_styles':sorted({s['style'] for s in p['spans']}),'style_spans':p['spans']})
            # Style properties are training observations, never sent to the student.
            sample['catalogue']=template['styles']
        if resume_from is not None:
            previous=sorted(Path(resume_from).glob('iteration-*/teacher/request.json'))[-1]
            message=json.loads(previous.read_text())['messages'][1]['content']
            previous_input=json.loads(message if isinstance(message,str) else message[0]['text'])
            from .evidence031 import restore
            aliases=previous_input['observations'].get('style_aliases',{})
            if restore(previous_input['observations']['paragraphs'],aliases)!=observations:raise DocumentError('RESUME_REFERENCE_CHANGED')
            feedback=restore(previous_input['feedback'],aliases)
            if feedback:
                feedback['conflicts']=[{**c,'examples':c.get('examples',[])[:4]} for c in feedback.get('conflicts',[])[:20]]
                for m in feedback.get('measurements',[]):
                    pixels=m.pop('pixels',None)
                    if pixels:m['pixel_exact']=pixels.get('pixel_exact')
                    unresolved=m.pop('unresolved',[])
                    if unresolved:m.update(unresolved_count=len(unresolved),unresolved_examples=unresolved[:8])
            report['continued_from']=str(resume_from)
        unique_catalogues=list({rules.key(s['catalogue']):s['catalogue'] for s in samples}.values())
        for iteration in range(max_iterations):
            if time.monotonic()-start>1800:raise DocumentError('AGENT_TIME_LIMIT')
            work=folder/f'iteration-{iteration+1}';work.mkdir()
            user_feedback=feedback_provider() if feedback_provider else {'revision':0,'text':''}
            report['feedback_revision_applied']=user_feedback['revision']
            report['stage']='teacher'
            row={'number':iteration+1,'teacher_output_limit':teacher_output_limit,'status':'running','applications':[],'started_seconds':time.monotonic()-start};report['iterations'].append(row);emit()
            from .inline026 import align_unique_quotes
            teacher_alignments=[]
            def validate_teacher(answer):
                normalized,fixes=align_unique_quotes(answer,allblocks)
                expand_groups(normalized,allblocks)
                teacher_alignments.extend(fixes)
                return normalized
            try:
                response,meta=caller(teacher,teacher_messages({'user_context':context,'user_feedback':user_feedback['text'],'paragraphs':observations,
                           'catalogues':unique_catalogues},feedback,feedback_images),work/'teacher',max_tokens=teacher_output_limit,
                           validate=validate_teacher)
                # Fake/offline callers may ignore validate. The supervisor
                # applies the same strict normalization before compilation.
                response,late_alignments=align_unique_quotes(response,allblocks)
                teacher_alignments.extend(late_alignments)
                expand_groups(response,allblocks)
            except DocumentError as exc:
                recoverable={'MODEL_INCOMPLETE','QUESTION_SCHEMA','TEACHER_SCHEMA','ROLE_DEFINITION_INVALID','SEMANTIC_GROUP_INVALID','SEMANTIC_GROUP_COVERAGE','SEMANTIC_GROUP_OVERLAP','INLINE_ANCHOR_NOT_FOUND','INLINE_QUOTE_MISMATCH','INLINE_RANGE'}
                if not adaptive or str(exc) not in recoverable:raise
                row.update(status='failed',code=str(exc),finished_seconds=time.monotonic()-start)
                if str(exc)=='MODEL_INCOMPLETE':teacher_output_limit=min(32768,teacher_output_limit*2)
                feedback={'validation_error':str(exc),'instruction':'Return a fresh complete response; all question roles must be keys of roles. Use exact quoted spans and local occurrence numbers.'}
                if str(exc)=='MODEL_INCOMPLETE':feedback['instruction']='The previous answer was truncated. Output budget increased. Group consecutive paragraphs and use only necessary semantic inline annotations; return complete JSON.'
                emit();continue
            if response['questions'] and feedback_provider and not report.get('question_window') and teacher.get('question_wait_seconds',0)>0 and iteration+1>=teacher.get('question_after_iteration',1):
                from .questions035 import wait
                expanded_questions=expand_groups(response,allblocks)
                question_labels=[{b['id']:expanded_questions[f'{i}:{b["id"]}'] for b in sample['content']['blocks']} for i,sample in enumerate(samples)]
                def question_progress(state):
                    report.update(stage='awaiting_optional_answer',question_window=state,questions=question_evidence(response['questions'],samples,question_labels));emit()
                latest,window=wait(response['questions'],user_feedback,feedback_provider,question_progress,seconds=min(30,teacher['question_wait_seconds']))
                if latest['revision']>user_feedback['revision']:
                    response,answer_meta=caller(teacher,teacher_messages({'user_context':context,'user_feedback':latest['text'],'paragraphs':observations,'catalogues':unique_catalogues},feedback,feedback_images),work/'teacher-clarified',max_tokens=teacher_output_limit,validate=validate_teacher)
                    response,late_alignments=align_unique_quotes(response,allblocks)
                    teacher_alignments.extend(late_alignments)
                    expand_groups(response,allblocks)
                    # Keep the effective response discoverable by controlled compiler replay.
                    dump(work/'effective-teacher.json',response)
                    row['clarification_teacher']=answer_meta;report['feedback_revision_applied']=latest['revision']
            from .semantic023 import compact_conflicts,semantic_signature
            signature=semantic_signature(response,allblocks)
            report['stage']='compiling';emit()
            row['teacher']=meta;row['teacher_quote_alignments']=teacher_alignments
            expanded=expand_groups(response,allblocks)
            labels=[{b['id']:expanded[f'{i}:{b["id"]}'] for b in s['content']['blocks']} for i,s in enumerate(samples)]
            from .inline026 import validate as validate_inline, overlay
            inline=validate_inline(response,allblocks)
            iteration_samples=[]
            for i,sample in enumerate(samples):
                marks={b['id']:inline[f'{i}:{b["id"]}'] for b in sample['content']['blocks']}
                iteration_samples.append({**sample,'semantics':overlay(sample['semantics'],marks) if response.get('inline_roles') else sample['semantics']})
            package,conflicts=build_package(iteration_samples,labels,response['roles'],work/'template',
                                            response.get('inline_roles'),span_grammar=span_grammar)
            row['conflicting_groups']=len(conflicts);row['questions']=response['questions']
            if len(conflicts)<report.get('best_training_conflicts',float('inf')):
                report['best_training_conflicts']=len(conflicts)
                report['best_training_iteration']=iteration+1
            row['conflict_properties']=sorted({p for c in conflicts for p in c.get('differing_properties',[])})
            from .diagnostics024 import evidence
            row['conflict_evidence']=evidence(conflicts,samples)
            emit()
            # Role renaming can keep the old plateau detector from firing
            # even while the same target-style contradiction survives. After
            # three such observations, offer a small batch of concrete user
            # questions. No answer is inferred from the timeout; unresolved
            # training rules remain unpublished.
            from .questions035 import conflict_signature,clarify
            conflict_history.append({key for conflict in conflicts
                                     if (key:=conflict_signature(conflict)) is not None})
            if (adaptive and conflicts and not response['questions'] and not report.get('questions')
                    and len(conflict_history)>=3):
                persistent=set.intersection(*conflict_history[-3:])
                derived=clarify(conflicts,row['conflict_evidence'],response['roles'],persistent)
                if derived:
                    row['derived_questions']=derived;report['questions']=derived;emit()
                    if (feedback_provider and not report.get('question_window')
                            and iteration+1<max_iterations and teacher.get('question_wait_seconds',0)>0):
                        from .questions035 import wait
                        def question_progress(state):
                            report.update(stage='awaiting_optional_answer',question_window=state);emit()
                        latest,window=wait(derived,user_feedback,feedback_provider,question_progress,
                                           seconds=min(30,teacher['question_wait_seconds']))
                        if latest['revision']>user_feedback['revision']:
                            row['clarification_revision_received']=latest['revision']
                        report['stage']='compiling';emit()
            dump(work/'training-conflicts.json',conflicts)
            conflict_fingerprint=digest(rules.key([{'kind':c['kind'],'when':c.get('when'),
                'variants':c.get('variants'),'targets':sorted({rules.key(e['set']) for e in c.get('examples',[])})}
                for c in conflicts]).encode())
            compact=compact_conflicts(conflicts,row['conflict_evidence'],expanded,page=iteration)
            row['conflict_feedback_page']=compact['conflicts_page']
            row['conflict_feedback_pages_total']=compact['conflicts_pages_total']
            if (conflicts and adaptive and teacher.get('triage_conflicts') and
                    signature==last_conflicted_signature and conflict_fingerprint==last_conflict_fingerprint and
                    iteration>=compact['conflicts_pages_total']):
                # The teacher may rephrase descriptions or regroup adjacent
                # blocks. Stop only after every bounded conflict page was
                # shown to a subsequent teacher response; otherwise later
                # contrastive groups would never reach the model.
                row.update(status='needs_review',code='SEMANTIC_PLATEAU',
                           student_skipped='unchanged_training_plan',
                           finished_seconds=time.monotonic()-start)
                report['status']='needs_review';report['code']='SEMANTIC_PLATEAU'
                emit();break
            # A conflicting training package cannot yet reproduce the reference.
            # Let the teacher refine its roles before paying the student and the
            # visual model to evaluate a package that is already known to fail.
            if conflicts and adaptive and teacher.get('triage_conflicts'):
                row.update(status='needs_review',code='TRAINING_CONFLICTS',
                           student_skipped='training_conflicts',
                           finished_seconds=time.monotonic()-start)
                involved={r for c in compact['conflicts'] for r in
                          [c.get('when',{}).get('role'),*[e.get('assigned_role') for e in c['examples']]] if r in response['roles']}
                feedback={**compact,'triage_phase':'training_conflicts',
                          'previous_roles':{r:response['roles'][r][:300] for r in sorted(involved)[:12]},
                          'previous_role_names':sorted(response['roles']),
                          'previous_inline_roles':{r:d[:300] for r,d in list(sorted(response.get('inline_roles',{}).items()))[:12]},
                          'instruction':'Descriptions alone cannot change these conflicts. Revise group role labels or inline ranges only where contrasting examples provide a semantic or structural cue. Preserve exact properties; keep indistinguishable variants unresolved and ask a critical question.'}
                last_conflicted_signature=signature;last_conflict_fingerprint=conflict_fingerprint
                dump(work/'feedback.json',feedback)
                emit()
                continue
            confusions=[]
            for i,sample in enumerate(samples):
                # Render an actual degraded DOCX, not just a filtered prompt.
                incoming=work/f'degraded-{i+1}.docx'
                neutralize(sample['source'],incoming)
                report['stage']='student';report['active_document']=i+1;emit()
                try:
                    trial=apply(incoming,work/'template',work/f'application-{i+1}',student,caller=caller)
                except DocumentError as exc:
                    if not adaptive or str(exc).startswith('PROVIDER_HTTP_'):raise
                    row['applications'].append({'status':'failed','code':str(exc),'unresolved':[],'passed':False})
                    emit();continue
                new_content=json.loads((work/f'application-{i+1}/input-original.json').read_text())
                old=iter(sample['content']['blocks']);expected={}
                def content_key(block):
                    return block['text'],[a['kind'] for a in block['atoms'] if a['kind']!='text']
                for b in new_content['blocks']:
                    original=next(old,None)
                    while original is not None and content_key(original)!=content_key(b) and not original['text'] and not original['atoms']:
                        original=next(old,None)
                    if original is None or content_key(original)!=content_key(b):
                        raise DocumentError('EVALUATION_CONTENT_ALIGNMENT')
                    expected[b['id']]=labels[i][original['id']]
                public={k:v for k,v in trial.items() if k not in {'assignments','pdf'}}
                public['input_protocol']='neutralized DOCX; empty top-level layout paragraphs removed'
                public['role_correct']=sum(trial['assignments'][bid]==role for bid,role in expected.items())
                public['role_total']=len(expected)
                confusions.extend({'document':i+1,'paragraph':j+1,'text':b['text'][:300],
                     'expected':expected[b['id']],'predicted':trial['assignments'][b['id']]}
                     for j,b in enumerate(new_content['blocks'])
                     if expected[b['id']]!=trial['assignments'][b['id']])
                report['stage']='comparing';emit()
                if trial.get('pdf'):
                    public['pixels']=compare_all(sample['golden'],Path(trial['pdf']),work/f'diff-{i+1}')
                    from .format032 import audit
                    public['format']=audit(sample['source'],work/f'application-{i+1}'/'result.docx')
                public['integrity_failures']=[name for name in APPLICATION_INTEGRITY_GATES
                                              if trial.get(name) is not True]
                public['passed']=application_passed(public,trial)
                row['applications'].append(public);emit()
            success=not conflicts and all(a['passed'] for a in row['applications'])
            if success and acceptance_probe is not None:
                report['stage']='stress_testing';emit()
                row['stress']=acceptance_probe(samples,work/'template',work)
                applicable=[r for r in row['stress'] if r.get('status')!='not_applicable']
                success=bool(applicable) and all(r.get('passed',False) for r in applicable)
                emit()
            row['status']='passed' if success else 'needs_review'
            row['finished_seconds']=time.monotonic()-start
            measurements=[{k:v for k,v in a.items() if k not in {'pixels','unresolved'}} |
                          {'pixel_exact':a.get('pixels',{}).get('pixel_exact'),
                           'unresolved_count':len(a.get('unresolved',[])),
                           'unresolved_examples':a.get('unresolved',[])[:12]} for a in row['applications']]
            feedback={**compact,
                      'semantic_confusions':confusions[:40],'measurements':measurements,
                      'previous_roles':response['roles'],'previous_groups':response['groups'],
                      'previous_inline_roles':response.get('inline_roles',{}),'previous_inline':response.get('inline',[])}
            if row.get('stress'):feedback['stress_failures']=[{k:v for k,v in r.items() if k!='pixels'} for r in row['stress'] if not r.get('passed') and r.get('status')!='not_applicable']
            dump(work/'feedback.json',feedback)
            feedback_images=[]
            if teacher.get('visual_review'):
                from .visual035 import inspect,summary
                visual=[]
                for i,application in enumerate(row['applications']):
                    pdfs=list((work/f'application-{i+1}/render').glob('*.pdf'))
                    if pdfs:
                        visual.append({'document':i+1,**summary(inspect(samples[i]['golden'],pdfs[0],work/f'visual-{i+1}',teacher,caller))})
                row['visual']=visual;feedback['visual']=visual
                dump(work/'feedback.json',feedback);emit()
            else:
                # Pixel comparison covers every page. Supply a bounded visual example
                # of the first differing page to the teacher on the next iteration.
                for i,a in enumerate(row['applications']):
                    different=next((p for p in a.get('pixels',{}).get('matched_page_diagnostics',[]) if not p['pixel_exact']),None)
                    if different is None:continue
                    import base64,pymupdf
                    index=a['pixels']['matched_page_diagnostics'].index(different)
                    candidate=next((work/f'application-{i+1}/render').glob('*.pdf'))
                    for pdf in (samples[i]['golden'],candidate):
                        with pymupdf.open(pdf) as doc:
                            page=doc[index];pix=page.get_pixmap(matrix=pymupdf.Matrix(640/page.rect.width,640/page.rect.width),alpha=False)
                            feedback_images.append('data:image/jpeg;base64,'+base64.b64encode(pix.tobytes('jpeg',jpg_quality=65)).decode())
                    feedback['visual_evidence']={'document':i+1,'page':index+1,'order':['reference','candidate'],'display_width':640}
                    break
            if success:
                report['stage']='negative_controls';emit()
                from .controls023 import verify as negative_controls
                controls=[]
                for i,sample in enumerate(samples):
                    place=work/f'negative-{i+1}';place.mkdir()
                    controls.extend(negative_controls(sample['source'],sample['golden'],place))
                report['negative_controls']=controls
                if not controls or not all(c['detected'] for c in controls):
                    raise DocumentError('NEGATIVE_CONTROL_FAILED')
                # Requirement questions and held-out transfer remain separate gates.
                report.update(status='reference_verified',template=str(work/'template'),
                              questions=question_evidence(response['questions'],samples,labels),role_definitions=response['roles'])
                break
        else:report['status']='needs_review'
    except DocumentError as exc:
        report.update(status='needs_review',code=str(exc))
    except Exception as exc:
        report.update(status='unavailable',error_type=type(exc).__name__)
    if report.get('iterations') and report['iterations'][-1].get('status')=='running':
        report['iterations'][-1]['status']='failed'
        report['iterations'][-1]['code']=report.get('code',report.get('error_type','INTERRUPTED'))
    report['last_stage']=report.get('stage');report['stage']='finished';report['seconds']=time.monotonic()-start;emit();return report
