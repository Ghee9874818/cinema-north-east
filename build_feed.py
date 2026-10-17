#!/usr/bin/env python3
"""Validate a cinema-supplied JSON feed and build a static app feed.
Usage: python build_feed.py cinema_feed.json [output.json]
Does not scrape or fetch websites; obtain feeds with permission.
"""
import json, sys, datetime
from pathlib import Path
CINEMAS = {"Alnwick Playhouse", "Vue Cramlington", "ODEON Silverlink", "ODEON Metrocentre", "Everyman Newcastle", "Cineworld Newcastle", "Tyneside Cinema"}
def build(source):
    if not isinstance(source, dict) or not isinstance(source.get("screenings"), list):
        raise ValueError("Expected object with screenings array")
    output=[]; seen=set()
    for i, item in enumerate(source["screenings"]):
        try:
            cinema=item["cinema"]; title=item["title"].strip(); date=item["date"]; time=item["time"]
            if cinema not in CINEMAS or not title or len(title)>200: raise ValueError("Invalid cinema/title")
            datetime.date.fromisoformat(date)
            datetime.time.fromisoformat(time)
            link=item.get("bookingUrl", "")
            if link and not link.startswith("https://"): raise ValueError("Booking URL must use HTTPS")
            key=(cinema,title.casefold(),date,time)
            if key in seen: continue
            seen.add(key)
            output.append({"cinema":cinema,"title":title,"date":date,"time":time,"bookingUrl":link})
        except (KeyError,TypeError,ValueError) as e:
            raise ValueError(f"Invalid screening row {i+1}: {e}") from e
    output.sort(key=lambda r:(r["date"],r["time"],r["cinema"]))
    return {"schemaVersion":1,"screenings":output}
if __name__ == "__main__":
    if len(sys.argv)<2: sys.exit("Usage: python build_feed.py input.json [output.json]")
    data=build(json.loads(Path(sys.argv[1]).read_text()))
    out=Path(sys.argv[2] if len(sys.argv)>2 else "screenings.json")
    out.write_text(json.dumps(data,indent=2,ensure_ascii=False))
    print(f"Validated {len(data['screenings'])} screenings -> {out}")
