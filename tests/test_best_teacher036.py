"""A repair must not discard a better verified training candidate."""
import json
import tempfile
import unittest
from pathlib import Path

from docx import Document

from articleflow.agent023 import extract_input
from articleflow.managed034 import collect, pick_replay_work


class BestTeacherReplayTests(unittest.TestCase):
    def test_selects_lowest_conflict_training_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            learning=Path(td)/'learning'
            for number,count in enumerate((44,40,41,44),1):
                work=learning/f'iteration-{number}'
                (work/'teacher').mkdir(parents=True)
                (work/'teacher/validated.json').write_text('{}')
                (work/'training-conflicts.json').write_text(json.dumps([{}]*count))
            self.assertEqual(pick_replay_work(Path(td),4).name,'iteration-2')

    def test_prefers_last_real_student_response_over_training_only(self):
        with tempfile.TemporaryDirectory() as td:
            learning=Path(td)/'learning'
            for number,count in enumerate((30,31,20),1):
                work=learning/f'iteration-{number}'
                (work/'teacher').mkdir(parents=True)
                (work/'teacher/validated.json').write_text('{}')
                (work/'training-conflicts.json').write_text(json.dumps([{}]*count))
            (learning/'iteration-2/application-1/student').mkdir(parents=True)
            (learning/'iteration-2/application-1/student/validated.json').write_text('{}')
            self.assertEqual(pick_replay_work(Path(td),3).name,'iteration-2')

    def test_missing_teacher_response_has_no_replay(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(pick_replay_work(Path(td),3))

    def test_repaired_student_is_replayed_from_effective_answer(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=root/'reference.docx'
            doc=Document();doc.add_paragraph('alpha beta');doc.save(source)
            run=root/'run';work=run/'learning/iteration-1'
            extract_input(source,run/'learning/reference-1/extracted')
            teacher={'roles':{'body':'Body paragraph'},
                     'groups':[{'start':1,'end':1,'role':'body'}],
                     'questions':[], 'inline_roles':{'term':'Technical term'},
                     'inline':[{'paragraph':1,'quote':'alpha','occurrence':1,'role':'term'}]}
            (work/'teacher').mkdir(parents=True)
            (work/'teacher/validated.json').write_text(json.dumps(teacher))
            application=work/'application-1'
            application.mkdir(parents=True)
            effective={'groups':[{'start':1,'end':1,'role':'body'}],
                       'inline':[{'paragraph':1,'quote':'alpha','occurrence':1,'role':'term'}]}
            (application/'effective-student.json').write_text(json.dumps(effective))
            # The invalid first pass has no provider-validated file. The
            # effective response is the only replayable student evidence.
            self.assertFalse((application/'student/validated.json').exists())
            self.assertEqual(pick_replay_work(run,1),work)
            cases=collect([source],run,{'iterations':[{}]})
            self.assertEqual([case['id'] for case in cases],['document-1-normal'])
            self.assertEqual(cases[0]['response'],effective)
            self.assertEqual(cases[0]['teacher_iteration'],1)


if __name__=='__main__':
    unittest.main()
