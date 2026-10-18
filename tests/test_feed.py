import copy,json,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
import build_feed as feed
NOW=datetime(2026,10,18,11,tzinfo=timezone.utc)
def row(cinema='Alnwick Playhouse',**fields):
    return dict(cinema=cinema,title='A film',date='2026-10-18',time='13:00',**fields)
def candidate():
    return dict(screenings=[row(notes='Screen 1',bookingUrl='https://www.alnwickplayhouse.co.uk/spektrix/ChooseSeats?EventInstanceId=1')],collectionMode='live-public-api',collectedAt=NOW.isoformat(),coverage={'from':'2026-10-18','through':'2026-10-24'})
class FeedTests(unittest.TestCase):
    def test_preserves_formats_screens_ids_and_metadata(self):
        rows=[row(id='1',notes='Screen 1',format='IMAX'),row(id='2',notes='Screen 2',format='2D')]
        out=feed.build({'screenings':rows,'warning':'check times'})
        self.assertEqual(out['screenings'],rows);self.assertEqual(out['warning'],'check times')
    def test_duplicate_exact_only(self):
        r=row();self.assertEqual(len(feed.build({'screenings':[r,r]})['screenings']),1)
    def test_conflicting_ids_rejected(self):
        with self.assertRaises(ValueError):feed.build({'screenings':[row(id='1'),row(id='1',notes='different')]})
    def test_strict_dates_times_links(self):
        for fields in ({'date':'2026-02-30'},{'time':'25:00'},{'time':'1٠:0٠'},{'time':'13:00:00'},{'bookingUrl':'https://evil.example/'},{'bookingUrl':'https://user@www.alnwickplayhouse.co.uk/'}):
            r=row();r.update(fields)
            with self.subTest(fields=fields),self.assertRaises(ValueError):feed.build({'screenings':[r]})
    def test_merge_preserves_other_venues_and_input(self):
        original={'screenings':[row('Tyneside Cinema'),row(title2='old')],'verifiedOn':'2026-10-17','venueStatus':{'Tyneside Cinema':{'status':'unavailable'}}}
        snapshot=copy.deepcopy(original);result=feed.merge_candidate(original,candidate(),NOW)
        self.assertEqual(original,snapshot)
        self.assertEqual(len(result['screenings']),2)
        self.assertEqual(result['venueStatus']['Tyneside Cinema'],original['venueStatus']['Tyneside Cinema'])
        self.assertNotIn('verifiedOn',result)
        self.assertEqual(result['venueStatus']['Alnwick Playhouse']['status'],'collected')
    def test_rejects_unpublishable_candidates(self):
        for change in ({'screenings':[]},{'collectionMode':'offline-fixture'},{'collectedAt':(NOW-timedelta(days=2)).isoformat()},{'collectedAt':(NOW+timedelta(minutes=1)).isoformat()},{'coverage':{'from':'2026-10-19','through':'2026-10-24'}}):
            c=candidate();c.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):feed.merge_candidate({'screenings':[]},c,NOW)
    def test_merge_rejects_multiple_venues(self):
        c=candidate();c['screenings'].append(row('Tyneside Cinema'))
        with self.assertRaises(ValueError):feed.merge_candidate({'screenings':[]},c,NOW)
    def test_failed_venue_keeps_rows_and_last_collection(self):
        existing=feed.merge_candidate({'screenings':[]},candidate(),NOW)
        result=feed.mark_unavailable(existing,'Alnwick Playhouse','HTTP unavailable',NOW)
        self.assertEqual(result['screenings'],existing['screenings'])
        self.assertEqual(result['venueStatus']['Alnwick Playhouse']['collectedAt'],NOW.isoformat())
        self.assertEqual(result['venueStatus']['Alnwick Playhouse']['status'],'unavailable')
    def test_no_collection_regression(self):
        existing=feed.merge_candidate({'screenings':[]},candidate(),NOW)
        c=candidate();c['collectedAt']=(NOW-timedelta(minutes=1)).isoformat()
        with self.assertRaises(ValueError):feed.merge_candidate(existing,c,NOW)
    def test_no_historical_coverage(self):
        c=candidate();c['screenings'][0]['date']='2026-10-17';c['coverage']={'from':'2026-10-17','through':'2026-10-17'}
        with self.assertRaises(ValueError):feed.merge_candidate({'screenings':[]},c,NOW)
    def test_atomic_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'feed.json';feed.atomic_write(path,{'screenings':[]});self.assertEqual(json.loads(path.read_text()),{'screenings':[]})
