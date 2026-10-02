# -*- coding: utf-8 -*-
"""验证导出的 docx：OMML 公式、表格、残留 LaTeX。"""
import re
import sys
import zipfile

path = sys.argv[1] if len(sys.argv) > 1 else "test_export.docx"
with zipfile.ZipFile(path) as z:
    xml = z.read("word/document.xml").decode("utf-8")

omath = len(re.findall(r"<m:oMath[ >]", xml))
opara = len(re.findall(r"<m:oMathPara[ >]", xml))
print("oMath:", omath, "| oMathPara(display):", opara, "| inline:", omath - opara)
print("tables:", xml.count("<w:tbl>"),
      "| rows:", xml.count("<w:tr>") or xml.count("<w:tr "),
      "| cells:", len(re.findall(r"<w:tc[ >]", xml)))

stripped = re.sub(r"<m:oMathPara[\s\S]*?</m:oMathPara>", "", xml)
stripped = re.sub(r"<m:oMath>[\s\S]*?</m:oMath>", "", stripped)
B = chr(92)
residual = re.findall(B + B + r"(?:mathcal|boldsymbol|tag|kappa|mathrm)", stripped)
print("residual raw LaTeX outside OMML:", len(residual), residual[:5])
print("raw 'aligned' outside OMML:", stripped.count("begin{aligned}"))
