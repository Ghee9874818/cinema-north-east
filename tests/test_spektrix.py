import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import collect_spektrix as api

FIX=Path(__file__).parent/'fixtures'
EVENTS=json.loads((FIX/'spektrix-events-2026-10-18.json').read_text())
INSTANCES=json.loads((FIX/'spektrix-instances-2026-10-18.json').read_text())
START=date(2026,10,18);END=date(2026,10,25)

class ApiTests(unittest.TestCase):
    def test_live_captured_week_matches_official_website(self):
        self.assertEqual(api.transform(EVENTS,INSTANCES,START,END),json.loads((FIX/'expected.json').read_text()))
    def test_invalid_data_fails(self):
        for key,value in [('start','2026-10-18T25:00:00'),('startUtc','2026-10-18T13:00:00Z'),
                          ('cancelled',None),('isOnSale',None),('id','invalid'),('event',{'id':'123A'}),
                          ('attribute_Info',12)]:
            data=copy.deepcopy(INSTANCES);data[0][key]=value
            with self.subTest(key=key),self.assertRaises((ValueError,TypeError)):
                api.transform(EVENTS,data,START,END)
    def test_live_theatre_and_hidden_events_rejected(self):
        for key,value in [('attribute_Type','Live'),('attribute_SendToWebsite',False)]:
            data=copy.deepcopy(EVENTS);data[0][key]=value
            with self.subTest(key=key),self.assertRaises(api.CollectionError):
                api.transform(data,INSTANCES,START,END)
    def test_empty_responses_rejected(self):
        for e,i in [([],INSTANCES),(EVENTS,[]),(EVENTS,{})]:
            with self.assertRaises(api.CollectionError):api.transform(e,i,START,END)
    def test_partial_join_rejected(self):
        data=[i for i in INSTANCES if i['event']['id']!=EVENTS[0]['id']]
        with self.assertRaises(api.CollectionError):api.transform(EVENTS,data,START,END)
    def test_cancelled_removed(self):
        data=copy.deepcopy(INSTANCES);data[0]['cancelled']=True
        self.assertEqual(len(api.transform(EVENTS,data,START,END)),18)
    def test_on_sale_is_not_availability(self):
        data=copy.deepcopy(INSTANCES);data[0]['isOnSale']=False
        self.assertEqual(len(api.transform(EVENTS,data,START,END)),19)
    def test_duplicate_and_conflict(self):
        self.assertEqual(len(api.transform(EVENTS,INSTANCES+[INSTANCES[0]],START,END)),19)
        altered=copy.deepcopy(INSTANCES[0]);altered['attribute_Info']='other screen'
        with self.assertRaises(api.CollectionError):api.transform(EVENTS,INSTANCES+[altered],START,END)
    def test_out_of_window_rejected(self):
        with self.assertRaises(api.CollectionError):api.transform(EVENTS,INSTANCES,date(2026,10,19),END)
    def test_london_dst(self):
        data=copy.deepcopy(INSTANCES[:2]);events=[e for e in EVENTS if e['id'] in {i['event']['id'] for i in data}]
        data[0].update(start='2026-10-24T13:00:00',startUtc='2026-10-24T12:00:00Z')
        data[1].update(start='2026-10-25T13:15:00',startUtc='2026-10-25T13:15:00Z')
        rows=api.transform(events,data,date(2026,10,24),date(2026,10,26))
        self.assertEqual([r['time'] for r in rows],['13:00','13:15'])
    def test_failures_preserve_previous_candidate(self):
        for effects in [[OSError('network unavailable')],[(EVENTS,'hash'),OSError('timeout')]]:
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'candidate.json';path.write_text('original')
                with patch('collect_spektrix.fetch_json',side_effect=effects):
                    self.assertEqual(api.main(['--output',str(path)]),1)
                self.assertEqual(path.read_text(),'original')
    def test_offline_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'candidate.json'
            result=api.main(['--events',str(FIX/'spektrix-events-2026-10-18.json'),
                            '--instances',str(FIX/'spektrix-instances-2026-10-18.json'),
                            '--start',str(START),'--output',str(path)])
            self.assertEqual(result,0)
            candidate=json.loads(path.read_text())
            self.assertEqual(candidate['status'],'needs_review')
            self.assertEqual(candidate['collectionMode'],'offline-fixture')
            self.assertNotIn('verifiedOn',candidate)

if __name__=='__main__':unittest.main()

