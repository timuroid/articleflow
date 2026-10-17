import copy,unittest
from articleflow.evidence031 import prepare,restore

class EvidenceTests(unittest.TestCase):
    def test_aliases_preserve_xml_text_and_feedback_identity(self):
        style='paragraph-1234567890abcdef';xml='<w:pPr xmlns:w="urn:word"><w:ind w:firstLine="709"/></w:pPr>'
        source={'paragraphs':[{'text':style,'paragraph_style':style,'character_styles':[style],'style_spans':[{'start':0,'end':4,'style':style}]}],'catalogues':[{'paragraph':{style:[xml]}}]};old=copy.deepcopy(source)
        feedback={'property_variants':{style:{'size':'24'}},'examples':[{'text':style,'set':{'style':style}}]}
        result,fb=prepare(source,feedback);self.assertEqual(source,old)
        alias=next(iter(result['style_aliases']));self.assertEqual(result['style_aliases'][alias],style)
        self.assertEqual(result['catalogues'][0]['paragraph'][alias],[xml]);self.assertEqual(result['paragraphs'][0]['text'],style)
        self.assertEqual(result['paragraphs'][0]['style_spans'][0]['style'],alias)
        self.assertEqual(result['paragraphs'][0]['character_styles'],[alias])
        self.assertEqual(restore(result['paragraphs'],result['style_aliases']),source['paragraphs'])
        self.assertIn(alias,fb['property_variants']);self.assertEqual(fb['examples'][0]['text'],style);self.assertEqual(fb['examples'][0]['set']['style'],alias)
