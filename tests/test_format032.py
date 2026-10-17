import tempfile,unittest
from pathlib import Path
from docx import Document
from docx.shared import RGBColor
from articleflow.format032 import audit
from articleflow.docx_engine import load_package,write_package,parse_xml,xml_bytes,NS

class PropertyAuditTests(unittest.TestCase):
    def test_font_color_and_empty_boolean_properties_are_not_pixel_aliases(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=root/'a.docx';b=root/'b.docx';d=Document();r=d.add_paragraph().add_run('Same text');r.bold=True;d.save(a)
            d.save(b);self.assertTrue(audit(a,b)['property_exact'])
            r.bold=None;r.italic=True;d.save(b);self.assertFalse(audit(a,b)['property_exact'])
            r.italic=None;r.bold=True;r.font.color.rgb=RGBColor(1,2,3);d.save(b);self.assertFalse(audit(a,b)['property_exact'])
            r.font.color.rgb=None;r.font.name='Distinct font';d.save(b);self.assertFalse(audit(a,b)['property_exact'])

    def test_style_resources_are_checked_even_when_not_rendered_in_this_sample(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=root/'a.docx';b=root/'b.docx';d=Document();d.add_paragraph('Same text');d.save(a)
            parts=load_package(a);parts['word/settings.xml']+=b'\n';write_package(b,parts)
            self.assertFalse(audit(a,b)['resources_exact'])
