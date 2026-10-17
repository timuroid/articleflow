import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from docx import Document
from fastapi.testclient import TestClient
from articleflow.web017 import create_app
from articleflow.docx_engine import digest


class LearningModesTests(unittest.TestCase):
    def test_automatic_publishes_only_verified_package_without_inventing_mandatory_roles(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source.docx';d=Document();d.add_paragraph('Тест');d.save(source)
            late={'enabled':False}
            def fake_run(paths,folder,*args,**kwargs):
                package=folder/'iteration-1/template';package.mkdir(parents=True)
                for name,data in [('rules.json','{}'),('semantic.json',json.dumps({'roles':{'funding':'Сведения о финансировании'}})),('resources.zip','fixture')]:
                    (package/name).write_text(data)
                self.assertEqual(kwargs['feedback_provider'](),{'revision':0,'text':''})
                if late['enabled']:
                    app.state.store.execute('INSERT INTO learning_feedback024 VALUES (?,?,?)',(folder.name,1,'Новое требование'))
                return {'schema':'teacher-student-023','status':'reference_verified','template':str(package),
                        'iterations':[{'number':1,'applications':[]}],'source_hashes':[digest(p.read_bytes()) for p in paths],
                        'questions':[{'role':'funding','question':'Финансирование обязательно?'}],
                        'negative_controls':[{'detected':True}],'student_model':'fixture','held_out_transfer':'not_measured'}
            with patch('articleflow.web017.model_config',return_value={'model':'fixture'}),patch('articleflow.templateagent022.run',return_value={'status':'needs_review'}),patch('articleflow.agent028.run',side_effect=fake_run):
                app=create_app(root/'web')
                with TestClient(app) as client:
                    headers={'X-CSRF-Token':client.get('/api/v017/config').json()['csrf_token']}
                    tid=client.post('/api/v017/templates',data={'name':'Synthetic'},files={'files':('test.docx',source.read_bytes())},headers=headers).json()['id']
                    response=client.post(f'/api/v017/templates/{tid}/learn',json={'consent_external':True},headers=headers)
                    self.assertEqual(response.status_code,200,response.text)
                    version=client.get(f'/api/v017/templates/{tid}').json()
                    self.assertTrue(version['approved']);self.assertEqual(version['spec']['agent023']['required_roles'],[])
                    self.assertEqual(version['spec']['agent023']['mode'],'automatic')
                    rid=response.json()['id'];report=client.get(f'/api/v017/template-runs/{rid}').json()['report']
                    self.assertEqual(report['published_version'],2)
                    self.assertEqual(client.post(f'/api/v017/template-runs/{rid}/feedback',json={'expected_revision':0,'text':'Позднее уточнение'},headers=headers).status_code,409)

                    late['enabled']=True
                    second=client.post(f'/api/v017/templates/{tid}/learn',json={'consent_external':True},headers=headers)
                    second_report=client.get(f'/api/v017/template-runs/{second.json()["id"]}').json()['report']
                    self.assertEqual(second_report['publication_blocked'],'FEEDBACK_NOT_APPLIED_START_NEW_RUN')
                    self.assertEqual(client.get(f'/api/v017/templates/{tid}').json()['version'],2)

    def test_feedback_requires_live_run_revision_and_csrf(self):
        with tempfile.TemporaryDirectory() as td:
            app=create_app(Path(td));store=app.state.store
            with TestClient(app) as client:
                headers={'X-CSRF-Token':client.get('/api/v017/config').json()['csrf_token']}
                store.execute('INSERT INTO templates VALUES (?,?,?)',('test-template','Synthetic','now'))
                store.execute('INSERT INTO template_runs VALUES (?,?,?,?,?,?)',('test-run','test-template',1,'running',json.dumps({'schema':'teacher-student-023'}),'now'))
                url='/api/v017/template-runs/test-run/feedback';body={'expected_revision':0,'text':'Грантовый блок необязателен'}
                self.assertEqual(client.post(url,json=body).status_code,403)
                response=client.post(url,json=body,headers=headers)
                self.assertEqual(response.status_code,200,response.text)
                self.assertFalse(response.json()['already_applied'])
                self.assertEqual(client.post(url,json=body,headers=headers).status_code,409)
                self.assertEqual(store.one('SELECT revision FROM learning_feedback024 WHERE run_id=?',('test-run',))['revision'],1)


if __name__=='__main__':unittest.main()
