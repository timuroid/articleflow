"""Self-checking template agent: import adaptation, instance replay, stress certification."""
import copy
import json
import time
from pathlib import Path
from . import agent023, typography019 as t
from .adapters028 import normalize
from .docx_engine import NS,DocumentError,dump,digest,load_package,parse_xml,xml_bytes,write_package
from .catalogue import render_catalogue
from .integrity023 import check
from .research import render_pdf,compare_pixels
from .roundtrip022 import neutralize
from .stories026 import roots
from .provider023 import call


def restyle(source,target):
    parts=load_package(source)
    for name,root in roots(parts):
        for p in root.findall('.//w:p',NS):
            pp=p.find('w:pPr',NS)
            if pp is None:pp=t.prop('pPr');p.insert(0,pp)
            for local in ('spacing','ind','jc'):
                for old in list(pp.findall('w:'+local,NS)):pp.remove(old)
            pp.extend([t.prop('spacing',before=160,after=200,line=360,lineRule='auto'),t.prop('ind',left=360,firstLine=180),t.prop('jc',val='left')])
            for r in p.findall('.//w:r',NS):
                rp=r.find('w:rPr',NS)
                if rp is None:rp=t.prop('rPr');r.insert(0,rp)
                for local in ('rFonts','sz','szCs','color'):
                    for old in list(rp.findall('w:'+local,NS)):rp.remove(old)
                rp.extend([t.prop('rFonts',ascii='Arial',hAnsi='Arial'),t.prop('sz',val=28),t.prop('szCs',val=28),t.prop('color',val='7030A0')])
        if name=='word/document.xml':
            document=parse_xml(parts[name]);document.replace(document.find('w:body',NS),root);parts[name]=xml_bytes(document)
        else:parts[name]=xml_bytes(root)
    write_package(target,parts)
    if not all(check(source,target).values()):raise DocumentError('MUTATION_CONTENT_CHANGED')


def permute(source,target):
    """Swap two adjacent plain paragraphs only; section/object/table boundaries are barriers."""
    parts=load_package(source);root=parse_xml(parts['word/document.xml']);body=root.find('w:body',NS)
    def safe(p):
        return p.tag==t.tag('p') and bool(p.findall('.//w:t',NS)) and not p.xpath('.//w:sectPr | .//w:numPr | .//w:bookmarkStart | .//w:bookmarkEnd | .//w:hyperlink | .//w:drawing | .//w:fldChar | .//w:fldSimple | .//m:oMath | .//w:pStyle',namespaces=NS)
    for i in range(len(body)-1):
        if safe(body[i]) and safe(body[i+1]) and all(n.tag in {t.tag('p'),t.tag('sectPr')} for n in list(body)[max(0,i-1):i+3]):
            a,b=body[i],body[i+1];body.remove(b);body.insert(i,b)
            parts['word/document.xml']=xml_bytes(root);write_package(target,parts)
            return {'applied':True,'swapped':[i,i+1]}
    return {'applied':False,'reason':'NO_SAFE_ADJACENT_BLOCKS'}


def run(references,folder,teacher,student,*,max_iterations=3,caller=call,progress=None,context='',feedback_provider=None,max_calls=40,seconds=1800,validation_sources=()):
    folder=Path(folder);started=time.monotonic();calls=0;preparation=[];history=[]
    original_hashes=[digest(p.read_bytes()) for p in references]
    limits={'iterations':max_iterations,'model_calls':max_calls,'seconds':seconds,'cost':'shared_provider_ledger_cap'}
    def emit(report):
        report.update(contract='adaptive-template-028',source_hashes=original_hashes,preparation=copy.deepcopy(preparation),limits=limits,model_calls=calls,elapsed_seconds=round(time.monotonic()-started,2),call_history=copy.deepcopy(history))
        dump(folder/'result.json',report)
        if progress:progress(copy.deepcopy(report))
    def bounded(config,messages,directory,**kwargs):
        nonlocal calls
        if calls>=max_calls:raise DocumentError('AGENT_CALL_LIMIT')
        if time.monotonic()-started>seconds:raise DocumentError('AGENT_TIME_LIMIT')
        calls+=1
        try:return caller(config,messages,directory,**kwargs)
        finally:
            meta=Path(directory)/'meta.json'
            if meta.exists():
                record=json.loads(meta.read_text());history.append({**record,'stage_path':str(Path(directory).relative_to(folder)),'elapsed_seconds':round(time.monotonic()-started,2)})
    report={'schema':'teacher-student-023','status':'running','stage':'preflight','iterations':[],'training_documents':len(references)}
    folder.mkdir(parents=True,exist_ok=False);emit(report)
    prepared=[]
    try:
        for i,source in enumerate(references,1):
            entry={'document':i,'attempts':[]};preparation.append(entry);emit(report)
            golden=render_pdf(source,folder/f'preparation-{i}'/'golden')
            accepted=None
            for attempt in range(2):
                work=folder/f'preparation-{i}'/f'attempt-{attempt+1}';candidate=source
                observation={'number':attempt+1};entry['attempts'].append(observation);emit(report)
                try:
                    if attempt:
                        candidate=work/'normalized.docx';observation['adaptation']=normalize(source,candidate)
                        if not observation['adaptation']['removed_nodes']:raise DocumentError('NO_APPLICABLE_IMPORT_ADAPTER')
                    extracted=work/'extracted';agent023.extract_input(candidate,extracted)
                    plan=json.loads((extracted/'oracle-plan.json').read_text())
                    rebuilt=work/'reconstructed.docx';render_catalogue(extracted/'template',extracted/'content',plan,rebuilt)
                    integrity=check(candidate,rebuilt);pixels=compare_pixels(golden,render_pdf(rebuilt,work/'render'))
                    observation.update(integrity=integrity,pixels=pixels)
                    if not all(integrity.values()) or not pixels['pixel_exact']:raise DocumentError('INSTANCE_REPLAY_MISMATCH')
                    observation['status']='passed';accepted=candidate;break
                except DocumentError as exc:
                    observation.update(status='failed',code=str(exc));emit(report)
                    if attempt or str(exc) not in {'CATALOGUE_INLINE_UNSUPPORTED','EMPTY_RUN_UNSUPPORTED'}:raise
            if accepted is None:raise DocumentError('IMPORT_ADAPTATION_EXHAUSTED')
            prepared.append(accepted);entry['status']='instance_verified';emit(report)
        # Existing learner owns a subdirectory; outer report remains the authoritative web state.
        def stress(samples,template,work):
            rows=[]
            package=json.loads((template/'semantic.json').read_text());package['import_policy']='annotations-028';dump(template/'semantic.json',package)
            for i,sample in enumerate(samples,1):
                base=work/f'stress-{i}';base.mkdir();neutral=base/'neutral.docx';neutralize(sample['source'],neutral)
                styled=base/'restyled.docx';restyle(neutral,styled)
                shuffled=base/'permuted.docx';movement=permute(styled,shuffled)
                variants=[('restyled',styled)]
                if movement['applied']:variants.append(('permuted',shuffled))
                else:rows.append({'document':i,'variant':'permuted','status':'not_applicable','reason':movement['reason']})
                for name,path in variants:
                    row={'document':i,'variant':name,'status':'failed'};rows.append(row)
                    try:
                        result=agent023.apply(path,template,base/name,student,caller=bounded)
                        row.update(unresolved_count=len(result['unresolved']),status=result['status'])
                        if result.get('pdf'):
                            pixels=compare_pixels(sample['golden'],Path(result['pdf']));row['pixels']=pixels
                            row['passed']=pixels['pixel_exact'] and result.get('content_exact',False)
                        else:row['passed']=False
                    except DocumentError as exc:row.update(code=str(exc),passed=False)
            for i,source in enumerate(validation_sources,1):
                row={'document':i,'variant':'user_feedback_example','scope':'structural_only','passed':False};rows.append(row)
                try:
                    result=agent023.apply(source,template,work/f'feedback-example-{i}',student,caller=bounded)
                    row.update(status=result['status'],unresolved_count=len(result['unresolved']),passed=result['status']=='rendered_unverified' and not result['unresolved'])
                except DocumentError as exc:row.update(status='failed',code=str(exc))
            return rows
        result=agent023.run(prepared,folder/'learning',teacher,student,max_iterations=max_iterations,caller=bounded,progress=emit,context=context,feedback_provider=feedback_provider,acceptance_probe=stress,adaptive=True)
        result['effective_source_hashes']=[digest(p.read_bytes()) for p in prepared]
        if result['status']=='reference_verified':
            result['certification']={'instance_replay':True,'stress_passed':True,'scope':'references_and_applicable_mutations','universal_accuracy_proven':False}
        emit(result);return result
    except DocumentError as exc:report.update(status='needs_review',code=str(exc),last_stage=report.get('stage'),stage='finished')
    except Exception as exc:report.update(status='unavailable',code='PREPARATION_UNAVAILABLE',error_type=type(exc).__name__,stage='finished')
    emit(report);return report
