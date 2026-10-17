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


class ConflictEvidenceTests(unittest.TestCase):
    def test_document_identity_ranges_and_no_invented_locations(self):
        from articleflow.diagnostics024 import evidence
        from articleflow.rules023 import fit
        rows=[{'kind':'paragraph','when':{'role':'body'},'set':{'style':style},
               'id':'same','document':document,'range':[1,3]}
              for document,style in [(1,'a'),(2,'b')]]
        fitted,conflicts=fit(rows)
        self.assertEqual(fitted,[])
        samples=[{'content':{'blocks':[{'id':'same','text':text}]}} for text in ['abcd','WXYZ']]
        result=evidence(conflicts,samples)
        locations=result['groups'][0]['locations']
        self.assertEqual([x['document'] for x in locations],[1,2])
        self.assertEqual([x['excerpt'] for x in locations],['bc','XY'])
        self.assertTrue(result['groups'][0]['location_complete'])
        self.assertNotIn('page',locations[0])
        limited=evidence(conflicts,samples,limit=0)
        self.assertTrue(limited['truncated'])
        self.assertEqual(limited['groups'],[])
