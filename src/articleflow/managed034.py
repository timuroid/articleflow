"""Automatic escalation from template learning to managed engine repair."""
import json,os
from pathlib import Path,PurePosixPath
from .docx_engine import DocumentError,dump
from .sandbox034 import Engine,file_hashes,use,ACTIVE
from .provider023 import call


def load_engine(root,profile):
    relative=PurePosixPath(profile['path'])
    if relative.is_absolute() or '..' in relative.parts:raise DocumentError('ENGINE_PROFILE_PATH')
    path=Path(root).joinpath(*relative.parts)
    if any(p.is_symlink() for p in [path,*path.parents]):raise DocumentError('ENGINE_PROFILE_PATH')
    if file_hashes(path)!=profile['hashes']:raise DocumentError('ENGINE_PROFILE_CHANGED')
    engine=Engine(path,profile['image'])
    if engine.image!=profile['image']:raise DocumentError('ENGINE_IMAGE_CHANGED')
    return engine


def pick_replay_work(folder,count):
    """Use the strongest completed training evidence, never just the last try."""
    works=[folder/'learning'/f'iteration-{number}' for number in range(1,count+1)
           if (folder/'learning'/f'iteration-{number}'/'teacher/validated.json').exists()]
    student=[work for work in works if any(
        (application/'effective-student.json').exists() or
        (application/'student/validated.json').exists()
        for application in work.glob('application-*') if application.is_dir())]
    if student:return student[-1]
    completed=[work for work in works if (work/'training-conflicts.json').exists()]
    if completed:
        return min(completed,key=lambda work:(len(json.loads((work/'training-conflicts.json').read_text())),
                                              int(work.name.split('-')[-1])))
    return works[-1] if works else None


def collect(references,folder,result):
    from .semantic023 import expand_groups
    from .inline026 import validate,overlay
    from .rules023 import semantic_spans
    count=len(result.get('iterations',[]))
    work=pick_replay_work(folder,count)
    if work is None:
        cases=[]
        for i,reference in enumerate(references,1):
            normalized=folder/f'preparation-{i}/attempt-2/normalized.docx'
            cases.append({'id':f'instance-{i}','kind':'instance','split':'development','source':normalized if normalized.exists() else reference,'golden':reference})
        return cases
    response=json.loads((work/'effective-teacher.json' if (work/'effective-teacher.json').exists() else work/'teacher/validated.json').read_text());samples=[];allblocks=[]
    for i,reference in enumerate(references,1):
        normalized=folder/f'preparation-{i}/attempt-2/normalized.docx';source=normalized if normalized.exists() else reference
        extracted=folder/f'learning/reference-{i}/extracted'
        content=json.loads((extracted/'content/content.json').read_text())
        samples.append({'content':content,'extracted':extracted,'semantics':semantic_spans(source),'source':source})
        allblocks.extend({**b,'id':f'{i-1}:'+b['id']} for b in content['blocks'])
    labels=expand_groups(response,allblocks);inline=validate(response,allblocks)
    training={'samples':[{**s,'semantics':overlay(s['semantics'],{b['id']:inline[f'{i}:'+b['id']] for b in s['content']['blocks']}) if response.get('inline_roles') else s['semantics']} for i,s in enumerate(samples)],
              'labels':[{b['id']:labels[f'{i}:'+b['id']] for b in s['content']['blocks']} for i,s in enumerate(samples)],'roles':response['roles'],'inline_roles':response.get('inline_roles')}
    cases=[]
    for i,sample in enumerate(samples,1):
        candidates=[(work/f'application-{i}',work/f'degraded-{i}.docx','normal')]
        candidates += [(work/f'stress-{i}'/v,work/f'stress-{i}'/(v+'.docx'),v) for v in ['restyled','permuted']]
        for application,source,variant in candidates:
            effective=application/'effective-student.json'
            response_path=effective if effective.exists() else application/'student/validated.json'
            if not response_path.exists():continue
            cases.append({'id':f'document-{i}-{variant}','split':'development','source':source,'template':work/'template',
                          'teacher_iteration':int(work.name.split('-')[-1]),
                          'response':json.loads(response_path.read_text()),'golden':sample['source'],'training':training})
    if not cases:
        # A compiler conflict may prevent the first student call. Replay the
        # frozen teacher labels against candidate extraction without inventing
        # a student response or claiming that instance fidelity proves transfer.
        cases.append({'id':'training-only','kind':'training','split':'development',
                      'teacher_iteration':int(work.name.split('-')[-1]),
                      'training':training,'goldens':list(references)})
    return cases


def run(references,folder,teacher,student,*,caller=call,progress=None,repair_image=None,max_calls=40,**kwargs):
    from .agent028 import run as learn
    folder=Path(folder);image=repair_image or teacher.get('repair_image') or os.environ.get('ARTICLEFLOW_REPAIR_IMAGE');calls=0
    def bounded(*a,**kw):
        nonlocal calls
        if calls>=max_calls:raise DocumentError('AGENT_CALL_LIMIT')
        calls+=1;return caller(*a,**kw)
    result=learn(references,folder,teacher,student,caller=bounded,progress=progress,max_calls=max_calls,**kwargs)
    if result['status']=='reference_verified':return result
    dump(folder/'before-engine-repair.json',result)
    result['engine_repair']={'status':'not_configured' if not image else 'preparing'}
    def emit(stage=None):
        if stage:result.update(status='running',stage=stage)
        dump(folder/'result.json',result)
        if progress:progress(dict(result))
    if not image:emit();return result
    # Do not ask a code model to repair an exhausted account or failed transport.
    if str(result.get('code','')).startswith(('BUDGET','PROVIDER_','AGENT_CALL_LIMIT','AGENT_TIME_LIMIT')):emit();return result
    try:
        cases=collect(references,folder,result)
        if not cases:
            result['engine_repair']={'status':'needs_review','code':'NO_REPLAYABLE_FAILURE'};emit();return result
        if cases[0].get('teacher_iteration'):
            result['repair_source_iteration']=cases[0]['teacher_iteration']
            emit('engine_selecting_replay')
        from .probes034 import create
        # Independent corruption mechanism supplies diagnostic and sealed cases.
        # The proposal cannot choose either set or their expected outputs.
        with use(None):guards=create(folder/'repair-guards')
        from .repair034 import run as repair
        def repairing(r):
            result['engine_repair']={k:r[k] for k in ('status','stage','seconds') if k in r}
            latest=r.get('attempts',[])[-1] if r.get('attempts') else {}
            result['engine_repair'].update(total_probes=r['tests'],completed_probes=len(r.get('baseline',[])) if r['stage']=='baseline' else len(latest.get('development',[]))+len(latest.get('sealed',[])))
            emit('engine_'+r['stage'])
        repaired=repair(ACTIVE.get().source if ACTIVE.get() else Path(__file__).parent,cases+guards,folder/'repair',teacher,caller=bounded,image=image,progress=repairing)
        result['engine_repair']={k:v for k,v in repaired.items() if k not in {'baseline','attempts','base_hashes'}}
        if repaired['status']!='accepted':result.update(status='needs_review',stage='finished');emit();return result
        profile=json.loads(Path(repaired['profile']).read_text());profile['path']=str(Path(repaired['engine']).relative_to(folder))
        engine=load_engine(folder,profile)
        result['engine_profile']=profile;emit('engine_rechecking')
        # A patch passing probes still does not certify a template: run the full
        # independent corruption loop again, with fresh semantic model calls.
        def rechecking(r):
            live={**r,'engine_profile':profile,'engine_learning_root':'engine-replay/learning','engine_repair':result['engine_repair']}
            dump(folder/'result.json',live)
            if progress:progress(live)
        with use(engine):
            replay=learn(references,folder/'engine-replay',teacher,student,caller=bounded,progress=rechecking,max_calls=max_calls,**kwargs)
        replay.update(engine_profile=profile,engine_learning_root='engine-replay/learning',engine_repair=result['engine_repair'],managed_model_calls=calls)
        dump(folder/'result.json',replay);return replay
    except DocumentError as exc:
        result.update(status='needs_review',stage='finished',engine_repair={'status':'unavailable','code':str(exc)})
        emit();return result
