#!/usr/bin/env python3
"""Collect the explicit seven-day Alnwick programme into a review-only candidate."""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

URL = 'https://www.alnwickplayhouse.co.uk/cinema-l2gp'
ROOT = Path(__file__).resolve().parent
MAX_BYTES = 5_000_000

class CollectionError(ValueError):
    pass

class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []
    def has(self, cls):
        return cls in self.attrs.get('class', '').split()
    def find(self, predicate):
        return [n for c in self.children if isinstance(c, Node)
                for n in ([c] if predicate(c) else []) + c.find(predicate)]
    def text(self):
        return ' '.join(' '.join(c.text() if isinstance(c, Node) else c
                                 for c in self.children).split())

class Document(HTMLParser):
    VOID = set('area base br col embed hr img input link meta param source track wbr'.split())
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)
    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return
    def handle_data(self, text):
        self.stack[-1].children.append(text)

def one(nodes, context):
    if len(nodes) != 1:
        raise CollectionError(f'Expected one {context}; found {len(nodes)}')
    return nodes[0]

def parse_programme(html, today):
    doc = Document()
    doc.feed(html)
    doc.close()
    if len(doc.stack) != 1:
        raise CollectionError('Truncated HTML document')
    cards = doc.root.find(lambda n: n.has('movie-card'))
    if not cards:
        raise CollectionError('No movie cards: blocked response or changed markup')
    week = [(today + timedelta(days=i)).isoformat() for i in range(7)]
    rows, seen = [], {}
    for card in cards:
        title = one(card.find(lambda n: n.has('title')), 'film title').text()
        if not title or len(title)>200:
            raise CollectionError('Invalid title')
        days = card.find(lambda n: n.has('day'))
        if [n.attrs.get('data-date') for n in days] != week:
            raise CollectionError('Incomplete or stale seven-day programme')
        for day in days:
            shows = one(day.find(lambda n: n.has('shows')), 'shows container')
            links = shows.find(lambda n: n.tag == 'a')
            if not links and 'No shows' not in day.text():
                raise CollectionError('Empty day without explicit No shows marker')
            for link in links:
                clock = one(link.find(lambda n: n.has('movie-time-start')), 'start time').text()
                if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', clock):
                    raise CollectionError('Invalid start time')
                booking = urljoin(URL, link.attrs.get('href', ''))
                parts = urlsplit(booking)
                ids = parse_qs(parts.query).get('EventInstanceId', [])
                if (parts.scheme != 'https' or parts.netloc != 'www.alnwickplayhouse.co.uk'
                    or parts.path != '/spektrix/ChooseSeats' or parts.fragment
                    or len(ids)!=1 or not re.fullmatch(r'[A-Za-z0-9]+', ids[0])):
                    raise CollectionError('Unexpected booking link')
                notes = ' · '.join(n.text() for n in link.find(lambda n: n.has('property')))
                row = dict(cinema='Alnwick Playhouse', title=title, date=day.attrs['data-date'],
                           time=clock, bookingUrl=booking, notes=notes)
                if ids[0] in seen:
                    if seen[ids[0]] != row:
                        raise CollectionError('Conflicting duplicate performance')
                    continue
                seen[ids[0]] = row
                rows.append(row)
    if not rows:
        raise CollectionError('Empty programme requires manual review')
    rows.sort(key=lambda r:(r['date'], r['time'], r['title'], r['bookingUrl']))
    return rows, week

class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if parts.scheme != 'https' or parts.netloc != 'www.alnwickplayhouse.co.uk' or parts.path.startswith('/csq'):
            raise CollectionError('Source redirected to an access challenge')
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def fetch():
    req = urllib.request.Request(URL, headers={'User-Agent':'CinemaNorthEastCollector/1.0'})
    with urllib.request.build_opener(OfficialRedirects()).open(req, timeout=25) as response:
        if response.headers.get_content_type() != 'text/html':
            raise CollectionError('Source is not HTML')
        raw = response.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:
            raise CollectionError('Source exceeds size limit')
        return raw.decode('utf-8', errors='strict')

def collect(html, today, captured_at):
    rows, week = parse_programme(html, today)
    return dict(schemaVersion=1, status='needs_review', source=URL,
                collectedAt=captured_at, sourceSha256=hashlib.sha256(html.encode()).hexdigest(),
                updateMode='review-candidate-only', coverage={'from':week[0], 'through':week[-1]},
                screenings=rows)

def write_candidate(path, result):
    path = Path(path).resolve()
    if path.name == 'screenings.json' or path.suffix != '.json':
        raise CollectionError('Output must be a candidate .json file, never screenings.json')
    if path.is_relative_to(ROOT / 'tests'):
        raise CollectionError('Output overlaps test sources')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temp = stream.name
            stream.write(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html', type=Path, help='Read saved programme HTML')
    parser.add_argument('--today', type=date.fromisoformat, help='Fixture reference date; requires --html')
    parser.add_argument('--output', type=Path, default=ROOT/'work'/'alnwick-candidate.json')
    args = parser.parse_args(argv)
    if args.today and not args.html:
        parser.error('--today requires --html')
    try:
        now = datetime.now(timezone.utc)
        today = args.today or now.astimezone(ZoneInfo('Europe/London')).date()
        html = args.html.read_text(encoding='utf-8') if args.html else fetch()
        result = collect(html, today, now.isoformat())
        write_candidate(args.output, result)
        print(f"Collected {len(result['screenings'])} screenings for review -> {args.output}")
        return 0
    except (ValueError, OSError) as exc:
        print(f'Collection failed; existing files unchanged: {exc}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
