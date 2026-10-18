"""Deterministic refresh tests. No network, wall-clock dependency or live fixtures."""
import copy
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import refresh_feed as refresh

NOW = datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=1)


def candidate(key, title='Fresh film'):
    venue, mode, host = refresh.VENUES[key]
    path = {'alnwick': '/alnwickplayhouse/api/v3/',
            'tyneside': '/tynesidecinema/api/v3/',
            'everyman': '/api/gatsby-source-boxofficeapi/'}[key]
    booking = {'alnwick': 'https://www.alnwickplayhouse.co.uk/book',
               'tyneside': 'https://tynesidecinema.co.uk/book-online/1/',
               'everyman': 'https://purchase.everymancinema.com/launch/ticketing/1'}[key]
    return {'schemaVersion': 1, 'cinema': venue, 'collectionMode': mode,
            'collectedAt': NOW.isoformat(),
            'coverage': {'from': '2026-10-18', 'through': '2026-10-24'},
            'sources': [{'url': 'https://' + host + path + name, 'sha256': '0' * 64}
                        for name in ['events', 'instances']],
            'screenings': [{'cinema': venue, 'title': title, 'date': '2026-10-18',
                            'time': '13:00', 'notes': 'Screen 1', 'bookingUrl': booking}]}


def baseline():
    data = {'schemaVersion': 1, 'screenings': [], 'venueStatus': {}, 'custom': 'preserve'}
    for key, (venue, _, _) in refresh.VENUES.items():
        c = candidate(key, 'Last good film')
        data['screenings'] += c['screenings']
        data['venueStatus'][venue] = {'status': 'collected', 'collectedAt': OLD.isoformat(),
                                     'coverage': {'from': '2026-10-17', 'through': '2026-10-23'}}
    data['screenings'].append({'cinema': 'Vue Cramlington', 'title': 'Old Vue film',
                              'date': '2026-10-18', 'time': '15:00'})
    data['venueStatus']['Vue Cramlington'] = {
        'status': 'unavailable', 'lastAttemptAt': OLD.isoformat(), 'error': 'HTTP 403'}
    return data


class RefreshTests(unittest.TestCase):
    def run_refresh(self, collector=candidate, existing=None):
        return refresh.refresh(baseline() if existing is None else existing,
                               collector, clock=lambda: NOW)

    def test_three_successes_replace_only_their_venues(self):
        original = baseline()
        before = copy.deepcopy(original)
        result, report = self.run_refresh(existing=original)
        self.assertEqual(original, before)
        self.assertEqual(report['failedVenues'], 0)
        self.assertEqual(result['custom'], 'preserve')
        self.assertEqual(len(result['screenings']), 4)
        self.assertEqual(sum(r['title'] == 'Fresh film' for r in result['screenings']), 3)
        self.assertEqual(result['venueStatus']['Vue Cramlington'], before['venueStatus']['Vue Cramlington'])

    def test_failure_of_each_venue_is_independent_and_retains_last_good(self):
        for failed in refresh.VENUES:
            called = []
            def collect(key):
                called.append(key)
                if key == failed:
                    raise OSError('HTTP 503')
                return candidate(key)
            with self.subTest(venue=failed):
                result, report = self.run_refresh(collect)
                self.assertEqual(called, list(refresh.VENUES))
                self.assertNotIn('vue', called)
                venue = refresh.VENUES[failed][0]
                self.assertEqual([r['title'] for r in result['screenings'] if r['cinema'] == venue], ['Last good film'])
                status = result['venueStatus'][venue]
                self.assertEqual(status['collectedAt'], OLD.isoformat())
                self.assertEqual(status['lastAttemptAt'], NOW.isoformat())
                self.assertEqual(status['status'], 'unavailable')
                self.assertEqual(report['failedVenues'], 1)

    def test_total_failure_keeps_all_rows_and_updates_attempt_statuses(self):
        def fail(key):
            raise RuntimeError('Source blocked')
        result, report = self.run_refresh(fail)
        self.assertEqual(result['screenings'], refresh.build(baseline())['screenings'])
        self.assertEqual(report['failedVenues'], 3)
        self.assertEqual(result['generatedAt'], NOW.isoformat())

    def test_invalid_empty_stale_future_offline_and_wrong_venue_are_retained(self):
        cases = [
            {'screenings': []}, {'screenings': 'invalid'},
            {'collectedAt': (NOW - timedelta(minutes=2)).isoformat()},
            {'collectedAt': (NOW + timedelta(minutes=1)).isoformat()},
            {'collectionMode': 'offline-fixture'}, {'cinema': 'Vue Cramlington'},
            {'coverage': {'from': '2026-10-18', 'through': '2026-10-19'}},
            {'sources': []},
            {'sources': [{'url': 'https://attacker.example/data', 'sha256': '0' * 64}] * 2},
        ]
        for bad in cases:
            def collect(key):
                c = candidate(key)
                if key == 'alnwick':
                    c.update(bad)
                return c
            with self.subTest(bad=bad):
                result, report = self.run_refresh(collect)
                self.assertEqual(report['failedVenues'], 1)
                self.assertIn('Last good film', [r['title'] for r in result['screenings'] if r['cinema'] == 'Alnwick Playhouse'])

    def test_valid_wrong_venue_rows_cannot_replace_another_venue(self):
        result, report = self.run_refresh(lambda key: candidate('everyman') if key == 'alnwick' else candidate(key))
        self.assertEqual(report['failedVenues'], 1)
        self.assertEqual(result['venueStatus']['Alnwick Playhouse']['status'], 'unavailable')

    def test_partial_venue_candidate_rejected_atomically(self):
        def collect(key):
            c = candidate(key)
            if key == 'tyneside':
                c['screenings'] += [{**c['screenings'][0], 'time': '99:00'}]
            return c
        result, report = self.run_refresh(collect)
        self.assertEqual(report['failedVenues'], 1)
        self.assertEqual([r['title'] for r in result['screenings'] if r['cinema'] == 'Tyneside Cinema'], ['Last good film'])

    def test_recovery_clears_old_error_and_attempt(self):
        original = baseline()
        original['venueStatus']['Tyneside Cinema'].update(status='unavailable', error='old error', lastAttemptAt=OLD.isoformat())
        result, _ = self.run_refresh(existing=original)
        self.assertEqual(result['venueStatus']['Tyneside Cinema']['status'], 'collected')
        self.assertNotIn('error', result['venueStatus']['Tyneside Cinema'])
        self.assertNotIn('lastAttemptAt', result['venueStatus']['Tyneside Cinema'])

    def test_baseline_failure_does_not_collect_or_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'screenings.json'
            path.write_text('{broken')
            collector = unittest.mock.Mock()
            with self.assertRaises(ValueError):
                refresh.refresh_file(path, collector, lambda: NOW)
            collector.assert_not_called()
            self.assertEqual(path.read_text(), '{broken')
            with self.assertRaises(FileNotFoundError):
                refresh.refresh_file(Path(folder) / 'missing.json', collector, lambda: NOW)

    def test_unsupported_baseline_schema_aborts_before_collection(self):
        data = baseline()
        data['schemaVersion'] = 2
        collector = unittest.mock.Mock()
        with self.assertRaises(ValueError):
            self.run_refresh(collector, data)
        collector.assert_not_called()

    def test_corrupt_baseline_status_aborts_before_collection(self):
        for value in [[], {'Alnwick Playhouse': []}, {'Alnwick Playhouse': {'collectedAt': '2026-10-18'}}]:
            data = baseline()
            data['venueStatus'] = value
            collector = unittest.mock.Mock()
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_refresh(collector, data)
            collector.assert_not_called()

    def test_atomic_replace_failure_preserves_original_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'screenings.json'
            text = json.dumps(baseline())
            path.write_text(text)
            with patch('build_feed.os.replace', side_effect=OSError('Disk error')):
                with self.assertRaises(OSError):
                    refresh.refresh_file(path, candidate, lambda: NOW)
            self.assertEqual(path.read_text(), text)
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_disk_write_has_degraded_status_and_valid_rows(self):
        def collect(key):
            if key == 'everyman':
                raise ValueError('Empty schedule')
            return candidate(key)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'screenings.json'
            path.write_text(json.dumps(baseline()))
            report = refresh.refresh_file(path, collect, lambda: NOW)
            data = json.loads(path.read_text())
            self.assertEqual(report['failedVenues'], 1)
            self.assertEqual(data['venueStatus']['Everyman Newcastle']['status'], 'unavailable')
            self.assertEqual(len(data['screenings']), 4)

    def test_source_hash_and_venue_path_required(self):
        for update in [{'sha256': 'not a hash'}, {'url': 'https://system.spektrix.com/other/api/v3/events'}]:
            c = candidate('alnwick')
            c['sources'][0].update(update)
            with self.assertRaises(ValueError):
                refresh.validate_candidate('alnwick', c, NOW)

    def test_candidate_days_use_london_date_across_bst(self):
        now = datetime(2026, 10, 18, 23, 30, tzinfo=timezone.utc)
        c = candidate('alnwick')
        c.update(collectedAt=now.isoformat(), coverage={'from': '2026-10-19', 'through': '2026-10-25'})
        c['screenings'][0]['date'] = '2026-10-19'
        self.assertEqual(refresh.validate_candidate('alnwick', c, now), c)

    def test_command_uses_new_output_and_no_fixture_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            def runner(command, **kwargs):
                calls.append((command, kwargs))
                Path(command[-1]).write_text(json.dumps(candidate('tyneside')))
                return SimpleNamespace(returncode=0, stderr='')
            result = refresh.collect_one('tyneside', folder, runner)
            self.assertEqual(result, candidate('tyneside'))
            command, options = calls[0]
            self.assertIn('tyneside', command)
            self.assertNotIn('--events', command)
            self.assertEqual(options['timeout'], 180)
            with self.assertRaises(ValueError):
                refresh.collect_one('tyneside', folder, runner)
            self.assertEqual(len(calls), 1)

    def test_timeout_nonzero_missing_and_malformed_output(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RuntimeError):
                refresh.collect_one('alnwick', folder, unittest.mock.Mock(side_effect=subprocess.TimeoutExpired('cmd', 180)))
            with self.assertRaises(RuntimeError):
                refresh.collect_one('alnwick', folder, lambda *a, **k: SimpleNamespace(returncode=1, stderr='HTTP 503'))
            with self.assertRaises(ValueError):
                refresh.collect_one('alnwick', folder, lambda *a, **k: SimpleNamespace(returncode=0, stderr=''))
            def malformed(command, **kwargs):
                Path(command[-1]).write_text('bad JSON')
                return SimpleNamespace(returncode=0, stderr='')
            with self.assertRaises(ValueError):
                refresh.collect_one('alnwick', folder, malformed)

    def test_vue_is_not_an_automatic_collection_target(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = unittest.mock.Mock()
            with self.assertRaises(ValueError):
                refresh.collect_one('vue', folder, runner)
            runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
