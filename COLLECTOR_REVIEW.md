# Historical Alnwick development record

This document records the original collector development phase. Statements about unchanged files, test totals, workflow availability and publication approval describe that phase only. See INTEGRATION_REVIEW.md for the current integrated package and verification status.

# Alnwick collector development review — 18 October 2026

## Update: official public API found and tested

On 18 October 2026, the official booking page iframe identified Alnwick's Spektrix client as `alnwickplayhouse`. The public API at https://system.spektrix.com/alnwickplayhouse/api/v3 responds to ordinary automated requests without credentials. The earlier HTML-page blocker remains, but the official API provides a working alternative.

The new preferred collector is `collect_spektrix.py`. A live end-to-end run retrieved 19 performances for 18–24 October 2026. Every title, date, time, screen/access note and booking identifier matched the 19 records observed on the official Cinema programme. The test suite now has 24 passing cases. Tests use raw public API response fixtures as well as the reduced HTML fixture. No credentials, response cookies or customer data are included.

The local manual-only workflow now uses the API collector. It has not been uploaded to GitHub or run on a GitHub-hosted runner. No schedules, deployments or publishing have been enabled. index.html, screenings.json and build_feed.py remain byte-for-byte unchanged.

### Exact source queries tested

- Events: https://system.spektrix.com/alnwickplayhouse/api/v3/events?instanceStart_from=2026-10-18&instanceStart_to=2026-10-25&attribute_Type=Film&attribute_SendToWebsite=1
- Performances: https://system.spektrix.com/alnwickplayhouse/api/v3/instances?startFrom=2026-10-18&startTo=2026-10-25&eventattribute_Type=Film&eventattribute_SendToWebsite=1

Both returned HTTP 200 JSON. The film filter includes cinema broadcasts such as Hadestown and ballet because the venue marks them as Film. It excludes live theatre and classes. The collector also checks these attributes locally instead of assuming server-side filters worked.

The two arrays join by event ID. Individual instances provide `start`, `startUtc`, `cancelled`, `attribute_Info` and booking IDs. The `/instances` endpoint emits its explicitly UTC field without a trailing Z, while the event-specific instances endpoint includes Z; both forms are handled and compared against Europe/London. No dates are guessed. Cancelled performances are excluded. `isOnSale` is not interpreted as seat availability and an off-sale performance is not silently dropped.

Failures, empty feeds, inconsistent IDs, missing performance groups, invalid times, unexpected response types and redirects leave existing candidates untouched. Candidates remain labelled needs_review and the collector refuses output named screenings.json. This code does not merge with other venues or publish anything.

### Recommended next step

Use this public API rather than the HTML scraper. First trial the manual review workflow from the intended runner, then compare collection results across multiple days. After review, a future approved change can schedule cached collection and add freshness/failure handling to the live site, preserving all seven cinemas and their data. Daily collection is a reasonable initial proposal, not an enabled schedule. API responses are a snapshot; changes between the two requests or silently incomplete upstream data are still possible. Current guards detect some inconsistencies but cannot guarantee source completeness.

Public read access needs no API key according to [Spektrix's filtering documentation](https://integrate.spektrix.com/docs/apieventfiltering). [Spektrix's API mode guide](https://integrate.spektrix.com/docs/api/choosing-an-api-mode) describes Web mode as the public listings route. Its caution about server-side calls links to customer record operations; this collector only reads public event/instance data. Successful local access does not guarantee access from GitHub Actions or long-term uptime. The live site's final wording and publication process still require user review.

### Run the preferred collector

```sh
python3 -m unittest discover -s tests -v
python3 collect_spektrix.py --output work/alnwick-api-candidate.json
```

The default coverage is seven days, up to 31 days can be explicitly requested. Only the default seven-day window has been live-tested. The code and raw fixtures are in this package; the separate local live review candidate is not an approved production feed.

---

The original HTML-collector assessment below is retained as development history. Its unresolved feed-access conclusion is superseded by the API findings above.

This package is based on repository main at af2bebd (downloaded from GitHub on 18 October 2026). No repository writes, live feed replacements, deployments, or scheduled jobs were performed.

## Completed

Replaced the diagnostic-only update.py with a Python 3.12 standard-library collector for the official Cinema page's seven-day movie-card programme. It associates each title with explicit data-date values, movie-time-start values, screen/subtitle notes and the individual Spektrix booking URL. It does not infer dates from relative text, parse running time as a showtime, or expand date ranges.

Every film card must contain the current seven dates in order. Missing titles, start times, booking IDs, unexpected booking hosts, conflicting performance IDs, truncated HTML, stale dates and empty programmes fail collection. Dates are interpreted in Europe/London; times remain the venue's local wall-clock times.

Successful collection writes an atomic review candidate with source hash, collection timestamp, coverage dates and status needs_review. The default output is work/alnwick-candidate.json. Output named screenings.json is refused. There is no publishing or feed-merge step.

Added a manual-only GitHub Actions workflow that runs tests, attempts collection, and uploads a review artifact on success. It has contents: read, no schedule, no commit step and no Pages deployment. The workflow has not been installed or run on GitHub.

## Validation and limits

12 local unittest cases pass, including comparisons with 19 records transcribed from the current browser DOM across seven movie cards, duplicate handling, malformed records, stale dates, daylight-saving and year boundaries, and preservation of files after failure.

The HTML fixture is a reduced reconstruction of the observed DOM, not a raw HTTP capture. It retains the relevant classes, nested label spans, dates, booking identifiers and notes; posters, icons and surrounding navigation are omitted. tests/fixtures/expected.json records the captured values. This proves parsing against the observed structure, not a successful unattended live collection. The DST test exercises local date boundaries; it does not validate the host's clock or a real scheduled run.

Direct HTTP requests to the official source return HTTP 307 to /csq/ with x-redirect-reason: no-token. The live collector test failed safely with 'Source redirected to an access challenge'. A normal browser loaded the programme. No access challenge was bypassed. Resolve unattended access through an official feed or supported access arrangement before enabling automatic updates. Browser-rendered content may also differ from the raw server response; test an actual successful HTTP capture before claiming production readiness.

Coverage is deliberately limited to the seven-day programme displayed on the Cinema page. Later 'Upcoming screenings' cards are date ranges and are not expanded. No whole-programme completeness claim is made. The parser cannot detect a wholly missing film card without independent source counts. Production work needs successful live runs over multiple days, comparison against the official programme, drift checks, and an approved publication process that preserves other cinemas' data.

## Preserved files

index.html, screenings.json, build_feed.py, README.md and DATA_STATUS.md are byte-for-byte copies of the inspected repository. All seven cinema entries remain intact. No other cinema's data was removed or replaced. The current live site still uses the dated snapshot.

## Run locally

From this directory with Python 3.12 or later:

```sh
python3 -m unittest discover -s tests -v
python3 update.py --html tests/fixtures/alnwick-2026-10-18.html --today 2026-10-18 --output work/example-candidate.json
python3 update.py --output work/alnwick-candidate.json
```

The last command currently fails at the source access challenge. Failure leaves existing candidates and the live feed untouched. Do not run build_feed.py against a candidate and deploy it without reviewing both the listings and the intended live-site changes with the user. The site's current display also needs a separate approved update before claiming live verified data or using per-performance booking links.
