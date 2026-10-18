"""Offline checks for the one-call student-size diagnostic."""
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from articleflow.docx_engine import DocumentError


script=Path(__file__).resolve().parents[1]/'scripts/student_size036.py'
spec=importlib.util.spec_from_file_location('student_size036',script)
diagnostic=importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


def block(block_id,text):
    return {'id':block_id,'text':text,'atoms':[]}


class StudentSizeDiagnosticTests(unittest.TestCase):
    def test_compact_prompt_is_losslessly_decodable_and_smaller(self):
        rows=[{'n':n,'text':f'Article paragraph {n}',
               'atom_kinds':['text'] if n%2 else ['text','drawing'],
               'depth':0,'columns':0,'column':0,'row_band':'outside',
               'story_kind':'body','section_boundary':False,
               'previous_kind':'paragraph','next_kind':'paragraph',
               'previous_role':'unknown','next_role':'unknown',
               'language':'latin','role_transition_language':'other',
               'list_level':-1,'list_kind':'none','field_commands':''}
              for n in range(1,41)]
        payload={'roles':{'body':'Main document body'},
                 'inline_roles':{'term':'Technical term'},'paragraphs':rows}
        standard=[{'role':'system','content':'Assign roles and inline spans.'},
                  {'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]
        compact=diagnostic.compact_student_messages(standard)
        encoded=json.loads(compact[1]['content'])
        self.assertEqual(diagnostic.expand_compact_payload(encoded),payload)
        self.assertEqual(encoded['columns'][:3],['n','text','atom_kinds'])
        self.assertEqual(encoded['constants']['story_kind'],'body')
        self.assertIn('paragraph-columns-v1',compact[0]['content'])
        self.assertLess(len(json.dumps(compact).encode()),len(json.dumps(standard).encode()))
        with self.assertRaisesRegex(DocumentError,'COMPACT_ROWS_SCHEMA'):
            diagnostic.expand_compact_payload({**encoded,'paragraphs':[[1]]})

    def test_reasoning_effort_reaches_provider_and_diagnostic_records(self):
        repo=Path(__file__).resolve().parents[1]
        (repo/'artifacts').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=repo/'artifacts') as name:
            folder=Path(name);template=folder/'template';template.mkdir()
            roles={'title':'Document title'}
            inline_roles={'term':'Technical term'}
            teacher={'roles':roles,'groups':[{'start':1,'end':1,'role':'title'}],
                     'questions':[],'inline_roles':inline_roles,
                     'inline':[{'paragraph':1,'quote':'Title','occurrence':1,'role':'term'}]}
            reference={'blocks':[block('r1','Title')]}
            incoming={'blocks':[block('n1','Title')],'structure':{}}
            (folder/'reference.json').write_text(json.dumps(reference))
            (folder/'teacher.json').write_text(json.dumps(teacher))
            (folder/'neutralized.docx').write_bytes(b'fake document, extraction mocked')
            (template/'semantic.json').write_text(json.dumps({'roles':roles,'inline_roles':inline_roles}))
            (template/'rules.json').write_text('{}')
            (template/'resources.zip').write_bytes(b'fake resources')
            output=folder/'run'
            argv=['student_size036.py','--reference-content',str(folder/'reference.json'),
                  '--teacher-response',str(folder/'teacher.json'),'--template',str(template),
                  '--neutralized-docx',str(folder/'neutralized.docx'),
                  '--model','test/mandatory-reasoning','--key-file',str(folder/'key'),
                  '--ledger',str(folder/'ledger'),'--output',str(output),
                  '--reasoning-effort','low']
            returned={'groups':[{'start':1,'end':1,'role':'title'}],'inline':[]}
            standard=[{'role':'system','content':'Assign roles and inline spans.'},
                      {'role':'user','content':json.dumps({
                          'roles':roles,'inline_roles':inline_roles,
                          'paragraphs':[{'n':1,'text':'Title','atom_kinds':['text']}]})}]
            with patch.object(sys,'argv',argv),\
                 patch.object(diagnostic,'extract_input',return_value=incoming),\
                 patch.object(diagnostic,'student_messages',return_value=standard),\
                 patch.object(diagnostic,'call',return_value=(returned,{'status':'valid','api_attempts':1})) as provider,\
                 redirect_stdout(io.StringIO()) as printed:
                diagnostic.main()
                provider.assert_called_once()
                compact_output=folder/'compact-run'
                compact_argv=argv.copy()
                compact_argv[compact_argv.index('--output')+1]=str(compact_output)
                compact_argv.append('--compact')
                with patch.object(sys,'argv',compact_argv):diagnostic.main()
            self.assertEqual(provider.call_count,2)
            self.assertEqual(provider.call_args_list[0].args[0]['reasoning_effort'],'low')
            self.assertEqual(provider.call_args_list[1].args[0]['reasoning_effort'],'low')
            self.assertEqual(json.loads(provider.call_args_list[1].args[1][1]['content'])['schema'],
                             'paragraph-columns-v1')
            self.assertEqual(json.loads((output/'protocol.json').read_text())['reasoning_effort'],'low')
            summary=json.loads((output/'summary.json').read_text())
            self.assertEqual(summary['reasoning_effort'],'low')
            self.assertEqual(summary['prompt_format'],'standard')
            self.assertEqual(json.loads((compact_output/'summary.json').read_text())['prompt_format'],
                             'paragraph-columns-v1')
            self.assertEqual(summary['teacher_inline_obligations']['aligned_rows'],1)
            self.assertEqual(summary['teacher_inline_obligations']['defined_roles'],1)
            self.assertEqual(json.loads((output/'protocol.json').read_text())['teacher_inline_obligations'],
                             summary['teacher_inline_obligations'])
            scored=summary['semantic_diagnostics']
            self.assertTrue(scored['student_response_structurally_valid'])
            self.assertEqual(scored['inline']['teacher_exact_span_agreement'],
                             {'matched':0,'expected':1,'predicted':0,'precision':0.0,'recall':0.0})
            self.assertNotIn('whole_response_valid',scored)
            self.assertNotIn('Title',printed.getvalue())

    def test_removed_empty_layout_blocks_align_without_guessing_content(self):
        reference={'blocks':[block('r1','Title'),block('r2',''),block('r3','Body'),
                             block('r4',''),block('r5','Other')]}
        incoming={'blocks':[block('n1','Title'),block('n2','Body'),block('n3','Other')]}
        teacher={'roles':{'title':'Document title','spacer':'Empty layout paragraph',
                          'body':'Main document body'},
                 'groups':[{'start':1,'end':1,'role':'title'},
                           {'start':2,'end':2,'role':'spacer'},
                           {'start':3,'end':3,'role':'body'},
                           {'start':4,'end':4,'role':'spacer'},
                           {'start':5,'end':5,'role':'body'}],
                 'questions':[],'inline_roles':{},'inline':[]}
        expected,skipped=diagnostic.align_expected(reference,incoming,teacher)
        self.assertEqual(skipped,2)
        self.assertEqual(expected,{'n1':'title','n2':'body','n3':'body'})
        with self.assertRaisesRegex(DocumentError,'EVALUATION_CONTENT_ALIGNMENT'):
            diagnostic.align_expected(reference,{'blocks':[block('n1','Title'),block('n2','Wrong')]},teacher)

    def test_agreement_is_scored_even_if_inline_row_is_invalid(self):
        incoming={'blocks':[block('n1','Alpha beta'),block('n2','Body text')]}
        expected={'n1':'title','n2':'body'}
        package={'roles':{'title':'Document title','body':'Main document body'},
                 'inline_roles':{'term':'Technical term'}}
        response={'groups':[{'start':1,'end':1,'role':'title'},
                            {'start':2,'end':2,'role':'body'}],
                  'inline':[{'paragraph':1,'quote':'Alpha','occurrence':1,'role':'term'},
                            {'paragraph':1,'quote':'beta','occurrence':2,'role':'term'}]}
        result=diagnostic.score_response(response,incoming,expected,package)
        self.assertEqual(result['role_agreement_with_teacher'],
                         {'correct':2,'total':2,'accuracy':1.0})
        self.assertEqual(result['inline']['rows'],2)
        self.assertEqual(result['inline']['invalid_rows'],1)
        self.assertEqual(result['inline']['validation_code'],'INLINE_ANCHOR_NOT_FOUND')
        self.assertFalse(result['student_response_structurally_valid'])
        self.assertNotIn('Alpha beta',json.dumps(result))

    def test_exact_inline_agreement_uses_aligned_block_and_offsets(self):
        reference={'blocks':[block('r1',''),block('r2','Alpha beta')]}
        incoming={'blocks':[block('n1','Alpha beta')]}
        teacher={'roles':{'body':'Main document body','spacer':'Empty layout paragraph'},
                 'groups':[{'start':1,'end':1,'role':'spacer'},
                           {'start':2,'end':2,'role':'body'}],
                 'questions':[],'inline_roles':{'term':'Technical term'},
                 'inline':[{'paragraph':2,'quote':'Alpha','occurrence':1,'role':'term'}]}
        expected,skipped,expected_inline=diagnostic.align_expected(
            reference,incoming,teacher,include_inline=True)
        self.assertEqual(skipped,1)
        self.assertEqual(expected_inline,{'n1':[{'start':0,'end':5,'role':'term'}]})
        package={'roles':teacher['roles'],'inline_roles':teacher['inline_roles']}
        response={'groups':[{'start':1,'end':1,'role':'body'}],
                  'inline':[{'paragraph':1,'quote':'Alpha','occurrence':1,'role':'term'}]}
        score=diagnostic.score_response(response,incoming,expected,package,expected_inline)
        self.assertEqual(score['inline']['teacher_exact_span_agreement'],
                         {'matched':1,'expected':1,'predicted':1,'precision':1.0,'recall':1.0})


if __name__=='__main__':unittest.main()
