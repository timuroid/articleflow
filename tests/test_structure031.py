import json,tempfile,unittest
from pathlib import Path
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from articleflow.agent023 import extract_input,build_package
from articleflow.rules023 import semantic_spans,features

class ListStructureTests(unittest.TestCase):
    def test_alternating_list_levels_do_not_collapse_into_same_role_context(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source.docx';d=Document()
            for i in range(8):
                p=d.add_paragraph('Synthetic list item '+str(i));pp=p._p.get_or_add_pPr();num=OxmlElement('w:numPr')
                for name,value in [('ilvl',str(i%2)),('numId','1')]:
                    node=OxmlElement('w:'+name);node.set(qn('w:val'),value);num.append(node)
                pp.append(num)
            d.save(source);content=extract_input(source,root/'extracted');labels={b['id']:'item' for b in content['blocks']}
            geometry=features(content,labels)['paragraph'];self.assertEqual([v['list_level'] for v in geometry.values()],[0,1]*4)
            package,conflicts=build_package([{'content':content,'extracted':root/'extracted','semantics':semantic_spans(source)}],[labels],{'item':'List item'},root/'template')
            self.assertEqual(conflicts,[])
