from pathlib import Path
import sys,unittest
from lxml import etree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ps2.word_math import display_equations,factor_vector,display,NS,M


class WordMathTests(unittest.TestCase):
    def test_all_original_display_equations_are_structural_math(self):
        equations=display_equations();self.assertEqual(len(equations),9)
        root=E.Element('root')
        for e in equations:root.append(display(e))
        for tag in ['sSub','sSup','sSubSup','f','rad','nary','limLow']:
            self.assertTrue(root.xpath('.//m:'+tag,namespaces=NS),tag)
        self.assertEqual(len(root.xpath('.//m:oMathPara',namespaces=NS)),9)

    def test_RMSE_uses_nested_sums_true_fraction_and_square_root(self):
        root=display(display_equations()[2])
        self.assertEqual(len(root.xpath('.//m:nary',namespaces=NS)),2)
        self.assertEqual(root.xpath('.//m:f/m:num//m:t/text()',namespaces=NS),['1'])
        self.assertEqual(root.xpath('.//m:f/m:den//m:t/text()',namespaces=NS),['T'])
        self.assertTrue(root.xpath('.//m:rad',namespaces=NS))

    def test_native_matrix_and_factor_order(self):
        root=display(factor_vector())
        cells=root.xpath('.//m:m/m:mr/m:e',namespaces=NS)
        self.assertEqual(len(cells),3)
        self.assertEqual([''.join(c.xpath('.//m:t/text()',namespaces=NS)) for c in cells],['Mkt−RFs','HMLs','SMBs'])

    def test_greek_scripts_and_projection_inverse(self):
        predictive=display(display_equations()[1]);self.assertEqual(predictive.xpath('.//m:sSubSup/m:e/m:r/m:t/text()',namespaces=NS),['β'])
        self.assertEqual(predictive.xpath('.//m:sSubSup/m:sub/m:r/m:t/text()',namespaces=NS),['i,t+1'])
        self.assertEqual(predictive.xpath('.//m:sSubSup/m:sup/m:r/m:t/text()',namespaces=NS),['real'])
        projection=display(display_equations()[7]);self.assertIn('−1',projection.xpath('.//m:sSup/m:sup/m:r/m:t/text()',namespaces=NS))
