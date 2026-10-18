import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import update

FIX = Path(__file__).parent/'fixtures'
HTML = (FIX/'alnwick-2026-10-18.html').read_text()
TODAY = date(2026,10,18)

class CollectorTests(unittest.TestCase):
    def test_official_dom_records(self):
        rows, week = update.parse_programme(HTML,TODAY)
        self.assertEqual(rows,json.loads((FIX/'expected.json').read_text()))
        self.assertEqual(len(rows),19)
        self.assertEqual(week, [f'2026-10-{d}' for d in range(18,25)])
    def test_blocked_response(self):
        with self.assertRaises(update.CollectionError):
            update.parse_programme('<html><body>Checking browser</body></html>',TODAY)
    def test_stale_page(self):
        with self.assertRaises(update.CollectionError):
            update.parse_programme(HTML,date(2026,10,19))
    def test_bad_or_partial_records(self):
        for before,after in [('13:00','25:00'),('2026-10-18','2026-02-30'),
            ('class="title"','class="changed"'),('movie-time-start','changed'),
            ('/spektrix/ChooseSeats?EventInstanceId=','https://example.com/?EventInstanceId='),
            ('EventInstanceId=','wrong='),('</body></html>',''),
            ('class="shows"','class="changed"')]:
            with self.subTest(before=before),self.assertRaises(update.CollectionError):
                update.parse_programme(HTML.replace(before,after,1),TODAY)
    def test_exact_duplicate_deduplicated(self):
        card=HTML[HTML.index('<li class="movie-card"'):HTML.index('</ul></body>')]
        rows,_=update.parse_programme(HTML.replace('</ul></body>',card+'</ul></body>'),TODAY)
        self.assertEqual(len(rows),19)
    def test_conflicting_duplicate_rejected(self):
        changed=HTML.replace('933177AMTKJNTTHCTLBLSLVLVSDPKBGMS','932977ADCBHNKMSQKNNJMJBMRKKDLKBRV')
        with self.assertRaises(update.CollectionError):
            update.parse_programme(changed,TODAY)
    def test_challenge_redirect_rejected(self):
        with self.assertRaises(update.CollectionError):
            update.OfficialRedirects().redirect_request(None,None,307,'',{},'https://www.alnwickplayhouse.co.uk/csq/')
    def test_live_output_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'screenings.json';p.write_text('original')
            with self.assertRaises(update.CollectionError): update.write_candidate(p,{})
            self.assertEqual(p.read_text(),'original')
    def test_failed_run_preserves_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'candidate.json';p.write_text('original')
            with patch('update.fetch',side_effect=update.CollectionError('blocked')):
                self.assertEqual(update.main(['--output',str(p)]),1)
            self.assertEqual(p.read_text(),'original')
    def test_offline_candidate_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'candidate.json'
            self.assertEqual(update.main(['--html',str(FIX/'alnwick-2026-10-18.html'),
                                         '--today','2026-10-18','--output',str(p)]),0)
            data=json.loads(p.read_text())
            self.assertEqual(data['status'],'needs_review')
            self.assertNotIn('verifiedOn',data)
            self.assertEqual(len(data['sourceSha256']),64)
    def test_london_dst_boundary(self):
        html=HTML
        for d in range(24,17,-1):html=html.replace(f'2026-10-{d}',f'2026-10-{d+7}')
        rows,_=update.parse_programme(html,date(2026,10,25))
        self.assertEqual(rows[0]['date'],'2026-10-25')
    def test_year_boundary(self):
        from datetime import timedelta
        html=HTML
        for i,d in enumerate(range(18,25)):
            html=html.replace(f'2026-10-{d}',(date(2026,12,29)+timedelta(days=i)).isoformat())
        _,week=update.parse_programme(html,date(2026,12,29))
        self.assertEqual(week[-1],'2027-01-04')

if __name__=='__main__':unittest.main()
