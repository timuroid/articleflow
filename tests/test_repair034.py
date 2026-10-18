import io,json,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from articleflow.docx_engine import DocumentError
from articleflow.sandbox034 import propose,unpack,snapshot,file_hashes
from articleflow.managed034 import load_engine

class RepairIsolationTests(unittest.TestCase):
    def test_patch_cannot_edit_evaluator_or_escape_directory(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)/'base';snapshot(base);before=file_hashes(base)
            for path in ['format032.py','../rules023.py','worker034.py','agent023.py']:
                with self.assertRaisesRegex(DocumentError,'PATCH_FILE_FORBIDDEN'):
                    propose(base,Path(td)/'out',{'diagnosis':'test','edits':[{'file':path,'old':'x','new':'y'}]})
            self.assertEqual(file_hashes(base),before)

    def test_invalid_patch_never_mutates_base(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)/'base';snapshot(base);before=file_hashes(base)
            for old,new,code in [('not present','replacement','PATCH_ANCHOR_NOT_UNIQUE'),('def fit(examples):','def :','PATCH_SYNTAX')]:
                with self.assertRaisesRegex(DocumentError,code):propose(base,Path(td)/'out',{'diagnosis':'test','edits':[{'file':'rules023.py','old':old,'new':new}]})
            self.assertEqual(file_hashes(base),before)

    def test_worker_archive_cannot_write_symlink_or_parent(self):
        for name,link in [('../outside',False),('/absolute',False),('leak',True)]:
            data=io.BytesIO()
            with tarfile.open(fileobj=data,mode='w') as t:
                item=tarfile.TarInfo(name)
                if link:item.type=tarfile.SYMTYPE;item.linkname='/tmp/private'
                t.addfile(item)
            with tempfile.TemporaryDirectory() as td:
                with self.assertRaisesRegex(DocumentError,'WORKER_UNSAFE_ARCHIVE'):unpack(data.getvalue(),Path(td)/'out')

    def test_runtime_rejects_changed_engine_before_docker(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);snapshot(root/'engine');profile={'path':'engine','hashes':file_hashes(root/'engine'),'image':'sha256:test'}
            with (root/'engine/order024.py').open('a') as f:f.write('\n# changed\n')
            with patch('articleflow.managed034.Engine') as docker:
                with self.assertRaisesRegex(DocumentError,'ENGINE_PROFILE_CHANGED'):load_engine(root,profile)
                docker.assert_not_called()

    def test_sealed_probe_details_never_reach_patch_model(self):
        from articleflow.repair034 import messages
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);(base/'order024.py').write_text('pass\n')
            prompt=messages(base,[{'id':'development','passed':False}],{'code':'SEALED_REGRESSION'},['order024.py'])
            self.assertNotIn('golden.docx',json.dumps(prompt));self.assertIn('SEALED_REGRESSION',json.dumps(prompt))

    def test_sealed_failure_is_redacted_in_real_repair_loop_feedback(self):
        from articleflow.repair034 import run
        prompts=[]
        class FakeEngine:
            def __init__(self,source,image):self.hashes=file_hashes(source);self.image='sha256:fixture'
        def evaluate(engine,case,folder):
            baseline='baseline' in folder.parts
            return {'id':case['id'],'split':case['split'],'passed':not baseline and case['split']=='development','private_detail':case['private']}
        def caller(config,messages,directory,**kwargs):
            prompts.append(json.dumps(messages))
            return {'diagnosis':'fixture','edits':[{'file':'rules023.py','old':'def fit(examples):','new':'def fit(examples):\n    # probe'}]}, {'api_attempts':0}
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);snapshot(root/'source')
            cases=[{'id':'development','split':'development','private':'allowed'}, {'id':'sealed_only_sentinel','split':'sealed','private':'hidden_expected_text_sentinel'}]
            with patch('articleflow.repair034.Engine',FakeEngine),patch('articleflow.repair034.evaluate',side_effect=evaluate):
                result=run(root/'source',cases,root/'run',{},caller=caller)
            self.assertEqual(result['status'],'needs_review');self.assertEqual(len(prompts),2)
            for prompt in prompts:
                self.assertNotIn('sealed_only_sentinel',prompt);self.assertNotIn('hidden_expected_text_sentinel',prompt)

    def test_partial_progress_requires_no_case_regression(self):
        from articleflow.repair034 import improves
        before=[{'id':'a','split':'development','conflicts':33},{'id':'b','split':'development','passed':True}]
        self.assertTrue(improves(before,[{'id':'a','conflicts':25},{'id':'b','passed':True}]))
        self.assertFalse(improves(before,[{'id':'a','conflicts':25},{'id':'b','conflicts':1}]))
        self.assertFalse(improves(before,[{'id':'a','conflicts':33},{'id':'b','passed':True}]))
        self.assertFalse(improves(before,[{'id':'a','conflicts':1}]))

    def test_accepted_patch_requires_fresh_template_recheck(self):
        from articleflow.managed034 import run
        for fresh_status in ['needs_review','reference_verified']:
            with self.subTest(fresh_status=fresh_status),tempfile.TemporaryDirectory() as td:
                root=Path(td);folder=root/'run';calls=[]
                def learn(references,directory,*args,**kwargs):
                    calls.append(directory);directory.mkdir(parents=True)
                    return {'schema':'teacher-student-023','status':'needs_review' if len(calls)==1 else fresh_status,'iterations':[]}
                def repair(base,cases,directory,*args,**kwargs):
                    directory.mkdir();engine=directory/'engine';engine.mkdir();profile=directory/'profile.json'
                    profile.write_text(json.dumps({'hashes':{},'image':'sha256:fixture'}))
                    return {'status':'accepted','engine':str(engine),'profile':str(profile)}
                with patch('articleflow.agent028.run',side_effect=learn),patch('articleflow.managed034.collect',return_value=[{'id':'dev','split':'development'}]),patch('articleflow.probes034.create',return_value=[{'id':'guard','split':'sealed'}]),patch('articleflow.repair034.run',side_effect=repair),patch('articleflow.managed034.load_engine',return_value=None):
                    result=run([],folder,{}, {},repair_image='fixture')
                self.assertEqual(len(calls),2);self.assertEqual(result['status'],fresh_status)
                self.assertEqual(result['engine_learning_root'],'engine-replay/learning')
                self.assertTrue((folder/'before-engine-repair.json').exists())

    def test_import_failure_generates_instance_probe_without_student_response(self):
        from articleflow.managed034 import collect
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'reference.docx'
            cases=collect([source],root/'run',{'iterations':[]})
            self.assertEqual(len(cases),1);self.assertEqual(cases[0]['kind'],'instance')
            self.assertNotIn('response',cases[0]);self.assertEqual(cases[0]['golden'],source)
