#!/usr/bin/env python3
"""Refresh the three working official sources; preserve every failed venue's data.

No fixture or candidate-directory input is accepted by the command-line entrypoint.
Candidates exist only in a new temporary directory for this run. A degraded run
still writes truthful failure statuses; the workflow deploys those before failing
its final health check. A corrupt baseline or failed atomic write is fatal.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from build_feed import atomic_write, build, mark_unavailable, merge_candidate

ROOT = Path(__file__).resolve().parent
LONDON = ZoneInfo('Europe/London')
# Deliberately no Vue request: its anonymous endpoint rejected the Actions runner.
VENUES = {
    'alnwick': ('Alnwick Playhouse', 'live-public-api', 'system.spektrix.com'),
    'tyneside': ('Tyneside Cinema', 'live-public-source', 'system.spektrix.com'),
    'everyman': ('Everyman Newcastle', 'live-public-source', 'www.everymancinema.com'),
}
DAYS = 7


def utcnow():
    return datetime.now(timezone.utc)


def validate_baseline(existing):
    if not isinstance(existing, dict) or existing.get('schemaVersion') != 1:
        raise ValueError('Unsupported feed schema')
    result = build(existing)
    statuses = result.get('venueStatus', {})
    if not isinstance(statuses, dict):
        raise ValueError('Invalid baseline venue statuses')
    for status in statuses.values():
        if not isinstance(status, dict):
            raise ValueError('Invalid baseline venue status')
        if 'collectedAt' in status:
            stamp = datetime.fromisoformat(status['collectedAt'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('Baseline collection timestamp must include timezone')
    return result


def validate_candidate(key, candidate, started):
    venue, mode, host = VENUES[key]
    candidate = build(candidate)
    if candidate.get('cinema', venue) != venue or any(
        row['cinema'] != venue for row in candidate['screenings']
    ):
        raise ValueError('Collector returned the wrong venue')
    if candidate.get('collectionMode') != mode:
        raise ValueError('Collector did not return its expected live collection mode')
    stamp = datetime.fromisoformat(candidate.get('collectedAt', '').replace('Z', '+00:00'))
    if stamp.tzinfo is None or stamp < started - timedelta(minutes=1):
        raise ValueError('Candidate was not freshly collected during this run')
    day = stamp.astimezone(LONDON).date()
    if candidate.get('coverage') != {
        'from': str(day), 'through': str(day + timedelta(days=DAYS - 1))
    }:
        raise ValueError('Candidate does not cover the requested seven-day window')
    sources = candidate.get('sources')
    if not isinstance(sources, list) or len(sources) < 2:
        raise ValueError('Missing official-source evidence')
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError('Invalid official-source evidence')
        url = urlsplit(source.get('url', ''))
        if (url.scheme != 'https' or url.hostname != host or url.username or
                url.password or url.port not in (None, 443) or
                not re.fullmatch(r'[0-9a-f]{64}', source.get('sha256', ''))):
            raise ValueError('Invalid official-source URL or content hash')
        expected = {
            'alnwick': '/alnwickplayhouse/api/v3/',
            'tyneside': '/tynesidecinema/api/v3/',
            'everyman': '/api/gatsby-source-boxofficeapi/',
        }[key]
        if not url.path.startswith(expected):
            raise ValueError('Source evidence belongs to another venue or API')
    return candidate


def collect_one(key, directory, runner=subprocess.run):
    if key not in VENUES:
        raise ValueError('Unsupported automatic collector')
    output = Path(directory) / (key + '-candidate.json')
    # Even an injected runner cannot reuse a prior output at this location.
    if output.exists():
        raise ValueError('Candidate output already exists')
    script = ['collect_spektrix.py'] if key == 'alnwick' else ['collect_additional.py', key]
    command = [sys.executable, str(ROOT / script[0]), *script[1:],
               '--days', str(DAYS), '--output', str(output)]
    try:
        process = runner(command, cwd=ROOT, capture_output=True, text=True,
                         timeout=180, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Official-source collector timed out after 180 seconds') from exc
    if process.returncode:
        # JSON quoting prevents untrusted response text becoming workflow commands.
        print('Collector diagnostics: ' + json.dumps(process.stderr[-4000:]), file=sys.stderr)
        raise RuntimeError(f'Official-source collector failed (exit {process.returncode}); see run log')
    if not output.is_file() or output.stat().st_size > 5_000_000:
        raise ValueError('Collector output is missing or exceeds the size limit')
    return json.loads(output.read_text(encoding='utf-8'))


def refresh(existing, collector, clock=utcnow):
    """Pure orchestration boundary; collector and clock are injected in tests."""
    result = validate_baseline(existing)
    started = clock()
    reports = []
    for key, (venue, _, _) in VENUES.items():
        try:
            candidate = validate_candidate(key, collector(key), started)
            result = merge_candidate(result, candidate, now=clock())
            reports.append({'venue': venue, 'status': 'collected',
                            'screenings': len(candidate['screenings'])})
        except Exception as exc:
            # A failed or malformed source must not prevent the other venues' refresh.
            # KeyboardInterrupt/SystemExit are not swallowed; no file has been written yet.
            message = ' '.join(str(exc).split())[:300] or type(exc).__name__
            result = mark_unavailable(result, venue, message, now=clock())
            retained = sum(r['cinema'] == venue for r in result['screenings'])
            reports.append({'venue': venue, 'status': 'unavailable',
                            'retainedScreenings': retained, 'error': message})
    finished = clock().isoformat()
    result['generatedAt'] = finished
    result['updateMode'] = 'automatic official-source collection; see per-cinema status'
    result['warning'] = 'Coverage varies by cinema. Times can change; confirm with the official cinema.'
    report = {'startedAt': started.isoformat(), 'finishedAt': finished,
              'venues': reports,
              'failedVenues': sum(r['status'] != 'collected' for r in reports),
              'totalScreenings': len(result['screenings'])}
    return build(result), report


def refresh_file(path, collector, clock=utcnow):
    path = Path(path)
    # Never silently initialize an empty feed if the committed last-good feed is missing.
    existing = json.loads(path.read_text(encoding='utf-8'))
    result, report = refresh(existing, collector, clock)
    atomic_write(path, result)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', type=Path, default=ROOT / 'screenings.json')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.feed.resolve() == args.report.resolve():
        parser.error('Feed and report paths must differ')
    try:
        with tempfile.TemporaryDirectory(prefix='cinema-refresh-') as directory:
            report = refresh_file(args.feed, lambda key: collect_one(key, directory))
        atomic_write(args.report, report)
        print(json.dumps(report, indent=2))
        return 0
    except (ValueError, OSError, TypeError, AttributeError) as exc:
        print('Refresh stopped: ' + json.dumps(str(exc)), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
