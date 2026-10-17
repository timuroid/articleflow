import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
from benchmark_long025 import generate


class LongFixtureTests(unittest.TestCase):
    def test_planted_ambiguity_and_labels_survive_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.docx';meta=generate(path,'ambiguous',17)
            document=Document(path)
            paragraphs=list(document._element.body.iter(qn('w:p')))
            self.assertEqual(len(paragraphs),len(meta['labels']))
            self.assertGreater(len(paragraphs),200)
            indents=set();colors=set();vertical=set()
            for i,p in enumerate(paragraphs,1):
                if meta['labels'][f'b-{i:06d}']=='body':
                    indents.add(p.find(qn('w:pPr')).find(qn('w:ind')).get(qn('w:firstLine')))
                colors.update(n.get(qn('w:val')) for n in p.iter(qn('w:color')))
                vertical.update(n.get(qn('w:val')) for n in p.iter(qn('w:vertAlign')))
            self.assertEqual(indents,{'709','720'})
            self.assertIn('204080',colors)
            self.assertTrue({'superscript','subscript'}<=vertical)
            self.assertTrue(document._element.body.xpath('.//w:tbl//w:tbl'))
