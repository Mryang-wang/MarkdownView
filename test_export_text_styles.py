"""Real Pandoc DOCX text formatting regression checks; no GUI or network."""
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from app.exporter import export_docx


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "m": "http://schemas.openxmlformats.org/officeDocument/2006/math"}
W = "{" + NS["w"] + "}"


class ExportTextStylesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="mdview-text-styles-test-")
        cls.addClassCleanup(cls.folder.cleanup)
        output = Path(cls.folder.name) / "styles.docx"
        markdown = '''# Text format export

Untouched paragraph.

<span style="font-family: 'Times New Roman'; font-size: 12.5pt; color: #AABBCC">Outer <u style="text-decoration-style: wavy"><mark style="background-color: #BFDBFE; color: #272724">**Combined**</mark></u> <span style="font-size: 24pt">Bigger</span> <span style="color: #123456">DifferentColor</span> OuterAgain</span>

<span style="font-family: '宋体'; font-size: 16pt; color: #b91c1c">中文局部字体</span>

<mark style="background-color: #7950f2; color: #ffffff"><span style="color: #166534; font-size: 18pt">ColorInsideMark</span></mark>

<span style="color: #166534"><mark style="background-color: #fecdd3; color: #272724">ColorOutsideMark</mark></span>

<span style="font-size: 30pt; color: #ff0000"><span style="font-size: 15px; color: var(--mdv-text-color)">ResetDefaults</span> KeepOuter</span>

<span style="font-size: 16px">PixelSize</span> <span style="color: #39a">ShortColor</span> <span style="font-size: 6pt">MinimumSize</span> <span style="font-size: 96pt">MaximumSize</span>

<u style="text-decoration-style: double"><span style="font-size: 10.5pt">OnlySizeUnderline</span></u> <mark style="background-color: #BBF7D0">LegacyHighlight</mark> <u>LegacyUnderline</u>

<span style="color: #ff0000"><mark style="background-color: #000000; color: #ffffff"><span style="color: var(--mdv-text-color)">AutoInsideHighlight</span></mark></span>

<span style="font-size: 13pt; color: #123456"><span style="font-size: nonsense; color: nope">InvalidInner</span></span>

| Header | Styled |
| --- | --- |
| Body | <span style="font-size: 14pt; color: #334455">TableCell</span> |

<span style="font-size: 17pt; color: #456789">[StyledLink](https://example.com)</span>

`<span style="font-size: 72pt; color: #ff0000">CodeLiteral</span>`

Math $x^2$.
'''
        export_docx(markdown, str(output))
        with zipfile.ZipFile(output) as archive:
            cls.document = ET.fromstring(archive.read("word/document.xml"))
            cls.styles = ET.fromstring(archive.read("word/styles.xml"))

    def run_for(self, text):
        matches = [run for run in self.document.findall(".//w:r", NS)
                   if text in "".join(run.itertext())]
        self.assertEqual(len(matches), 1, (text, ["".join(run.itertext()) for run in matches]))
        return matches[0]

    def property(self, text, tag, attribute="val"):
        element = self.run_for(text).find("w:rPr/w:" + tag, NS)
        self.assertIsNotNone(element, (text, tag, ET.tostring(self.run_for(text))))
        return element.get(W + attribute)

    def test_combined_font_size_color_bold_underline_highlight(self):
        for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
            self.assertEqual(self.property("Combined", "rFonts", attribute), "Times New Roman")
        self.assertEqual(self.property("Combined", "sz"), "25")
        self.assertEqual(self.property("Combined", "szCs"), "25")
        self.assertEqual(self.property("Combined", "color"), "AABBCC")
        self.assertEqual(self.property("Combined", "u"), "wave")
        self.assertEqual(self.property("Combined", "shd", "fill"), "BFDBFE")
        self.assertIsNotNone(self.run_for("Combined").find("w:rPr/w:b", NS))

    def test_nearest_explicit_property_wins_without_losing_other_properties(self):
        self.assertEqual(self.property("Bigger", "sz"), "48")
        self.assertEqual(self.property("Bigger", "color"), "AABBCC")
        self.assertEqual(self.property("DifferentColor", "color"), "123456")
        self.assertEqual(self.property("DifferentColor", "sz"), "25")
        self.assertEqual(self.property("OuterAgain", "color"), "AABBCC")
        self.assertEqual(self.property("InvalidInner", "color"), "123456")
        self.assertEqual(self.property("InvalidInner", "sz"), "26")

    def test_explicit_color_wins_over_highlight_contrast_in_both_orders(self):
        for text in ("ColorInsideMark", "ColorOutsideMark"):
            self.assertEqual(self.property(text, "color"), "166534")
        self.assertEqual(self.property("ColorInsideMark", "shd", "fill"), "7950F2")
        self.assertEqual(self.property("ColorOutsideMark", "shd", "fill"), "FECDD3")
        self.assertEqual(self.property("AutoInsideHighlight", "color"), "auto")
        self.assertEqual(self.property("AutoInsideHighlight", "shd", "fill"), "000000")

    def test_default_resets_pixels_half_points_and_size_limits(self):
        self.assertEqual(self.property("ResetDefaults", "color"), "auto")
        self.assertEqual(self.property("ResetDefaults", "sz"), "23")
        self.assertEqual(self.property("ResetDefaults", "szCs"), "23")
        self.assertEqual(self.property("KeepOuter", "sz"), "60")
        self.assertEqual(self.property("KeepOuter", "color"), "FF0000")
        self.assertEqual(self.property("PixelSize", "sz"), "24")
        self.assertEqual(self.property("MinimumSize", "sz"), "12")
        self.assertEqual(self.property("MaximumSize", "sz"), "192")
        self.assertEqual(self.property("ShortColor", "color"), "3399AA")

    def test_cjk_fonts_and_size_complex_script_properties(self):
        for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
            self.assertEqual(self.property("中文局部字体", "rFonts", attribute), "宋体")
        self.assertEqual(self.property("中文局部字体", "sz"), "32")
        self.assertEqual(self.property("中文局部字体", "szCs"), "32")
        self.assertEqual(self.property("中文局部字体", "color"), "B91C1C")

    def test_legacy_formats_tables_links_code_math_and_unformatted_text(self):
        self.assertEqual(self.property("OnlySizeUnderline", "u"), "double")
        self.assertEqual(self.property("OnlySizeUnderline", "sz"), "21")
        self.assertEqual(self.property("LegacyHighlight", "shd", "fill"), "BBF7D0")
        self.assertEqual(self.property("LegacyUnderline", "u"), "single")
        self.assertEqual(self.property("TableCell", "sz"), "28")
        self.assertEqual(self.property("TableCell", "color"), "334455")
        self.assertEqual(self.property("StyledLink", "sz"), "34")
        self.assertEqual(self.property("StyledLink", "color"), "456789")
        for text in ("Untouched paragraph.", "CodeLiteral"):
            run = self.run_for(text)
            self.assertIsNone(run.find("w:rPr/w:sz", NS))
            self.assertIsNone(run.find("w:rPr/w:color", NS))
        self.assertIn('<span style="font-size: 72pt; color: #ff0000">CodeLiteral</span>',
                      "".join(self.document.itertext()))
        self.assertIsNotNone(self.document.find(".//m:oMath", NS))
        self.assertIsNotNone(self.document.find(".//w:tbl", NS))

    def test_native_properties_are_present_in_character_styles_too(self):
        style_id = self.property("Combined", "rStyle")
        style = next(s for s in self.styles.findall("w:style", NS) if s.get(W + "styleId") == style_id)
        self.assertEqual(style.find("w:rPr/w:sz", NS).get(W + "val"), "25")
        self.assertEqual(style.find("w:rPr/w:color", NS).get(W + "val"), "AABBCC")
        for run in self.document.findall(".//w:r", NS):
            for tag in ("rFonts", "sz", "szCs", "color", "u", "shd"):
                self.assertLessEqual(len(run.findall("w:rPr/w:" + tag, NS)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
