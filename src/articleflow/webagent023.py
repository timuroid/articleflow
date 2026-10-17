"""Teacher/student learning and explicit requirement decisions in the web app."""
import json
import shutil
from pathlib import Path
from typing import Literal
from fastapi import BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .docx_engine import DocumentError, digest


class LearnRequest(BaseModel):
    consent_external: bool = False
    context: str = Field(default='',max_length=12000)
    iterations: int = Field(default=5,ge=1,le=8)
    mode: Literal['automatic','assisted'] = 'automatic'
    validation_job_id: str | None = None


class LearningFeedback(BaseModel):
    expected_revision: int = Field(ge=0)
    text: str = Field(min_length=1,max_length=12000)


class LearnApproval(BaseModel):
    run_id: str
    required_roles: list[str] = Field(default_factory=list)
    answers: dict[str,bool] = Field(default_factory=dict)


class RequirementAnswers(BaseModel):
    expected_version: int
    answers: dict[str,bool]


def mount(app,store,csrf):
    from .web017 import _latest,_uid,_now,model_config
    store.execute('CREATE TABLE IF NOT EXISTS learning_feedback024 (run_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, text TEXT NOT NULL)')
    def learn(run_id,context,iterations,mode,validation_job_id=None):
        from .agent028 import run
        with store.batch_lock:
            row=store.one('SELECT * FROM template_runs WHERE id=?',(run_id,))
            paths=sorted(store.path('templates',row['template_id'],'samples').glob('*.docx'))
            def feedback():
                rows=store.all('SELECT revision,text FROM learning_feedback024 WHERE run_id=?',(run_id,))
                return dict(rows[0]) if rows else {'revision':0,'text':''}
            def progress(r):
                r={**r,'mode':mode,'feedback_revision_received':feedback()['revision']}
                store.execute('UPDATE template_runs SET status=?,report_json=? WHERE id=?',
                              (r['status'],json.dumps(r,ensure_ascii=False),run_id))
            try:
                config=model_config()
                if config is None:raise DocumentError('MODEL_NOT_PROVISIONED')
                result=run(paths,store.path('template-runs',run_id),
                       {**config,'model':config.get('teacher023','openai/gpt-6.1-sol'),'reasoning_effort':'low'},
                       {**config,'model':config.get('student023','qwen/qwen3.8-27b'),'reasoning_effort':'none'},
                       context=context,max_iterations=iterations,progress=progress,feedback_provider=feedback,validation_sources=([store.path('jobs',validation_job_id,'source.docx')] if validation_job_id else []))
                if result['status']=='reference_verified':
                    directory=Path(result['template'])
                    result['package_hashes']={name:digest((directory/name).read_bytes()) for name in ('rules.json','semantic.json','resources.zip')}
                progress(result)
                if mode=='automatic' and result['status']=='reference_verified':
                    try:
                        published=approve(row['template_id'],LearnApproval(run_id=run_id))
                        result['published_version']=published['version']
                    except HTTPException as exc:
                        result['publication_blocked']=exc.detail
                    progress(result)
            except Exception as exc:
                progress({'schema':'teacher-student-023','status':'needs_review',
                          'code':str(exc) if isinstance(exc,DocumentError) else 'LEARNING_UNAVAILABLE'})

    @app.post('/api/v017/templates/{template_id}/learn',dependencies=[Depends(csrf)])
    def start(template_id:str,body:LearnRequest,background:BackgroundTasks):
        if not body.consent_external or model_config() is None:raise HTTPException(400,'MODEL_CONSENT_OR_CONFIG_REQUIRED')
        version=_latest(store,template_id)
        pending=store.all("SELECT id FROM template_runs WHERE template_id=? AND status IN ('queued','running')",(template_id,))
        if pending:raise HTTPException(409,'TEMPLATE_RUN_IN_PROGRESS')
        run_id=_uid()
        store.execute('INSERT INTO template_runs VALUES (?,?,?,?,?,?)',(run_id,template_id,version['version'],'queued',json.dumps({'schema':'teacher-student-023'}),_now()))
        if body.validation_job_id:
            rows=store.all('SELECT b.template_id FROM jobs j JOIN batches b ON j.batch_id=b.id WHERE j.id=?',(body.validation_job_id,))
            if not rows or rows[0]['template_id']!=template_id:
                store.execute('DELETE FROM template_runs WHERE id=?',(run_id,))
                raise HTTPException(400,'VALIDATION_JOB_TEMPLATE_MISMATCH')
        background.add_task(learn,run_id,body.context,body.iterations,body.mode,body.validation_job_id)
        return {'id':run_id,'status':'queued'}

    @app.post('/api/v017/template-runs/{run_id}/feedback',dependencies=[Depends(csrf)])
    def submit_feedback(run_id:str,body:LearningFeedback):
        if not body.text.strip():raise HTTPException(400,'FEEDBACK_EMPTY')
        with store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row=con.execute('SELECT status,report_json FROM template_runs WHERE id=?',(run_id,)).fetchone()
            if row is None:raise HTTPException(404,'NOT_FOUND')
            report=json.loads(row['report_json'])
            if report.get('schema')!='teacher-student-023' or row['status'] not in ('queued','running'):
                raise HTTPException(409,'LEARNING_FINISHED_START_NEW_RUN')
            previous=con.execute('SELECT revision FROM learning_feedback024 WHERE run_id=?',(run_id,)).fetchone()
            revision=previous['revision'] if previous else 0
            if revision!=body.expected_revision:raise HTTPException(409,'FEEDBACK_VERSION_CHANGED')
            con.execute('INSERT OR REPLACE INTO learning_feedback024 VALUES (?,?,?)',(run_id,revision+1,body.text))
            report['feedback_revision_received']=revision+1
            con.execute('UPDATE template_runs SET report_json=? WHERE id=?',(json.dumps(report,ensure_ascii=False),run_id))
        return {'revision':revision+1,'applies':'next_iteration','already_applied':False}

    @app.get('/api/v017/template-runs/{run_id}/agent-preview/{sample}/{mode}')
    def preview(run_id:str,sample:int,mode:str):
        row=store.one('SELECT * FROM template_runs WHERE id=?',(run_id,));report=json.loads(row['report_json'])
        if report.get('schema')!='teacher-student-023' or not 1<=sample<=report.get('training_documents',0):raise HTTPException(404,'NOT_FOUND')
        run_root=store.path('template-runs',run_id)
        if report.get('contract')=='adaptive-template-028':run_root=run_root/'learning'
        if mode=='reference':folder=run_root/f'reference-{sample}'/'reference'
        elif mode=='result':folder=run_root/f'iteration-{len(report["iterations"])}'/f'application-{sample}'/'render'
        else:raise HTTPException(404,'NOT_FOUND')
        files=list(folder.glob('*.pdf'))
        if len(files)!=1:raise HTTPException(404,'PREVIEW_UNAVAILABLE')
        return FileResponse(files[0],media_type='application/pdf')

    @app.post('/api/v017/templates/{template_id}/approve-agent',dependencies=[Depends(csrf)])
    def approve(template_id:str,body:LearnApproval):
        row=store.one('SELECT * FROM template_runs WHERE id=? AND template_id=?',(body.run_id,template_id))
        report=json.loads(row['report_json']);version=_latest(store,template_id)
        if row['base_version']!=version['version']:raise HTTPException(409,'TEMPLATE_VERSION_CHANGED')
        if report.get('schema')!='teacher-student-023' or report.get('status')!='reference_verified':raise HTTPException(409,'AGENT_NOT_VERIFIED')
        if not report.get('negative_controls') or not all(c.get('detected') for c in report['negative_controls']):raise HTTPException(409,'NEGATIVE_CONTROL_REQUIRED')
        paths=sorted(store.path('templates',template_id,'samples').glob('*.docx'))
        if [digest(p.read_bytes()) for p in paths]!=report['source_hashes']:raise HTTPException(409,'REFERENCE_CHANGED')
        run_root=store.path('template-runs',body.run_id)
        if report.get('contract')=='adaptive-template-028':
            if not all(report.get('certification',{}).get(k) is True for k in ('instance_replay','stress_passed')):raise HTTPException(409,'STRESS_CERTIFICATION_REQUIRED')
            run_root=run_root/'learning'
        directory=run_root/f'iteration-{len(report["iterations"])}'/'template'
        expected=report.get('package_hashes',{})
        if set(expected)!={'rules.json','semantic.json','resources.zip'} or any(digest((directory/n).read_bytes())!=h for n,h in expected.items()):raise HTTPException(409,'PACKAGE_CHANGED')
        feedback_rows=store.all('SELECT revision FROM learning_feedback024 WHERE run_id=?',(body.run_id,))
        if feedback_rows and feedback_rows[0]['revision']>report.get('feedback_revision_applied',0):
            raise HTTPException(409,'FEEDBACK_NOT_APPLIED_START_NEW_RUN')
        package=json.loads((directory/'semantic.json').read_text())
        roles=set(package['roles'])
        if not set(body.required_roles)<=roles or not set(body.answers)<=roles:raise HTTPException(400,'REQUIRED_ROLE_INVALID')
        if report.get('mode','assisted')!='automatic' and any(q['role'] not in body.answers for q in report.get('questions',[])):raise HTTPException(409,'REQUIREMENT_QUESTIONS_UNANSWERED')
        required=sorted((set(body.required_roles)|{r for r,v in body.answers.items() if v})-{r for r,v in body.answers.items() if not v})
        spec=json.loads(version['spec_json']);spec['agent023']={'run_id':body.run_id,'iteration':len(report['iterations']),
             'contract':report.get('contract'),'mode':report.get('mode','assisted'),'package_hashes':expected,'required_roles':required,'answers':body.answers,'roles':package['roles'],
             'student_model':report['student_model'],'verification':'reference_verified','held_out_transfer':report['held_out_transfer']}
        with store.connect() as con:
            current=con.execute('SELECT MAX(version) FROM template_versions WHERE template_id=?',(template_id,)).fetchone()[0]
            if current!=version['version']:raise HTTPException(409,'TEMPLATE_VERSION_CHANGED')
            con.execute('INSERT INTO template_versions VALUES (?,?,?,?,?)',(template_id,current+1,json.dumps(spec,ensure_ascii=False),1,_now()))
        return {'version':current+1,'approved':True}

    @app.post('/api/v017/templates/{template_id}/requirements',dependencies=[Depends(csrf)])
    def requirements(template_id:str,body:RequirementAnswers):
        version=_latest(store,template_id);spec=json.loads(version['spec_json']);settings=spec.get('agent023')
        if not settings or version['version']!=body.expected_version:raise HTTPException(409,'TEMPLATE_VERSION_CHANGED')
        if not set(body.answers)<=set(settings['roles']):raise HTTPException(400,'REQUIRED_ROLE_INVALID')
        settings['answers'].update(body.answers)
        settings['required_roles']=sorted((set(settings['required_roles'])|{r for r,v in body.answers.items() if v})-{r for r,v in body.answers.items() if not v})
        with store.connect() as con:
            current=con.execute('SELECT MAX(version) FROM template_versions WHERE template_id=?',(template_id,)).fetchone()[0]
            if current!=body.expected_version:raise HTTPException(409,'TEMPLATE_VERSION_CHANGED')
            con.execute('INSERT INTO template_versions VALUES (?,?,?,?,?)',(template_id,current+1,json.dumps(spec,ensure_ascii=False),version['approved'],_now()))
        return {'version':current+1,'approved':bool(version['approved'])}


def process_job(store,job,batch,version,spec):
    from .agent023 import apply
    from .web017 import model_config,font_audit
    from .documentcheck022 import check
    folder=store.path('jobs',job['id'],'revisions',str(job['revision']));folder.mkdir(parents=True,exist_ok=True)
    settings=spec['agent023'];config=model_config()
    if not batch.get('use_llm') or config is None:raise DocumentError('AGENT_REQUIRES_MODEL_CONSENT')
    run_root=store.path('template-runs',settings['run_id'])
    if settings.get('contract')=='adaptive-template-028':run_root=run_root/'learning'
    template=run_root/f'iteration-{settings["iteration"]}'/'template'
    if any(digest((template/n).read_bytes())!=h for n,h in settings['package_hashes'].items()):raise DocumentError('PACKAGE_CHANGED')
    source=store.path('jobs',job['id'],'source.docx')
    result=apply(source,template,folder/'application',{**config,'model':settings['student_model'],'reasoning_effort':'none'})
    content=json.loads((folder/'application/input-original.json').read_text())
    present={result['assignments'][b['id']] for b in content['blocks'] if b['text'].strip()}
    missing=[r for r in settings['required_roles'] if r not in present]
    package=json.loads((template/'semantic.json').read_text())
    unconfirmed_missing=[r for r in package.get('observed_top_level_roles',[]) if r not in present and r not in settings.get('answers',{}) and r not in missing]
    report={**result,'status':'draft','missing':missing,'questions':[],
            'result_available':bool(result.get('pdf')) and result['status']!='integrity_failed',
            'unconfirmed_missing':unconfirmed_missing,
            'template_id':batch['template_id'],'template_version':batch['template_version'],'revision':job['revision']}
    if result['status']=='integrity_failed':report['status']='error';report['questions'].append('Нарушена целостность документа; результат заблокирован.')
    elif result.get('pdf'):
        shutil.copyfile(folder/'application/result.docx',folder/'result.docx')
        visual=check(folder/'result.docx',folder/'visual',repair=False);report['visual_validation']=visual
        fonts=font_audit();report['font_audit']=fonts
        if visual['status']=='passed' and fonts['exact'] and not missing and (not unconfirmed_missing or settings.get('mode')=='automatic'):report['status']='ready'
    if missing:report['questions'].append('Отсутствуют обязательные блоки: '+', '.join(missing))
    if unconfirmed_missing and settings.get('mode')!='automatic':report['questions'].append('В эталоне были блоки, которых нет в статье. Уточните, допустимо ли их отсутствие: '+', '.join(unconfirmed_missing))
    if result.get('unresolved'):report['questions'].append('Для части блоков нет однозначного правила оформления.')
    report.pop('assignments',None);report.pop('pdf',None)
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    store.execute('UPDATE jobs SET status=?,report_json=? WHERE id=?',(report['status'],json.dumps(report,ensure_ascii=False),job['id']))
