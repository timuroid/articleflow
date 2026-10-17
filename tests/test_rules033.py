import unittest
from articleflow.rules023 import fit

class InlineDependencyTests(unittest.TestCase):
    def test_uniform_style_does_not_require_semantic_annotation(self):
        rows=[{'kind':'character','when':{'role':'body','bold':False,'italic':False,'vertical':'baseline','hyperlink':False,'inline_role':r},'set':{'style':'same'},'id':r} for r in ['plain','term']]
        rules,conflicts=fit(rows)
        self.assertEqual(conflicts,[])
        self.assertEqual(len(rules),1)
        self.assertNotIn('inline_role',rules[0]['when'])
        self.assertEqual(rules[0]['support'],2)

    def test_real_inline_difference_cannot_be_erased(self):
        rows=[{'kind':'character','when':{'role':'body','bold':False,'italic':False,'vertical':'baseline','hyperlink':False,'inline_role':r},'set':{'style':r},'id':r} for r in ['plain','term']]
        rules,conflicts=fit(rows)
        self.assertEqual(conflicts,[])
        self.assertEqual({r['when']['inline_role'] for r in rules},{'plain','term'})

    def test_conflicting_training_evidence_blocks_broadening(self):
        base={'role':'body','bold':False,'italic':False,'vertical':'baseline','hyperlink':False}
        rows=[{'kind':'character','when':{**base,'inline_role':r},'set':{'style':s},'id':str(i)} for i,(r,s) in enumerate([('plain','normal'),('term','normal'),('term','different')])]
        rules,conflicts=fit(rows)
        self.assertEqual(len(conflicts),1)
        self.assertEqual(rules[0]['when']['inline_role'],'plain')
