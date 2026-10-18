"""Exact unique anchors may repair tiny teacher offset mistakes, not ambiguity."""
import unittest

from articleflow.docx_engine import DocumentError
from articleflow.inline026 import align_unique_quotes, validate


class UniqueAnchorTests(unittest.TestCase):
    def test_unique_exact_quote_one_character_away(self):
        blocks=[{'id':'b-1','text':'name S value'}]
        response={'inline':[{'paragraph':1,'start':6,'end':7,'quote':'S','role':'symbol'}]}
        normalized,fixes=align_unique_quotes(response,blocks)
        self.assertEqual((normalized['inline'][0]['start'],normalized['inline'][0]['end']),(5,6))
        self.assertEqual(len(fixes),1)
        self.assertEqual(response['inline'][0]['start'],6)
        self.assertEqual(validate(normalized,blocks,{'symbol':'Scientific symbol'})['b-1'][0]['start'],5)

    def test_repeated_absent_and_distant_quotes_stay_invalid(self):
        cases=[('S S',1,2,'S'),('name Q value',5,6,'S'),('S far apart',7,8,'S')]
        for text,start,end,quote in cases:
            with self.subTest(text=text):
                blocks=[{'id':'b-1','text':text}]
                response={'inline':[{'paragraph':1,'start':start,'end':end,'quote':quote,'role':'symbol'}]}
                normalized,fixes=align_unique_quotes(response,blocks)
                self.assertEqual(normalized,response)
                self.assertEqual(fixes,[])
                with self.assertRaises(DocumentError):
                    validate(normalized,blocks,{'symbol':'Scientific symbol'})

    def test_preserves_invalid_role_for_strict_validator(self):
        blocks=[{'id':'b-1','text':'name S value'}]
        response={'inline':[{'paragraph':1,'start':6,'end':7,'quote':'S','role':'unknown'}]}
        normalized,fixes=align_unique_quotes(response,blocks)
        self.assertEqual(len(fixes),1)
        with self.assertRaisesRegex(DocumentError,'INLINE_RANGE'):
            validate(normalized,blocks,{'symbol':'Scientific symbol'})


if __name__=='__main__':
    unittest.main()
