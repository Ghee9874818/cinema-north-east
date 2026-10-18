#!/usr/bin/env python3
"""Validate and merge official venue candidates without losing other venues.

Usage: python build_feed.py candidate.json [output.json]
Only live-public-api / live-official-site candidates collected in the last day
can replace a venue. Failure leaves the existing output untouched.
"""
import copy
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

CINEMAS = {
    'Alnwick Playhouse': {'www.alnwickplayhouse.co.uk', 'alnwickplayhouse.co.uk'},
    'Vue Cramlington': {'www.myvue.com', 'myvue.com'},
    'ODEON Silverlink': {'www.odeon.co.uk', 'odeon.co.uk'},
    'ODEON Metrocentre': {'www.odeon.co.uk', 'odeon.co.uk'},
    'Everyman Newcastle': {'www.everymancinema.com', 'everymancinema.com', 'purchase.everymancinema.com'},
    'Cineworld Newcastle': {'www.cineworld.co.uk', 'cineworld.co.uk'},
    'Tyneside Cinema': {'tynesidecinema.co.uk', 'www.tynesidecinema.co.uk'},
}

def build(source):
    if not isinstance(source, dict) or not isinstance(source.get('screenings'), list):
        raise ValueError('Expected object with screenings array')
    if len(source['screenings']) > 10000:
        raise ValueError('Too many screenings')
    output, seen, identities = [], set(), {}
    for i, item in enumerate(source['screenings']):
        try:
            if not isinstance(item, dict): raise ValueError('Expected row object')
            row = copy.deepcopy(item)
            cinema, title, day, time = (row[k] for k in ('cinema','title','date','time'))
            if cinema not in CINEMAS or not isinstance(title,str) or not title.strip() or len(title)>200:
                raise ValueError('Invalid cinema/title')
            row['title'] = title.strip()
            if not isinstance(day,str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',day): raise ValueError('Invalid date')
            date.fromisoformat(day)
            if not isinstance(time,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',time): raise ValueError('Invalid time')
            link = row.get('bookingUrl','')
            if not isinstance(link,str): raise ValueError('Invalid booking URL')
            if link:
                u=urlsplit(link)
                if u.scheme!='https' or u.hostname not in CINEMAS[cinema] or u.username or u.password or u.port not in (None,443):
                    raise ValueError('Booking URL must be an official HTTPS venue link')
            for field in ('notes','format','screen','id','sourceId'):
                if field in row and (not isinstance(row[field],str) or len(row[field])>1000): raise ValueError('Invalid '+field)
            # Preserve separate screens/formats/performances at the same time.
            encoded=json.dumps(row,sort_keys=True,ensure_ascii=False)
            identity=row.get('id') or row.get('sourceId')
            if identity:
                key=(cinema,identity)
                if key in identities and identities[key]!=encoded: raise ValueError('Conflicting performance ID')
                identities[key]=encoded
            if encoded not in seen:
                seen.add(encoded);output.append(row)
        except (KeyError,TypeError,ValueError,AttributeError) as exc:
            raise ValueError(f'Invalid screening row {i+1}: {exc}') from exc
    output.sort(key=lambda r:(r['date'],r['time'],r['cinema'],r['title'],r.get('bookingUrl','')))
    result=copy.deepcopy(source)
    result.update(schemaVersion=1,screenings=output)
    return result

def merge_candidate(existing, candidate, now=None):
    now=now or datetime.now(timezone.utc)
    previous=build(existing)
    candidate=build(candidate)
    if candidate.get('collectionMode') not in ('live-public-api','live-official-site','live-public-source'):
        raise ValueError('Only freshly collected official data may be published')
    collected=datetime.fromisoformat(candidate.get('collectedAt','').replace('Z','+00:00'))
    if collected.tzinfo is None or not timedelta(0)<=now-collected<=timedelta(days=1):
        raise ValueError('Candidate collection timestamp is stale or in the future')
    rows=candidate['screenings']
    if not rows: raise ValueError('Empty candidate requires explicit completeness review')
    venues={r['cinema'] for r in rows}
    if len(venues)!=1: raise ValueError('A candidate must cover exactly one venue')
    venue=next(iter(venues))
    coverage=candidate.get('coverage',{})
    start,end=date.fromisoformat(coverage.get('from','')),date.fromisoformat(coverage.get('through',''))
    if end<start or (end-start).days>30: raise ValueError('Invalid coverage window')
    if not start<=collected.astimezone(ZoneInfo('Europe/London')).date()<=end:
        raise ValueError('Coverage must include collection date in the venue timezone')
    old_stamp=previous.get('venueStatus',{}).get(venue,{}).get('collectedAt')
    if old_stamp and datetime.fromisoformat(old_stamp.replace('Z','+00:00'))>collected:
        raise ValueError('Candidate is older than the last successful collection')
    if not all(start<=date.fromisoformat(r['date'])<=end for r in rows): raise ValueError('Row outside coverage')
    previous['screenings']=[r for r in previous['screenings'] if r['cinema']!=venue]+rows
    statuses=previous.setdefault('venueStatus',{})
    statuses[venue]={
        'status':'collected', 'collectedAt':candidate['collectedAt'],
        'coverage':copy.deepcopy(coverage), 'source':candidate.get('source',''),
        'sources':copy.deepcopy(candidate.get('sources',[])),
        'collectionMode':candidate['collectionMode'],
    }
    previous.pop('verifiedOn',None)
    previous['updateMode']='automatic official-source collection; see per-cinema status'
    previous['generatedAt']=now.isoformat()
    previous['warning']='Coverage varies by cinema. Times can change; confirm with the official cinema.'
    # A global source label from an older one-venue snapshot would be misleading.
    previous.pop('source',None)
    return build(previous)

def mark_unavailable(existing, venue, reason, now=None):
    """Record a failed attempt without deleting any last successful rows."""
    if venue not in CINEMAS: raise ValueError('Unknown venue')
    result=build(existing)
    status=result.setdefault('venueStatus',{}).setdefault(venue,{})
    status.update(status='unavailable',lastAttemptAt=(now or datetime.now(timezone.utc)).isoformat(),error=str(reason)[:300])
    return result

def atomic_write(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    name=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as tmp:
            name=tmp.name;json.dump(data,tmp,indent=2,ensure_ascii=False);tmp.write('\n')
        os.replace(name,path)
    finally:
        if name and os.path.exists(name): os.unlink(name)

if __name__=='__main__':
    if len(sys.argv)<2: sys.exit('Usage: python build_feed.py candidate.json [output.json]')
    out=Path(sys.argv[2] if len(sys.argv)>2 else 'screenings.json')
    existing=json.loads(out.read_text()) if out.exists() else {'schemaVersion':1,'screenings':[]}
    candidate=json.loads(Path(sys.argv[1]).read_text())
    merged=merge_candidate(existing,candidate)
    atomic_write(out,merged)
    print(f"Validated and merged {len(candidate['screenings'])} screenings -> {out}")
