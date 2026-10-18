import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from docx import Document
from fastapi.testclient import TestClient
from articleflow.web017 import create_app
from articleflow.docx_engine import digest
from articleflow.webagent023 import learning_model_configs,process_job

class AdaptiveWebTests(unittest.TestCase):
    def test_learning_models_share_ledger_and_visual_default_is_separate(self):
        config={'key_file':'key','ledger':'same-ledger','model':'unused'}
        teacher,student=learning_model_configs(config)
        self.assertEqual(teacher['model'],'openai/gpt-6.1-sol')
        self.assertEqual(teacher['visual_model'],'inclusionai/ling-3.0-flash-vl')
        self.assertEqual(student['model'],'qwen/qwen3.8-27b')
        self.assertEqual(teacher['ledger'],student['ledger'])
        self.assertEqual(teacher['key_file'],student['key_file'])
        self.assertEqual(config['model'],'unused')
        override,_=learning_model_configs({**config,'visual_model':'example/vision'})
        self.assertEqual(override['visual_model'],'example/vision')

    def test_batch_uses_bounded_inline_repair_config(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            class Store:
                def __init__(self):self.updates=[]
                def path(self,*parts):return root.joinpath(*parts)
                def execute(self,sql,args):self.updates.append((sql,args))
            store=Store();template=store.path('template-runs','run','iteration-1','template')
            template.mkdir(parents=True)
            for name,payload in [('rules.json','{}'),('semantic.json','{"roles":{"body":"Body"}}'),('resources.zip','fixture')]:
                (template/name).write_text(payload)
            source=store.path('jobs','job','source.docx');source.parent.mkdir(parents=True);source.write_bytes(b'fixture')
            settings={'run_id':'run','iteration':1,'student_model':'qwen/qwen3.8-27b',
                      'package_hashes':{name:digest((template/name).read_bytes()) for name in ('rules.json','semantic.json','resources.zip')},
                      'required_roles':[],'answers':{},'mode':'automatic'}
            calls=[]
            def apply_stub(path,package,folder,config):
                calls.append(config)
                self.assertEqual(path,source)
                self.assertEqual(package,template)
                folder.mkdir(parents=True)
                (folder/'input-original.json').write_text('{"blocks":[{"id":"b-1","text":"Text"}]}')
                return {'status':'needs_review','assignments':{'b-1':'body'},'unresolved':[],
                        'model_invocations':1,'strict_one_pass_eligible':True}
            with patch('articleflow.web017.model_config',return_value={'model':'other','inline_repair_attempts':0}),\
                 patch('articleflow.agent023.apply',side_effect=apply_stub):
                process_job(store,{'id':'job','revision':0},{'use_llm':True,'template_id':'template','template_version':1},
                            {'version':1},{'agent023':settings})
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0]['model'],'qwen/qwen3.8-27b')
            self.assertEqual(calls[0]['inline_repair_attempts'],1)
            self.assertEqual(calls[0]['reasoning_effort'],'none')
            report=json.loads(store.path('jobs','job','revisions','0','report.json').read_text())
            self.assertEqual(report['model_invocations'],1)
            self.assertTrue(report['strict_one_pass_eligible'])

    def test_agentic_intake_and_certification_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source.docx';d=Document();d.add_paragraph('Synthetic');d.save(source)
            certificate={'instance_replay':True,'stress_passed':False}
            def run(paths,folder,*a,**kw):
                self.assertTrue(a[0]['triage_conflicts'])
                self.assertEqual(a[0]['model'],'openai/gpt-6.1-sol')
                self.assertEqual(a[0]['visual_model'],'inclusionai/ling-3.0-flash-vl')
                package=folder/'learning/iteration-1/template';package.mkdir(parents=True)
                for name,value in [('rules.json','{}'),('semantic.json','{"roles":{"body":"Body"}}'),('resources.zip','fixture')]: (package/name).write_text(value)
                return {'schema':'teacher-student-023','contract':'adaptive-template-032','status':'reference_verified','template':str(package),'iterations':[{'number':1,'applications':[]}],'source_hashes':[digest(p.read_bytes()) for p in paths],'negative_controls':[{'detected':True}],'certification':dict(certificate),'questions':[],'student_model':'fixture','held_out_transfer':'not_measured'}
            with patch('articleflow.web017.model_config',return_value={'model':'fixture'}),patch('articleflow.agent028.run',side_effect=run),patch('articleflow.templateagent022.run') as legacy:
                app=create_app(root/'web')
                with TestClient(app) as c:
                    h={'X-CSRF-Token':c.get('/api/v017/config').json()['csrf_token']}
                    r=c.post('/api/v017/templates',data={'name':'Synthetic','agentic':'true'},files={'files':('s.docx',source.read_bytes())},headers=h)
                    self.assertEqual(r.status_code,200,r.text);tid=r.json()['id'];legacy.assert_not_called()
                    self.assertTrue(c.get(f'/api/v017/templates/{tid}').json()['spec']['pending_agent'])
                    for cert,expected in [({'instance_replay':True,'stress_passed':False},False),({'stress_passed':True},False),({'instance_replay':True,'stress_passed':True},False),({'instance_replay':True,'stress_passed':True,'format_properties_exact':True},True)]:
                        certificate.clear();certificate.update(cert)
                        r=c.post(f'/api/v017/templates/{tid}/learn',json={'consent_external':True},headers=h)
                        self.assertEqual(r.status_code,200,r.text)
                        self.assertEqual(c.get(f'/api/v017/templates/{tid}').json()['approved'],expected)
                    self.assertEqual(c.get('/templates').status_code,200)
                    r=c.post(f'/api/v017/templates/{tid}/learn',json={'consent_external':True,'validation_job_id':'foreign-or-missing'},headers=h)
                    self.assertEqual(r.status_code,400)
