import importlib.util
import unittest
from pathlib import Path

path=Path(__file__).resolve().parents[1]/'scripts/probe_style_equivalence024.py'
spec=importlib.util.spec_from_file_location('equivalence_probe024',path)
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

class EquivalenceProbeTests(unittest.TestCase):
    def test_only_matching_semantic_span_changes_and_original_plan_survives(self):
        content={'blocks':[{'id':'b1','text':'Абвг','atoms':[]}],
                 'structure':[{'id':'b1','kind':'paragraph'}]}
        plan={'blocks':[{'id':'b1','role':'body','paragraph_style':'p1','spans':[{'start':0,'end':4,'style':'c1'}]}]}
        semantics={'b1':[{'start':0,'end':2,'features':{'bold':False}},
                         {'start':2,'end':4,'features':{'bold':True}}]}
        result,changed=probe.substitute(plan,content,semantics,{'role':'body','bold':True},'character','c2')
        self.assertEqual(changed,1)
        self.assertEqual(result['blocks'][0]['spans'],[{'start':0,'end':2,'style':'c1'},{'start':2,'end':4,'style':'c2'}])
        self.assertEqual(plan['blocks'][0]['spans'],[{'start':0,'end':4,'style':'c1'}])
