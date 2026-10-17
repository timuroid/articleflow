import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from docx import Document
from fastapi.testclient import TestClient
from articleflow.web017 import create_app
from articleflow.docx_engine import digest

class AdaptiveWebTests(unittest.TestCase):
    def test_agentic_intake_and_certification_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source.docx';d=Document();d.add_paragraph('Synthetic');d.save(source)
            certificate={'instance_replay':True,'stress_passed':False}
            def run(paths,folder,*a,**kw):
                package=folder/'learning/iteration-1/template';package.mkdir(parents=True)
                for name,value in [('rules.json','{}'),('semantic.json','{"roles":{"body":"Body"}}'),('resources.zip','fixture')]: (package/name).write_text(value)
                return {'schema':'teacher-student-023','contract':'adaptive-template-028','status':'reference_verified','template':str(package),'iterations':[{'number':1,'applications':[]}],'source_hashes':[digest(p.read_bytes()) for p in paths],'negative_controls':[{'detected':True}],'certification':dict(certificate),'questions':[],'student_model':'fixture','held_out_transfer':'not_measured'}
            with patch('articleflow.web017.model_config',return_value={'model':'fixture'}),patch('articleflow.agent028.run',side_effect=run),patch('articleflow.templateagent022.run') as legacy:
                app=create_app(root/'web')
                with TestClient(app) as c:
                    h={'X-CSRF-Token':c.get('/api/v017/config').json()['csrf_token']}
                    r=c.post('/api/v017/templates',data={'name':'Synthetic','agentic':'true'},files={'files':('s.docx',source.read_bytes())},headers=h)
                    self.assertEqual(r.status_code,200,r.text);tid=r.json()['id'];legacy.assert_not_called()
                    self.assertTrue(c.get(f'/api/v017/templates/{tid}').json()['spec']['pending_agent'])
                    for cert,expected in [({'instance_replay':True,'stress_passed':False},False),({'stress_passed':True},False),({'instance_replay':True,'stress_passed':True},True)]:
                        certificate.clear();certificate.update(cert)
                        r=c.post(f'/api/v017/templates/{tid}/learn',json={'consent_external':True},headers=h)
                        self.assertEqual(r.status_code,200,r.text)
                        self.assertEqual(c.get(f'/api/v017/templates/{tid}').json()['approved'],expected)
                    self.assertEqual(c.get('/templates').status_code,200)
                    r=c.post(f'/api/v017/templates/{tid}/learn',json={'consent_external':True,'validation_job_id':'foreign-or-missing'},headers=h)
                    self.assertEqual(r.status_code,400)
