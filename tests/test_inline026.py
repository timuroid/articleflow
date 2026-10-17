import unittest
from articleflow.inline026 import validate,overlay
from articleflow.docx_engine import DocumentError
from articleflow.rules023 import fit

class InlineTests(unittest.TestCase):
    def test_exact_ranges_and_overlay(self):
        blocks=[{'id':'b','text':'Текст x²'}]
        marks=validate({'inline':[{'paragraph':1,'start':6,'end':7,'role':'variable','quote':'x'}]},blocks,{'variable':'Variable name'})
        source={'b':[{'start':0,'end':8,'features':{'bold':False}}]}
        result=overlay(source,marks)
        self.assertEqual([(s['start'],s['end'],s['features']['inline_role']) for s in result['b']],[(0,6,'plain'),(6,7,'variable'),(7,8,'plain')])
        self.assertNotIn('inline_role',source['b'][0]['features'])
        for patch in [{'quote':'y'},{'end':99},{'start':True},{'role':'unknown'}]:
            row={**{'paragraph':1,'start':6,'end':7,'role':'variable','quote':'x'},**patch}
            with self.assertRaises(DocumentError):validate({'inline':[row]},blocks,{'variable':'Variable name'})
    def test_overlap_rejected(self):
        row={'paragraph':1,'start':0,'end':1,'role':'term','quote':'a'}
        with self.assertRaises(DocumentError):validate({'inline':[row,row]},[{'id':'b','text':'a'}],{'term':'Defined term'})
    def test_role_differences_do_not_merge(self):
        rows=[{'kind':'character','when':{'role':'body','bold':False,'italic':False,'vertical':'baseline','hyperlink':False,'inline_role':role},'set':{'style':style},'id':'b'} for role,style in [('plain','a'),('variable','b')]]
        rules,conflicts=fit(rows)
        self.assertEqual(conflicts,[])
        self.assertEqual({r['when']['inline_role'] for r in rules},{'plain','variable'})

    def test_exact_anchor_selects_occurrence_without_fuzzy_repair(self):
        blocks=[{'id':'b','text':'x then x'}]
        row={'paragraph':1,'quote':'x','occurrence':2,'role':'variable'}
        self.assertEqual(validate({'inline':[row]},blocks,{'variable':'Variable'})['b'],[{'start':7,'end':8,'role':'variable'}])
        for patch in [{'quote':'X'},{'occurrence':3},{'occurrence':True},{'quote':''}]:
            with self.assertRaises(DocumentError):validate({'inline':[{**row,**patch}]},blocks,{'variable':'Variable'})
