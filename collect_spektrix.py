#!/usr/bin/env python3
"""Read Alnwick's official public Spektrix API. Write a review candidate only."""
import argparse
import hashlib
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from update import CollectionError, ROOT, write_candidate

BASE = 'https://system.spektrix.com/alnwickplayhouse/api/v3'
LONDON = ZoneInfo('Europe/London')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise CollectionError('API redirected; inspect source before retrying')

def fetch_json(url):
    req = urllib.request.Request(url, headers={'Accept':'application/json',
                                 'User-Agent':'CinemaNorthEastCollector/1.1'})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=25) as response:
        if response.headers.get_content_type() != 'application/json':
            raise CollectionError('API did not return JSON')
        raw = response.read(5_000_001)
        if len(raw)>5_000_000:
            raise CollectionError('API response exceeds size limit')
    return json.loads(raw.decode('utf-8')), hashlib.sha256(raw).hexdigest()

def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+[A-Za-z]+',value):
        raise CollectionError('Invalid public Spektrix identifier')
    return value

def records(value, label):
    if not isinstance(value,list) or not value or len(value)>10000 or not all(isinstance(x,dict) for x in value):
        raise CollectionError(f'Missing, empty or invalid {label} array')
    return value

def transform(events, instances, start, end):
    if not start < end or (end-start).days>31:
        raise CollectionError('Expected a date window of 1 to 31 days')
    lookup = {}
    for event in records(events,'events'):
        eid = identifier(event.get('id'))
        if (event.get('attribute_Type') != 'Film' or event.get('attribute_SendToWebsite') is not True):
            raise CollectionError('Event filters do not match expected Film/SendToWebsite attributes')
        title = event.get('name')
        if not isinstance(title,str) or not title.strip() or len(title)>200:
            raise CollectionError('Invalid film title')
        if eid in lookup and lookup[eid] != event:
            raise CollectionError('Conflicting event ID')
        lookup[eid] = event
    seen, rows, covered = {}, [], set()
    for instance in records(instances,'instances'):
        iid = identifier(instance.get('id'))
        if iid in seen:
            if seen[iid] != instance:
                raise CollectionError('Conflicting instance ID')
            continue
        seen[iid] = instance
        eid = identifier(instance.get('event',{}).get('id'))
        if eid not in lookup:
            raise CollectionError('Instance references an event missing from the event feed')
        covered.add(eid)
        if type(instance.get('cancelled')) is not bool or type(instance.get('isOnSale')) is not bool:
            raise CollectionError('Missing cancellation/on-sale flags')
        local = instance.get('start','')
        utc = instance.get('startUtc','')
        if not isinstance(local,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00',local):
            raise CollectionError('Invalid local performance start')
        wall = datetime.fromisoformat(local)
        if not isinstance(utc,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00(?:Z|\+00:00)?',utc):
            raise CollectionError('Missing UTC performance start')
        instant = datetime.fromisoformat(utc.replace('Z','+00:00'))
        # /instances serializes startUtc without Z; event-specific instances use Z.
        # Both are explicitly UTC fields, never host-local timestamps.
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        converted = instant.astimezone(LONDON)
        if converted.replace(tzinfo=None) != wall:
            raise CollectionError('Local and UTC performance times disagree')
        if not start <= wall.date() < end:
            raise CollectionError('API returned a performance outside the requested window')
        if instance['cancelled']:
            continue
        notes = instance.get('attribute_Info','')
        if not isinstance(notes,str):
            raise CollectionError('Invalid screen/access notes')
        rows.append(dict(cinema='Alnwick Playhouse',title=lookup[eid]['name'].strip(),
                         date=wall.date().isoformat(),time=wall.strftime('%H:%M'),notes=notes,
                         bookingUrl='https://www.alnwickplayhouse.co.uk/spektrix/ChooseSeats?EventInstanceId='+iid))
    if set(lookup) != covered:
        raise CollectionError('Events missing performances; possible inconsistent or partial response')
    if not rows:
        raise CollectionError('No non-cancelled screenings; manual review required')
    rows.sort(key=lambda r:(r['date'],r['time'],r['title'],r['bookingUrl']))
    return rows

def source_urls(start,end):
    dates={'instanceStart_from':start.isoformat(),'instanceStart_to':end.isoformat(),
           'attribute_Type':'Film','attribute_SendToWebsite':'1'}
    instances={'startFrom':start.isoformat(),'startTo':end.isoformat(),
               'eventattribute_Type':'Film','eventattribute_SendToWebsite':'1'}
    return [BASE+'/events?'+urlencode(dates),BASE+'/instances?'+urlencode(instances)]

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days',type=int,default=7)
    parser.add_argument('--events',type=Path,help='Saved API fixture; requires --instances and --start')
    parser.add_argument('--instances',type=Path)
    parser.add_argument('--start',type=date.fromisoformat,help='Fixture date only')
    parser.add_argument('--output',type=Path,default=ROOT/'work'/'alnwick-api-candidate.json')
    args=parser.parse_args(argv)
    if not 1<=args.days<=31: parser.error('--days must be 1 to 31')
    if any([args.events,args.instances,args.start]) and not all([args.events,args.instances,args.start]):
        parser.error('Offline mode requires --events, --instances and --start together')
    try:
        now=datetime.now(timezone.utc)
        start=args.start or now.astimezone(LONDON).date()
        end=start+timedelta(days=args.days)
        urls=source_urls(start,end)
        if args.events:
            bodies=[p.read_bytes() for p in (args.events,args.instances)]
            payloads=[json.loads(b) for b in bodies]
            hashes=[hashlib.sha256(b).hexdigest() for b in bodies]
        else:
            results=[fetch_json(url) for url in urls]
            payloads=[r[0] for r in results];hashes=[r[1] for r in results]
        rows=transform(*payloads,start,end)
        result=dict(schemaVersion=1,status='needs_review',source=BASE,
                    collectedAt=now.isoformat(),collectionMode='offline-fixture' if args.events else 'live-public-api',
                    sources=[dict(url=u,sha256=h) for u,h in zip(urls,hashes)],
                    updateMode='review-candidate-only',coverage={'from':str(start),'through':str(end-timedelta(days=1))},
                    screenings=rows)
        write_candidate(args.output,result)
        print(f'Collected {len(rows)} Alnwick screenings for review -> {args.output}')
        return 0
    except (ValueError,OSError,KeyError,TypeError,AttributeError) as exc:
        print(f'Collection failed; existing files unchanged: {exc}',file=sys.stderr)
        return 1

if __name__=='__main__':sys.exit(main())

