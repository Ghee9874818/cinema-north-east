"""Small dependency-free deployment contract checks; YAML is also parsed in review."""
from pathlib import Path
import json
import os
import re
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/daily-refresh.yml'


class RefreshWorkflowTests(unittest.TestCase):
    def test_main_only_and_no_feed_push_loop(self):
        source = WORKFLOW.read_text()
        self.assertIn("github.ref == 'refs/heads/main'", source)
        self.assertIn("github.repository == 'Ghee9874818/cinema-north-east'", source)
        self.assertIn('workflow_dispatch:', source)
        self.assertRegex(source, r'push:\s+branches: \[main\]\s+paths:\s+- \.github/workflows/daily-refresh.yml\s+permissions:')
        self.assertNotIn('pull_request', source)
        self.assertNotIn('  workflow_run:', source)

    def test_optional_staged_schedule_is_correct_when_enabled(self):
        # The first activation commit may omit schedule until a real deployment succeeds.
        source = WORKFLOW.read_text()
        if '  schedule:' in source:
            self.assertRegex(source, r"schedule:\s+- cron: '17 8 \* \* \*'\s+timezone: Europe/London")

    def test_actions_are_pinned_and_no_persistent_secret_is_requested(self):
        source = WORKFLOW.read_text()
        uses = re.findall(r'uses: ([^\s]+)', source)
        self.assertTrue(uses)
        self.assertTrue(all(re.fullmatch(r'actions/[a-z-]+@[0-9a-f]{40}', use) for use in uses))
        self.assertNotIn('secrets.', source)
        self.assertNotIn('configure-pages', source)
        self.assertNotIn('--force', source)
        self.assertIn('persist-credentials: false', source)
        self.assertIn('cancel-in-progress: false', source)

    def test_only_public_files_are_packaged(self):
        source = WORKFLOW.read_text()
        self.assertIn('cp index.html screenings.json "$RUNNER_TEMP/cinema-site/"', source)
        self.assertIn('path: ${{ runner.temp }}/cinema-site', source)
        self.assertNotIn('path: .', source)
        config = (ROOT / '_config.yml').read_text()
        for excluded in ['tests', 'additional_tests', 'refresh_feed.py']:
            self.assertIn('  - ' + excluded + '\n', config)

    def test_deployment_is_explicit_and_degraded_status_is_reported_afterwards(self):
        source = WORKFLOW.read_text()
        self.assertIn('pages: write', source)
        self.assertIn('id-token: write', source)
        self.assertIn('needs: refresh', source)
        self.assertIn('name: github-pages', source)
        self.assertLess(source.index('uses: actions/deploy-pages@'), source.index('Surface a degraded collection'))
        self.assertIn('git push origin HEAD:refs/heads/main', source)
        self.assertIn('git add -- screenings.json', source)
        self.assertIn('if: needs.refresh.outputs.failed', source)
        self.assertIn('Verify the published bytes', source)
        self.assertIn('actions: read', source)
        self.assertLess(source.index('Wait for earlier legacy Pages builds'), source.index('uses: actions/deploy-pages@'))
        self.assertIn("run['head_sha'] == os.environ['GITHUB_SHA']", source)


    def run_gate(self, states, event='push', ticks=None):
        source = WORKFLOW.read_text()
        code = re.search(r"python - <<'PY_GATE'\n(.*?)\n          PY_GATE", source, re.S).group(1)
        results = [SimpleNamespace(stdout=json.dumps([{'workflow_runs': rows}])) for rows in states]
        env = {'GITHUB_REPOSITORY': 'Ghee9874818/cinema-north-east',
               'GITHUB_SHA': 'trigger-sha', 'GITHUB_EVENT_NAME': event}
        with patch.dict(os.environ, env), patch('subprocess.run', side_effect=results) as run, \
                patch('time.sleep') as sleep, patch('time.monotonic', side_effect=ticks or [0] * 20):
            exec(compile(textwrap.dedent(code), 'legacy-pages-gate', 'exec'), {})
            return run.call_count, sleep.call_count

    def legacy_run(self, status, sha='trigger-sha'):
        return {'name': 'pages build and deployment', 'head_sha': sha, 'status': status}

    def test_legacy_gate_waits_for_registration_then_completion(self):
        calls, sleeps = self.run_gate([[], [self.legacy_run('in_progress')], [self.legacy_run('completed')]])
        self.assertEqual((calls, sleeps), (3, 2))

    def test_legacy_gate_also_waits_for_older_inflight_build(self):
        done = self.legacy_run('completed')
        calls, sleeps = self.run_gate([[done, self.legacy_run('queued', 'older')], [done, self.legacy_run('completed', 'older')]])
        self.assertEqual((calls, sleeps), (2, 1))

    def test_manual_and_schedule_need_no_triggering_legacy_build(self):
        for event in ['workflow_dispatch', 'schedule']:
            with self.subTest(event=event):
                self.assertEqual(self.run_gate([[]], event=event), (1, 0))

    def test_push_without_observable_legacy_build_fails_before_deploy(self):
        with self.assertRaises(SystemExit):
            self.run_gate([[]], ticks=[0, 301])


if __name__ == '__main__':
    unittest.main()
