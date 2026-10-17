#!/usr/bin/env python3
"""Experimental Alnwick Playhouse collector. Fails closed on uncertain extraction."""
import json, re, sys, urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
URL='https://www.alnwickplayhouse.co.uk/cinema-l2gp'
OUT=Path(__file__).parent/'data'/'screenings.json'
class Text(HTMLParser):
 def __init__(self): super().__init__(); self.parts=[]
 def handle_data(self,data):
  s=' '.join(data.split())
  if s:self.parts.append(s)
def fetch():
 req=urllib.request.Request(URL,headers={'User-Agent':'CinemaNorthEastResearch/0.7 (contact site owner before production use)'})
 with urllib.request.urlopen(req,timeout=20) as res:
  return res.read().decode('utf-8','replace')
def inspect(html):
 parser=Text();parser.feed(html)
 text='\n'.join(parser.parts)
 # Diagnostic only: site markup must be checked before building a reliable parser.
 return {'source':URL,'checked_at':datetime.now(timezone.utc).isoformat(),'page_title_present':'Cinema' in text,'screen_mentions':len(re.findall(r'Screen\s*[12]',text,re.I)),'time_mentions':len(re.findall(r'\b(?:[01]?\d|2[0-3]):[0-5]\d\b',text)),'status':'needs_parser_validation','screenings':[]}
def main():
 try: result=inspect(fetch())
 except Exception as e:
  print(f'Fetch failed: {e}',file=sys.stderr);return 1
 print(json.dumps(result,indent=2))
 # Never overwrite existing verified screenings with unvalidated or empty data.
 if not result['page_title_present'] or not result['time_mentions']:
  print('Unexpected page content; feed unchanged',file=sys.stderr);return 2
 diagnostic=OUT.with_name('collector-diagnostic.json')
 diagnostic.write_text(json.dumps(result,indent=2)+'\n')
 print('Diagnostic saved. No screenings published until extraction is validated.')
 return 0
if __name__=='__main__':sys.exit(main())
