# Cinema North East integrated collector review

Prepared 18 October 2026. This package integrates the recovered original Vue, Tyneside and Everyman collectors with feed and UI integrity fixes. No live site or GitHub branch was changed during this integration.

## Verification

- 38 tests in `tests/` passed.
- 17 additional collector tests in `additional_tests/` passed.
- Inline JavaScript and Playwright harness syntax checks passed.
- Recovered live candidates are **offline fixtures**, collected on 18 October at about 11:05–11:08 UTC. Their 231 Vue, 104 Tyneside and 101 Everyman rows successfully merge together while preserving venue metadata and booking links. These counts are not a fresh live collection or a claim of current ticket availability.
- Browser smoke tests are prepared but have **not run successfully**: local Chromium startup was blocked by the execution sandbox. The new Actions integrity workflow runs them and saves a mobile screenshot.
- GitHub integration returned HTTP403 `Resource not accessible by integration` on create-tree. No push or new Actions run occurred. Repository authorization must be restored through its supported connection before pushing.

## Changes

Everyman collection rejects missing or date-only start timestamps, malformed calendar times and conflicting duplicate movie metadata IDs. Identical duplicate metadata is harmless and remains accepted. Four regression tests cover these cases.

`build_feed.py` preserves notes, format, screen, IDs and metadata; removes exact duplicates only; rejects conflicting IDs, invalid dates/times and nonofficial booking hosts; accepts the recovered `live-public-source` mode; and permits Everyman's verified `purchase.everymancinema.com` booking host only for Everyman. Venue replacement rejects empty, stale, future-dated, regressing and out-of-coverage candidates. It replaces exactly one venue, preserves all other venues, records per-venue freshness and writes atomically. A successful candidate replaces the whole selected venue with its explicitly advertised current coverage window. Failed collection status can preserve last-good rows via `mark_unavailable`.

The UI uses direct validated booking links, keeps notes and format details, shows per-venue freshness and coverage, and clearly marks unconnected venues. Official venue links are specific to each location where verified. Personal-listing exports retain their provenance; official exports retain IDs/formats/screens. Existing local-storage keys are unchanged.

## Test-only workflows

- `.github/workflows/integrity-review.yml`: both Python test directories, Playwright smoke tests, screenshot artifact. It publishes no listings.
- `.github/workflows/additional-collector-review.yml`: all Python tests, then independent live Vue/Tyneside/Everyman collection jobs; validates each candidate's integration and checks that site files remain unchanged; saves only successful candidates as 14-day artifacts. No credentials are persisted and no deployment is attempted.
- Existing `.github/workflows/collector-review.yml`: unchanged Alnwick-only review collection.

The two new workflows trigger on relevant pushes to `test/alnwick-api-collector` and support manual dispatch. GitHub may only expose manual dispatch after a workflow is on the default branch; the branch push is the initial test trigger. They are **not scheduled**.

## Run checks

```
python -m unittest discover -s tests -v
python -m unittest discover -s additional_tests -v
npm install --prefix /tmp/cinema-ui-tests playwright@1.58.2
/tmp/cinema-ui-tests/node_modules/.bin/playwright install --with-deps chromium
NODE_PATH=/tmp/cinema-ui-tests/node_modules node tests/ui-smoke.cjs
```

## Remaining work

Restore supported GitHub write access, re-read the branch head to avoid overwriting newer work, push the integrated files to the test branch, and review the exact-commit Actions results and fresh candidates. Do not treat cached fixtures as fresh collection. Only then integrate publishing and schedules with accurate failure/freshness handling. Cineworld Newcastle and both ODEON venues remain without validated collectors; their access restrictions have not been bypassed. No paid data service or account setup is included.
