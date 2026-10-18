"""Managed code repair: proposal -> isolated engine -> external gates -> immutable profile."""
import json,shutil,time
from pathlib import Path
from .docx_engine import DocumentError,dump,digest
from .sandbox034 import Engine,snapshot,propose,use,EDITABLE,file_hashes
from .provider023 import call


def evaluate(engine,case,folder):
    from .agent023 import apply,build_package,extract_input
    from .integrity023 import check
    from .format032 import audit
    from .research import render_pdf,compare_pixels
    folder.mkdir(parents=True,exist_ok=False)
    row={'id':case['id'],'split':case['split'],'passed':False}
    try:
        if case.get('kind')=='instance':
            from .engine034 import render
            with use(engine):
                content=extract_input(case['source'],folder/'extracted')
                plan=json.loads((folder/'extracted/oracle-plan.json').read_text())
                output=folder/'reconstructed.docx'
                render(engine,folder/'extracted/template',folder/'extracted/content',plan,output)
            row['integrity']=check(case['golden'],output);row['format']=audit(case['golden'],output)
            row['pixels']=compare_pixels(render_pdf(case['golden'],folder/'golden'),render_pdf(output,folder/'render'))
            row['passed']=all(row['integrity'].values()) and row['format']['property_exact'] and row['pixels']['pixel_exact']
            dump(folder/'probe.json',row);return row
        with use(engine):
            template=case.get('template')
            if case.get('training'):
                t=case['training'];template=folder/'template'
                samples=[];extracted_samples=[]
                for number,original in enumerate(t['samples']):
                    if original.get('source') is None:raise DocumentError('REPAIR_TRAINING_SOURCE_REQUIRED')
                    extracted=folder/f'training-{number}'
                    content=extract_input(original['source'],extracted)
                    if [(b['id'],b['text']) for b in content['blocks']]!=[(b['id'],b['text']) for b in original['content']['blocks']]:raise DocumentError('CANDIDATE_TRAINING_ALIGNMENT')
                    from .rules023 import semantic_spans
                    from .inline026 import overlay
                    marks={bid:[{'start':s['start'],'end':s['end'],'role':s['features']['inline_role']} for s in spans if s['features'].get('inline_role','plain')!='plain'] for bid,spans in original['semantics'].items()}
                    semantics=semantic_spans(original['source'])
                    if t.get('inline_roles'):semantics=overlay(semantics,marks)
                    samples.append({**original,'content':content,'extracted':extracted,'semantics':semantics})
                    extracted_samples.append(extracted)
                _,conflicts=build_package(samples,t['labels'],t['roles'],template,t.get('inline_roles'))
                row['conflicts']=len(conflicts)
                # Oracle replay alone is insufficient: it bypasses the
                # learned semantic rules entirely. Compile every reference
                # with frozen teacher labels through the candidate engine and
                # compare its actual style decisions to the extracted oracle.
                from .leakage034 import _compile,_plan_fingerprint
                runtime=[];row['runtime_compilation']=runtime
                for number,(original,sample) in enumerate(zip(t['samples'],samples)):
                    oracle=json.loads((sample['extracted']/'oracle-plan.json').read_text())
                    for block in oracle['blocks']:
                        block['role']=t['labels'][number][block['id']]
                    marks={bid:[{'start':s['start'],'end':s['end'],
                                 'role':s['features']['inline_role']}
                                for s in spans if s['features'].get('inline_role','plain')!='plain']
                           for bid,spans in original['semantics'].items()}
                    compiled=_compile(engine,original['source'],template,
                                      (sample['content'],sample['semantics'],None),
                                      t['labels'][number],marks,folder/f'compiled-{number+1}')
                    exact=(compiled.get('status')=='planned' and
                           compiled.get('fingerprint')==_plan_fingerprint(oracle))
                    runtime.append({'document':number+1,'status':compiled.get('status'),
                                    'exact':exact,'issue_count':max(1,len(compiled.get('issues',[])))
                                    if compiled.get('status')!='planned' else 0,
                                    'wrong_style':compiled.get('status')=='planned' and not exact})
                row['runtime_unresolved_count']=sum(r['issue_count'] for r in runtime)
                row['runtime_wrong_style_count']=sum(r['wrong_style'] for r in runtime)
                row['runtime_exact']=bool(runtime) and all(r['exact'] for r in runtime)
                if conflicts and case.get('kind')!='source_gate':
                    row['conflict_examples']=conflicts[:12]
                    dump(folder/'probe.json',row);return row
            if case.get('kind') in {'training','source_gate'}:
                # No student answer exists yet. Verify that the candidate's
                # compiled template can still reproduce every reference using
                # only the frozen teacher labels and its own extracted oracle.
                # A source_gate performs this check even while fitting has
                # unresolved conflicts: fewer conflicts alone cannot justify
                # retaining a compiler that damages the reference instance.
                from .engine034 import render
                if not case.get('training'):raise DocumentError('REPAIR_TRAINING_SOURCE_REQUIRED')
                if len(case['goldens'])!=len(extracted_samples):raise DocumentError('REPAIR_TRAINING_GOLDEN_COVERAGE')
                row['instances']=[]
                for number,(extracted,golden) in enumerate(zip(extracted_samples,case['goldens'])):
                    plan=json.loads((extracted/'oracle-plan.json').read_text())
                    for block in plan['blocks']:
                        block['role']=t['labels'][number][block['id']]
                    plan['template_sha256']=digest((template/'rules.json').read_bytes())
                    plan['input_sha256']=digest((extracted/'content/content.json').read_bytes())
                    output=folder/f'reconstructed-{number+1}.docx'
                    render(engine,template,extracted/'content',plan,output)
                    instance={'document':number+1,'integrity':check(golden,output),
                              'format':audit(golden,output),
                              'pixels':compare_pixels(render_pdf(golden,folder/f'golden-{number+1}'),
                                                      render_pdf(output,folder/f'render-{number+1}'))}
                    instance['passed']=all(instance['integrity'].values()) and instance['format']['property_exact'] and instance['pixels']['pixel_exact']
                    row['instances'].append(instance)
                    if not instance['passed'] and 'integrity' not in row:
                        row.update({k:instance[k] for k in ('integrity','format','pixels')})
                row['passed']=(bool(row['instances']) and all(item['passed'] for item in row['instances'])
                               and row['runtime_wrong_style_count']==0
                               and (case.get('kind')=='source_gate' or row['runtime_exact']))
                dump(folder/'probe.json',row);return row
            if template is None:raise DocumentError('REPAIR_TEMPLATE_REQUIRED')
            result=apply(case['source'],template,folder/'application',{},caller=lambda *a,**kw:(case['response'],{'api_attempts':0,'mode':'fixed_response_probe'}))
        row['status']=result['status'];row['unresolved_count']=len(result.get('unresolved',[]))
        row['codes']=sorted({r.get('code','UNRESOLVED') for r in result.get('unresolved',[])})
        if case['split']=='development' and not row.get('passed'):
            content=json.loads((folder/'application/input-original.json').read_text())
            from .docx_engine import parse_xml
            structure=[]
            for b in content['blocks'][:80]:
                controls=[]
                for a in b['atoms']:
                    if a['kind']=='control':
                        n=parse_xml(a['xml'].encode());controls.append({'tag':n.tag.rsplit('}',1)[-1],'attributes':dict(n.attrib)})
                structure.append({'id':b['id'],'role':result['assignments'].get(b['id']),
                    'atom_kinds':[a['kind'] for a in b['atoms']],'controls':controls,
                    'section_boundary':b.get('section_boundary',False),'list_level':b.get('list_level',-1)})
            row['structural_evidence']=structure
            row['unresolved_examples']=result.get('unresolved',[])[:12]
            learned=json.loads((template/'semantic.json').read_text()).get('rules',[])
            row['near_rules']=[]
            for issue in result.get('unresolved',[])[:8]:
                if issue.get('code')!='NO_RULE':continue
                features=issue.get('features',{});near=[]
                for rule in learned:
                    if rule['kind']!=issue['kind']:continue
                    mismatch={k:{'observed':features.get(k),'required':v} for k,v in rule['when'].items() if features.get(k)!=v}
                    if len(mismatch)<=2:near.append({'mismatch':mismatch,'when':rule['when'],'target':rule['set']})
                near.sort(key=lambda r:len(r['mismatch']))
                row['near_rules'].append({'id':issue['id'],'candidates':near[:4]})
        if case.get('expect_blocked'):
            row['passed']=result['status']=='needs_review' and not (folder/'application/result.docx').exists()
        elif result.get('pdf'):
            output=folder/'application/result.docx'
            row['integrity']=check(case['golden'],output)
            row['format']=audit(case['golden'],output)
            row['pixels']=compare_pixels(render_pdf(case['golden'],folder/'golden'),Path(result['pdf']))
            row['passed']=all(row['integrity'].values()) and row['format']['property_exact'] and row['pixels']['pixel_exact']
    except DocumentError as exc:
        row['code']=str(exc)
        # The external guard must reject forbidden boundary movement too.
        row['passed']=bool(case.get('expect_blocked')) and str(exc)=='CANDIDATE_UNAUTHORIZED_ORDER'
        if case.get('kind')=='instance' and case['split']=='development':
            from collections import Counter
            from .docx_engine import load_package,parse_xml
            root=parse_xml(load_package(case['source'],allow_unsupported=True)['word/document.xml'])
            row['element_inventory']=dict(Counter(n.tag.rsplit('}',1)[-1] for n in root.iter() if isinstance(n.tag,str)))
    except Exception as exc:row.update(code='PROBE_UNAVAILABLE',error_type=type(exc).__name__)
    dump(folder/'probe.json',row);return row


def messages(source,failures,previous=None,modules=None):
    modules=modules or sorted(EDITABLE)
    return [{'role':'system','content':'''You repair a DOCX compiler in a controlled software experiment. Return JSON only: {"diagnosis": str, "edits": [{"file": str,"old": exact unique source substring,"new": replacement}]}. Fix the general algorithm, never an individual document. Do not memorize source text, IDs, style hashes, paragraph indices or expected test outputs. Do not relax content checks, infer success, suppress errors, change supported boundaries blindly, or read test/golden files. Code runs without network or secrets. You can edit only the supplied compiler modules. Hidden independent document tests are evaluated outside your process. Preserve exact typography distinctions and reject genuinely ambiguous rules. Incoming DOCX typography (font, size, color, shading, highlight, spacing, bold and italic, including complex-script variants) may be corrupted independently of the target style. Do not add or repurpose incoming typography as a predictor for target style; use semantic or structural evidence instead. A deployable result must fix all development probes and preserve unrelated regressions. You may propose a smaller general fix that strictly reduces measured unresolved conflicts without regressions: it remains an unpublished candidate for the next step. Consider separable causes rather than refusing because one patch cannot solve everything. Preserve structural bindings such as list instances as structural payload, never use resource IDs as style selectors. If no justified improvement is possible within scope, return diagnosis and an empty edits list; it remains unresolved.'''} ,{'role':'user','content':json.dumps({'source':{name:(Path(source)/name).read_text() for name in modules},'development_failures':failures,'previous_attempt':previous},ensure_ascii=False)}]


def rank(row):
    if row.get('passed'):return (0,0)
    if row.get('conflicts'):return (3,row['conflicts'])
    if row.get('unresolved_count'):return (2,row['unresolved_count'])
    if row.get('pixels') and row.get('integrity') and all(row['integrity'].values()):
        return (1,row['pixels'].get('differing_pixel_ratio',1))
    return (4,1)


def improves(previous,current):
    before={r['id']:rank(r) for r in previous if r['split']=='development'}
    after={r['id']:rank(r) for r in current}
    if set(before)!=set(after):return False
    old_rows={r['id']:r for r in previous if r['split']=='development'}
    new_rows={r['id']:r for r in current}
    for identifier,old in old_rows.items():
        if 'runtime_unresolved_count' in old:
            new=new_rows[identifier]
            if ('runtime_unresolved_count' not in new or
                    new['runtime_unresolved_count']>old['runtime_unresolved_count']):
                return False
    return all(after[k]<=before[k] for k in before) and any(after[k]<before[k] for k in before)


def run(base,cases,folder,config,*,caller=call,max_attempts=2,image='articleflow-repair034',progress=None,modules=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    if not any(c['split']=='development' for c in cases) or not any(c['split']=='sealed' for c in cases):raise DocumentError('REPAIR_SPLIT_REQUIRED')
    if len({c['id'] for c in cases})!=len(cases):raise DocumentError('REPAIR_CASE_ID_DUPLICATE')
    snapshot(folder/'base',base);base=folder/'base';engine=Engine(base,image)
    report={'schema':'engine-repair-034','status':'running','stage':'baseline','attempts':[],'base_hashes':engine.hashes,'image':engine.image,'tests':len(cases),'automatic_global_source_edit':False}
    def emit():
        report['seconds']=round(time.monotonic()-started,3);dump(folder/'report.json',report)
        if progress:progress(dict(report))
    def diagnose(engine,case,where):
        row=evaluate(engine,case,where)
        if config.get('visual_review') and case['split']=='development' and row.get('pixels'):
            from .visual035 import inspect,summary
            golden=list((where/'golden').glob('*.pdf'))
            actual=list((where/'application/render').glob('*.pdf')) or list((where/'render').glob('*.pdf'))
            if golden and actual:
                row['visual']=summary(inspect(golden[0],actual[0],where/'visual',config,caller))
                dump(where/'probe.json',row)
        return row
    rows=[];report['baseline']=rows;emit()
    base_probe_root=folder/'baseline'
    for c in cases:
        rows.append(diagnose(engine,c,folder/'baseline'/c['id']));emit()
    if all(r['passed'] for r in rows):report.update(status='already_passes',stage='finished');emit();return report
    if modules is None:
        failures=[r for r in rows if r['split']=='development' and not r['passed']]
        if failures and all(set(r.get('codes',[]))=={'ORDER_PROTECTED_BOUNDARY'} for r in failures):modules=['order024.py']
        elif any(c.get('kind')=='instance' for c in cases):modules=['catalogue.py','typography019.py']
    feedback=None
    for number in range(1,max_attempts+1):
        work=folder/f'attempt-{number}';work.mkdir();item={'number':number,'status':'running'};report['attempts'].append(item)
        report['stage']='proposing_patch';emit()
        try:
            response,meta=caller(config,messages(base,[r for r in rows if r['split']=='development' and not r['passed']],feedback,modules),work/'model',max_tokens=8192)
            item['model']=meta
            if not isinstance(response,dict):raise DocumentError('PATCH_SCHEMA')
            if response.get('edits')==[]:raise DocumentError('REPAIR_UNRESOLVED')
            item['patch']=propose(base,work/'engine',response)
            candidate=Engine(work/'engine',engine.image);report['stage']='testing_patch';emit()
            development=[];item['development']=development
            for c in cases:
                if c['split']=='development':development.append(diagnose(candidate,c,work/c['id']));emit()
            complete=all(r['passed'] for r in development)
            partial=improves(rows,development)
            if not complete and not partial:
                item['status']='rejected';feedback={'development':development,'instruction':'Correct the algorithm using the supplied current base code. Do not suppress checks.'};emit();continue
            if not complete:
                # Partial progress is useful only if the candidate still
                # reconstructs every training source. This gate uses the
                # candidate extractor, compiled package and renderer, with
                # frozen teacher labels and external document/page oracles.
                source_instances=[];item['source_instances']=source_instances
                seen=set()
                for c in cases:
                    if c['split']!='development' or not c.get('training'):continue
                    training=c['training']
                    if id(training) in seen:continue
                    seen.add(id(training))
                    source_case={'id':f'source-validation-{len(seen)}','split':'development',
                                 'kind':'source_gate','training':training,
                                 'goldens':[s['source'] for s in training['samples']]}
                    source_instances.append(evaluate(candidate,source_case,
                        work/'source-validation'/str(len(seen))));emit()
                if not source_instances or not all(r['passed'] for r in source_instances):
                    item.update(status='rejected',code='SOURCE_INSTANCE_REGRESSION')
                    feedback={'code':'SOURCE_INSTANCE_REGRESSION','development':development,
                              'source_instances':source_instances,
                              'instruction':'The candidate reduced conflicts but damaged exact source reconstruction. Preserve all observed properties and pages.'}
                    emit();continue
            # Independently corrupt the incoming typography while preserving
            # the text and structure.  Candidate selectors must be no more
            # sensitive to that corruption than the frozen base compiler.
            # This gate uses training inputs only and runs before sealed cases.
            typography=[];item['typography_stability']=typography
            from .leakage034 import compare as compare_typography
            seen=set()
            for c in cases:
                if c['split']!='development' or not c.get('training'):continue
                training=c['training']
                if id(training) in seen:continue
                seen.add(id(training))
                typography.append(compare_typography(engine,candidate,training,
                    base_probe_root/c['id']/'template',work/c['id']/'template',
                    work/'typography-stability'/str(len(seen))))
                emit()
            if any(not gate['passed'] for gate in typography):
                item.update(status='rejected',code='TYPOGRAPHY_LEAKAGE')
                feedback={'code':'TYPOGRAPHY_LEAKAGE',
                          'instruction':'Incoming typography may be corrupted. Avoid font, color, shading, spacing and emphasis as new target-style predictors; use stable semantic or structural evidence.'}
                emit();continue
            # Sealed examples never enter repair model feedback.
            sealed=[];item['sealed']=sealed
            for c in cases:
                if c['split']=='sealed':sealed.append(evaluate(candidate,c,work/c['id']));emit()
            if not all(r['passed'] for r in sealed):
                item.update(status='rejected',code='SEALED_REGRESSION');feedback={'code':'SEALED_REGRESSION','instruction':'Your generalization failed independent cases; their content and outputs are not disclosed.'};emit();continue
            if not complete:
                item.update(status='candidate_progress',retained_for_next_attempt=True)
                base=work/'engine';engine=candidate;rows=development+sealed;base_probe_root=work
                feedback={'development':development,'instruction':'This partial improvement passed all sealed regressions. Continue from the supplied updated code. It is not certified.'}
                emit();continue
            profile={'schema':'engine-profile-034','hashes':candidate.hashes,'image':candidate.image,'scope':'tested_cases_only','universal_correctness':False}
            dump(work/'profile.json',profile);report.update(status='accepted',stage='finished',profile=str(work/'profile.json'),engine=str(work/'engine'))
            item['status']='accepted';emit();return report
        except DocumentError as exc:
            item.update(status='rejected',code=str(exc));emit()
            if str(exc).startswith(('BUDGET','PROVIDER_','WORKER_','REPAIR_UNRESOLVED')):break
            feedback={'code':str(exc)}
    report.update(status='needs_review',stage='finished');emit();return report
