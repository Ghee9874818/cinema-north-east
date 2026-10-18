#!/usr/bin/env python3
"""Experimental additional cinema collectors. Candidate files only; no publishing."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo
from update import CollectionError, ROOT, write_candidate

LONDON=ZoneInfo('Europe/London')
VENUES={'tyneside':'Tyneside Cinema','vue':'Vue Cramlington','everyman':'Everyman Newcastle'}

class PublicClient:
    """Use curl, which was verified against the public website endpoints.
    Anonymous Vue visitor cookies exist only in this run's temporary directory.
    """
    def __init__(self,cookie_file):
        self.cookie_file=str(cookie_file)
        self.sources=[]
    def get(self,url,guest=False,post=False):
        cmd=['curl','--fail','--silent','--show-error','--max-time','30',
             '--max-filesize','10000000','--header','Accept: application/json']
        if guest:cmd+=['--cookie',self.cookie_file,'--cookie-jar',self.cookie_file]
        if post:cmd+=['--request','POST']
        cmd.append(url)
        result=subprocess.run(cmd,capture_output=True,timeout=35)
        if result.returncode:
            # Do not include response cookies or anonymous token bodies in logs.
            raise CollectionError(f'Public source request failed (curl {result.returncode}): {urlsplit(url).netloc}')
        try:data=json.loads(result.stdout)
        except (ValueError,UnicodeError) as exc:raise CollectionError('Source returned non-JSON content') from exc
        if not post:self.sources.append({'url':url,'sha256':hashlib.sha256(result.stdout).hexdigest()})
        return data

def array(value,label,empty=False):
    if not isinstance(value,list) or (not value and not empty) or not all(isinstance(v,dict) for v in value):
        raise CollectionError(f'Invalid or empty {label}')
    return value

def local_start(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]+)?)?(?:Z|[+-][0-9]{2}:[0-9]{2})?',value):
        raise CollectionError('Missing or invalid start timestamp')
    try:dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError as exc:raise CollectionError('Invalid start timestamp') from exc
    if dt.second or dt.microsecond:raise CollectionError('Unexpected sub-minute performance time')
    return dt.astimezone(LONDON).replace(tzinfo=None) if dt.tzinfo else dt

def row(venue,title,start,notes,url,hosts):
    if not isinstance(title,str) or not title.strip() or len(title)>200:raise CollectionError('Invalid film title')
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.netloc not in hosts:raise CollectionError('Unexpected booking host')
    return dict(cinema=venue,title=title.strip(),date=str(start.date()),time=start.strftime('%H:%M'),notes=notes,bookingUrl=url)

def finish(rows,start,end):
    if not rows:raise CollectionError('No screenings returned; review source manually')
    seen={}
    for item in rows:
        if not start<=date.fromisoformat(item['date'])<end:raise CollectionError('Out-of-window screening')
        key=item['bookingUrl']
        if key in seen and seen[key]!=item:raise CollectionError('Conflicting duplicate booking ID')
        seen[key]=item
    return sorted(seen.values(),key=lambda r:(r['date'],r['time'],r['title'],r['bookingUrl']))

def tyneside(events,instances,start,end):
    lookup={}
    for e in array(events,'events'):
        if not e.get('attribute_Medium') or not isinstance(e.get('duration'),int) or e['duration']<=0:
            raise CollectionError('Unexpected non-screening event: classification needs review')
        eid=e.get('id')
        if not isinstance(eid,str) or not re.fullmatch(r'\d+[A-Za-z]+',eid):raise CollectionError('Invalid event ID')
        if eid in lookup and lookup[eid]!=e:raise CollectionError('Conflicting event')
        lookup[eid]=e
    rows=[];covered=set()
    labels={'attribute_SubtitledForHardOfHearing':'Captioned for hard of hearing',
            'attribute_SubtitledScreening':'Subtitled','attribute_RelaxedScreening':'Relaxed',
            'attribute_DementiaFriendly':'Dementia friendly','attribute_TynesideBabyClub':'Baby Club',
            'attribute_SilverScreen':'Silver Screen','attribute_35mmScreening':'35mm',
            'attribute_3DScreening':'3D','attribute_QAndAScreening':'Q&A',
            'attribute_SchoolEvent':'School event','attribute_FriendsOnlyScreening':'Friends only'}
    for i in array(instances,'instances'):
        eid=i.get('event',{}).get('id');e=lookup.get(eid)
        if e is None:raise CollectionError('Unknown event in instance feed')
        covered.add(eid)
        if type(i.get('cancelled')) is not bool:raise CollectionError('Missing cancellation status')
        dt=local_start(i.get('start'))
        utc=i.get('startUtc')
        if not isinstance(utc,str):raise CollectionError('Missing UTC start')
        instant=datetime.fromisoformat(utc.replace('Z','+00:00'))
        if instant.tzinfo is None:instant=instant.replace(tzinfo=timezone.utc)
        if instant.astimezone(LONDON).replace(tzinfo=None)!=dt:raise CollectionError('Local/UTC time mismatch')
        if not start<=dt.date()<end:raise CollectionError('Unexpected date filter result')
        iid=i.get('id','');match=re.fullmatch(r'(\d+)[A-Za-z]+',iid)
        if not match:raise CollectionError('Invalid instance ID')
        if i['cancelled']:continue
        notes=['Screen not supplied by feed']+[label for key,label in labels.items() if i.get(key) is True]
        rows.append(row(VENUES['tyneside'],e.get('name'),dt,' · '.join(notes),
                        'https://tynesidecinema.co.uk/book-online/'+match[1]+'/',{'tynesidecinema.co.uk'}))
    if set(lookup)!=covered:raise CollectionError('Incomplete event/instance join')
    return finish(rows,start,end)

def vue(payloads,start,end):
    rows=[]
    if len(payloads)!=(end-start).days:raise CollectionError('Incomplete daily response set')
    for offset,p in enumerate(payloads):
        expected=start+timedelta(days=offset)
        if p.get('responseCode')!=0:raise CollectionError('Vue error response')
        for film in array(p.get('result'),'films',empty=True):
            if '10085' not in film.get('showingInCinemas',[]):raise CollectionError('Wrong Vue cinema')
            for group in array(film.get('showingGroups'),'showing groups',empty=True):
                for s in array(group.get('sessions'),'sessions',empty=True):
                    dt=local_start(s.get('startTime'))
                    if dt.date()!=expected:raise CollectionError('Vue date filter failed')
                    zoned=s.get('showTimeWithTimeZone','')
                    stamp=datetime.fromisoformat(zoned)
                    if stamp.tzinfo is None or local_start(zoned)!=dt or stamp.utcoffset()!=dt.replace(tzinfo=LONDON).utcoffset():
                        raise CollectionError('Vue timezone mismatch')
                    sid=s.get('sessionId');fid=film.get('filmId')
                    if not isinstance(sid,str) or not sid.isdigit() or not isinstance(fid,str):raise CollectionError('Invalid Vue IDs')
                    url=urljoin('https://www.myvue.com',s.get('bookingUrl',''))
                    if urlsplit(url).path!='/book-tickets/summary/10085/'+fid+'/'+sid:raise CollectionError('Vue booking venue/session mismatch')
                    attrs=[a['name'] for a in s.get('attributes',[]) if a.get('attributeType') in {'Session','Language'}]
                    notes=' · '.join([s.get('screenName') or 'Screen not supplied']+attrs)
                    rows.append(row(VENUES['vue'],film.get('filmTitle'),dt,notes,url,{'www.myvue.com'}))
    return finish(rows,start,end)

def everyman(schedule,movies,start,end):
    if set(schedule)!={'X11KB'}:raise CollectionError('Wrong Everyman venue')
    lookup={}
    for m in array(movies,'film metadata'):
        mid=m.get('id')
        if not isinstance(mid,(str,int)) or isinstance(mid,bool) or not str(mid).strip():
            raise CollectionError('Missing film metadata ID')
        mid=str(mid)
        if mid in lookup and lookup[mid]!=m:raise CollectionError('Conflicting film metadata ID')
        lookup[mid]=m
    groups=schedule['X11KB'].get('schedule')
    if not isinstance(groups,dict) or not groups:raise CollectionError('Missing schedule')
    rows=[]
    for mid,days in groups.items():
        if mid not in lookup:raise CollectionError('Missing film title')
        m=lookup[mid];title=m.get('exhibitor',{}).get('title') or m.get('locale',{}).get('title') or m.get('title')
        for day,shows in days.items():
            date.fromisoformat(day)
            for show in array(shows,'showtimes',empty=True):
                dt=local_start(show.get('startsAt'))
                if str(dt.date())!=day:raise CollectionError('Grouped and actual show date disagree')
                # This endpoint includes the upper boundary date. Coverage is explicitly exclusive here.
                if not start<=dt.date()<end:continue
                options=show.get('data',{}).get('ticketing',[])
                urls=[url for o in options if o.get('provider')=='default' for url in o.get('urls',[])]
                url=next((u for u in urls if urlsplit(u).netloc=='purchase.everymancinema.com'),None)
                if not url or not urlsplit(url).path.startswith('/launch/ticketing/'):raise CollectionError('Missing official booking URL')
                tags=show.get('tags',[])
                notes=['Screen '+str(show.get('screen',{}).get('name') or 'not supplied')]
                tag_labels={'Format.Projection.Digital':'Digital','Format.Projection.4k':'4K',
                            'Showtime.Accessibility.ClosedCaption':'Captioned',
                            'Showtime.Restriction.BabyClub':'Baby Club',
                            'Showtime.Restriction.KidsFriendly':'Kids friendly',
                            'Showtime.Restriction.SilverScreen':'Silver Screen',
                            'Showtime.Event.Throwback':'Throwback',
                            'Showtime.Experience.Beyond':'Beyond'}
                relevant=[t for t in tags if t.startswith(('Showtime.','Format.'))]
                unknown=set(relevant)-set(tag_labels)
                if unknown:raise CollectionError('Unmapped Everyman screening tags require review')
                notes += [tag_labels[t] for t in relevant]
                rows.append(row(VENUES['everyman'],title,dt,' · '.join(notes),url,{'purchase.everymancinema.com'}))
    return finish(rows,start,end)

def collect(venue,client,start,end):
    if venue=='tyneside':
        base='https://system.spektrix.com/tynesidecinema/api/v3'
        events=client.get(base+'/events?'+urlencode({'instanceStart_from':str(start),'instanceStart_to':str(end)}))
        instances=client.get(base+'/instances?'+urlencode({'startFrom':str(start),'startTo':str(end)}))
        return tyneside(events,instances,start,end)
    if venue=='vue':
        base='https://www.myvue.com/api/microservice'
        client.get(base+'/auth/token',guest=True,post=True)
        payloads=[]
        for offset in range((end-start).days):
            query=urlencode({'showingDate':str(start+timedelta(days=offset)),'includesSession':'true','includeSessionAttributes':'true'})
            payloads.append(client.get(base+'/showings/cinemas/10085/films?'+query,guest=True))
        return vue(payloads,start,end)
    base='https://www.everymancinema.com/api/gatsby-source-boxofficeapi'
    query=urlencode({'theaters':json.dumps({'id':'X11KB','timeZone':'Europe/London'},separators=(',',':')),'from':str(start),'to':str(end)})
    schedule=client.get(base+'/schedule?'+query)
    if set(schedule)!={'X11KB'}:raise CollectionError('Wrong venue')
    ids=list(schedule['X11KB'].get('schedule',{}))
    if not ids:raise CollectionError('Empty schedule')
    movies=[]
    for offset in range(0,len(ids),50):
        query=urlencode([('ids',mid) for mid in ids[offset:offset+50]]+[('basic','true')])
        movies.extend(client.get(base+'/movies?'+query))
    return everyman(schedule,movies,start,end)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('venue',choices=VENUES)
    p.add_argument('--days',type=int,default=7)
    p.add_argument('--output',type=Path)
    args=p.parse_args(argv)
    if not 1<=args.days<=7:p.error('Days must be between 1 and 7 during validation')
    try:
        now=datetime.now(timezone.utc);start=now.astimezone(LONDON).date();end=start+timedelta(days=args.days)
        with tempfile.TemporaryDirectory() as temp:
            client=PublicClient(Path(temp)/'anonymous-cookies.txt')
            rows=collect(args.venue,client,start,end)
        result=dict(schemaVersion=1,status='needs_review',cinema=VENUES[args.venue],collectionMode='live-public-source',
                    collectedAt=now.isoformat(),updateMode='review-candidate-only',sources=client.sources,
                    coverage={'from':str(start),'through':str(end-timedelta(days=1))},screenings=rows)
        out=args.output or ROOT/'work'/(args.venue+'-candidate.json')
        write_candidate(out,result)
        print(f"{VENUES[args.venue]}: {len(rows)} screenings saved for review -> {out}")
        return 0
    except (ValueError,OSError,KeyError,TypeError,AttributeError,subprocess.SubprocessError) as exc:
        print(f'Collection failed; previous outputs unchanged: {exc}',file=sys.stderr);return 1

if __name__=='__main__':sys.exit(main())
