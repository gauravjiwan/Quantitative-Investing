import io,sys,unittest
from pathlib import Path
from reportlab.pdfgen import canvas
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ps2.submission_pdf import read_classic,rewrite_references,combine,stream_bytes


def sample(pages):
    target=io.BytesIO();c=canvas.Canvas(target,pageCompression=0)
    for i in range(pages):c.drawString(50,700,f'Page {i+1}: reference-like text 9 0 R');c.showPage()
    c.save();return target.getvalue()


class SubmissionPDFTests(unittest.TestCase):
    def test_page_assembly_preserves_exact_exhibit_streams(self):
        main,baseline=sample(4),sample(15);assembled,record=combine(main,baseline)
        a,b=read_classic(assembled),read_classic(baseline)
        self.assertEqual(len(a.pages),15);self.assertEqual(record['original_exhibit_content_streams_preserved'],11)
        import re
        for old,new in zip(b.pages[4:],a.pages[4:]):
            x=int(re.search(rb'/Contents (\d+) 0 R',b.objects[old])[1]);y=int(re.search(rb'/Contents (\d+) 0 R',a.objects[new])[1])
            self.assertEqual(stream_bytes(b.objects[x]),stream_bytes(a.objects[y]))

    def test_literals_hex_and_comments_are_never_rewritten(self):
        data=b'<< /A 9 0 R /Title (text 9 0 R (nested \\) 9 0 R)) /Hex <39303052> % 9 0 R\n /B [9 0 R] >>'
        expected=data.replace(b'/A 9 0 R',b'/A 19 0 R').replace(b'/B [9 0 R]',b'/B [19 0 R]')
        self.assertEqual(rewrite_references(data,{9:19}),expected)

    def test_bad_input_and_wrong_page_counts_rejected(self):
        with self.assertRaises(ValueError):read_classic(b'Not a PDF')
        with self.assertRaises(ValueError):combine(sample(3),sample(15))
        with self.assertRaises(ValueError):read_classic(sample(4)[:-10])
