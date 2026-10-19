from pathlib import Path
import sys,unittest
from lxml import etree as E
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).resolve().parents[1]/'src')]
from ps2_build_editable_docx import x,paragraph,table_native,W,M,A,source_metadata,ROOT


class EditableDOCXTests(unittest.TestCase):
    def test_DrawingML_attributes_unqualified_Word_attributes_qualified(self):
        extent=x('a','ext',cx=100,cy=200)
        self.assertEqual(extent.get('cx'),'100');self.assertIsNone(extent.get('{'+A+'}cx'))
        page=x('w','pgSz',w=12240,h=15840)
        self.assertEqual(page.get('{'+W+'}w'),'12240')

    def test_inline_superscript_is_editable_math(self):
        p=paragraph('Slope b<sup>Welch</sup> and 10<sup>−15</sup>.')
        self.assertEqual(len(p.findall('.//{'+M+'}sSup')),2)
        self.assertFalse(any('<sup>' in t for t in p.itertext()))

    def test_complete_shrinkage_expression_is_one_native_equation(self):
        p=paragraph('Rule b*=1+k(b<sup>Welch</sup>−1), 0≤k≤1.')
        self.assertEqual(len(p.findall('.//{'+M+'}oMath')),1)
        text=''.join(p.find('.//{'+M+'}oMath').itertext())
        self.assertIn('k',text);self.assertIn('0 ≤ k ≤ 1',text)

    def test_multiple_panels_share_one_editable_table_with_exact_cells(self):
        data=[[['Name','Value','N'],['A','0.125','10']],[['Rule','Statistic'],['Missing','Not estimated']]]
        meta={'title':'Table 3. Synthetic','items':[{'kind':'table'},{'kind':'heading','text':'Panel B'},{'kind':'table'},{'kind':'text','text':'Note'}]}
        table,notes,expected=table_native(data,meta)
        rows=table.findall('{'+W+'}tr');self.assertEqual(len(rows),5)
        self.assertEqual([''.join(c.itertext()) for c in rows[-1].findall('{'+W+'}tc')],['Missing','Not estimated'])
        self.assertEqual(len(table.findall('.//{'+W+'}gridSpan')),3)
        self.assertEqual(notes,[{'kind':'text','text':'Note'}])

    def test_original_caption_and_note_sources_are_available(self):
        tables,figures=source_metadata(ROOT/'scripts/ps2_report_v2.py')
        self.assertEqual(len(tables),7);self.assertEqual(len(figures),4)
        self.assertTrue(any('Not estimated' in i.get('text','') for i in tables[5]['items']))
