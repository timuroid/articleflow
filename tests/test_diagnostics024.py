import unittest
from articleflow.diagnostics024 import explain

class PropertyDiagnosticsTests(unittest.TestCase):
    def test_conflicting_font_attributes_are_explained_without_normalization(self):
        namespace='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        styles={'a':[f'<w:rPr xmlns:w="{namespace}"><w:rFonts w:eastAsia="KaiTi"/></w:rPr>'],
                'b':[f'<w:rPr xmlns:w="{namespace}"><w:rFonts w:eastAsia="SimSun"/></w:rPr>']}
        rows=[{'kind':'character','when':{'role':'heading'},'variants':2,'examples':[{'id':'x','set':{'style':'a'}},{'id':'y','set':{'style':'b'}}]}]
        report=explain(rows,{'styles':{'character':styles}})
        self.assertEqual(report[0]['differing_properties'],['0/rPr/0/rFonts/@eastAsia'])
        self.assertEqual(report[0]['equivalence'],'not_established')
        self.assertTrue(report[0]['diagnostic_complete'])
        self.assertNotIn('differing_properties',rows[0])
