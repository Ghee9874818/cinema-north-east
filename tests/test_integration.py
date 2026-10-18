"""Recovered live captures are fixtures only, never a scheduled publication input."""
import json,unittest
from datetime import datetime,timezone
from pathlib import Path
import build_feed as feed
FIX=Path(__file__).parent/'fixtures'/'recovered-candidates'
NOW=datetime(2026,10,18,13,0,tzinfo=timezone.utc)
class IntegrationTests(unittest.TestCase):
 def test_recovered_captures_merge_without_collisions(self):
  result={'schemaVersion':1,'screenings':[]}
  for venue,count in [('vue',231),('tyneside',104),('everyman',101)]:
   candidate=json.loads((FIX/(venue+'-candidate.json')).read_text())
   self.assertEqual(len(candidate['screenings']),count)
   result=feed.merge_candidate(result,candidate,NOW)
   self.assertEqual(result['venueStatus'][candidate['cinema']]['collectedAt'],candidate['collectedAt'])
  self.assertEqual(len(result['screenings']),436)
  self.assertEqual(len(result['venueStatus']),3)
  self.assertTrue(all('notes' in row for row in result['screenings']))
  self.assertTrue(any(row['bookingUrl'].startswith('https://purchase.everymancinema.com/') for row in result['screenings']))
 def test_everyman_booking_host_cannot_leak_to_other_venues(self):
  row=json.loads((FIX/'everyman-candidate.json').read_text())['screenings'][0]
  row['cinema']='Vue Cramlington'
  with self.assertRaises(ValueError):feed.build({'screenings':[row]})
 def test_recovered_candidate_still_obeys_staleness(self):
  candidate=json.loads((FIX/'vue-candidate.json').read_text())
  with self.assertRaises(ValueError):feed.merge_candidate({'screenings':[]},candidate,datetime(2026,10,20,tzinfo=timezone.utc))
