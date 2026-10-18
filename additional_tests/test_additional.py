import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import collect_additional as c
FIX=Path(__file__).parent/'fixtures'
def data(name):return json.loads((FIX/(name+'.json')).read_text())
START=date(2026,10,18);END=date(2026,10,25)
class AdditionalTests(unittest.TestCase):
 def test_tyneside_raw_capture(self):
  rows=c.tyneside(data('tyneside-events'),data('tyneside-instances'),START,END)
  self.assertEqual(len(rows),104)
  self.assertTrue(all(r['cinema']=='Tyneside Cinema' for r in rows))
  self.assertTrue(any('Subtitled' in r['notes'] for r in rows))
 def test_tyneside_cancelled(self):
  instances=data('tyneside-instances');instances[0]['cancelled']=True
  self.assertEqual(len(c.tyneside(data('tyneside-events'),instances,START,END)),103)
 def test_tyneside_unknown_event(self):
  instances=data('tyneside-instances');instances[0]['event']['id']='123A'
  with self.assertRaises(c.CollectionError):c.tyneside(data('tyneside-events'),instances,START,END)
 def test_tyneside_timezone(self):
  instances=data('tyneside-instances');instances[0]['startUtc']=instances[0]['start']
  with self.assertRaises(c.CollectionError):c.tyneside(data('tyneside-events'),instances,START,END)
 def test_vue_capture(self):
  rows=c.vue([data('vue-sessions')],START,date(2026,10,19))
  self.assertEqual(len(rows),35)
  self.assertEqual(rows[0]['cinema'],'Vue Cramlington')
  self.assertTrue(all('/10085/' in r['bookingUrl'] for r in rows))
 def test_vue_wrong_venue(self):
  p=data('vue-sessions');p['result'][0]['showingInCinemas']=[]
  with self.assertRaises(c.CollectionError):c.vue([p],START,date(2026,10,19))
 def test_vue_booking_mismatch(self):
  p=data('vue-sessions');p['result'][0]['showingGroups'][0]['sessions'][0]['bookingUrl']='/book-tickets/summary/10000/wrong/123'
  with self.assertRaises(c.CollectionError):c.vue([p],START,date(2026,10,19))
 def test_vue_partial_week(self):
  with self.assertRaises(c.CollectionError):c.vue([data('vue-sessions')],START,END)
 def test_everyman_capture(self):
  rows=c.everyman(data('everyman-schedule'),data('everyman-movies'),START,END)
  self.assertTrue(len(rows)>50)
  self.assertTrue(all(r['date']<'2026-10-25' for r in rows))
  self.assertTrue(all(r['title'] for r in rows))
 def test_everyman_date_only_rejected(self):
  schedule=data('everyman-schedule')
  days=next(iter(schedule['X11KB']['schedule'].values()))
  day,shows=next(iter(days.items()));shows[0]['startsAt']=day
  with self.assertRaises(c.CollectionError):c.everyman(schedule,data('everyman-movies'),START,END)
 def test_everyman_conflicting_metadata_rejected(self):
  movies=data('everyman-movies');duplicate=copy.deepcopy(movies[0]);duplicate['title']='Conflicting title'
  with self.assertRaises(c.CollectionError):c.everyman(data('everyman-schedule'),movies+[duplicate],START,END)
 def test_everyman_identical_metadata_allowed(self):
  movies=data('everyman-movies');schedule=data('everyman-schedule')
  self.assertEqual(c.everyman(schedule,movies,START,END),c.everyman(schedule,movies+[copy.deepcopy(movies[0])],START,END))
 def test_timestamp_validation(self):
  for value in ('2026-10-18','20261018','2026-10-18T25:00','2026-10-18T1٠:00'):
   with self.subTest(value=value),self.assertRaises(c.CollectionError):c.local_start(value)
  self.assertEqual(c.local_start('2026-10-18T00:00:00').hour,0)
 def test_everyman_title_missing(self):
  with self.assertRaises(c.CollectionError):c.everyman(data('everyman-schedule'),data('everyman-movies')[1:],START,END)
 def test_everyman_wrong_venue(self):
  with self.assertRaises(c.CollectionError):c.everyman({'OTHER':{}},data('everyman-movies'),START,END)
 def test_failure_keeps_existing_candidate(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'candidate.json';p.write_text('previous')
   with patch('collect_additional.collect',side_effect=c.CollectionError('blocked')):
    self.assertEqual(c.main(['tyneside','--output',str(p)]),1)
   self.assertEqual(p.read_text(),'previous')
 def test_live_feed_output_refused(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'screenings.json';p.write_text('live')
   with self.assertRaises(c.CollectionError):c.write_candidate(p,{})
   self.assertEqual(p.read_text(),'live')
if __name__=='__main__':unittest.main()
