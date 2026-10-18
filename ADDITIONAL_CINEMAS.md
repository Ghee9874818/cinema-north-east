# Historical additional collector development record

The source validations below were recorded during original development on 18 October 2026. They are retained as technical provenance, not a fresh collection. See INTEGRATION_REVIEW.md for current integration tests and workflow status.

# Additional cinema collector development — 18 October 2026

The live site, all seven venue entries and the existing Alnwick daily workflow are unchanged. No new daily jobs, GitHub writes or deployments were performed during this phase.

## Tested review collectors

| Venue | Captured performances, 18–24 October | Source | Status |
| --- | ---: | --- | --- |
| Vue Cramlington | 231 | Public website showings service, cinema ID 10085 | Local live run passed; anonymous visitor session required |
| Tyneside Cinema | 104 | Official public Spektrix events and instances feed, client tynesidecinema | Local live run passed |
| Everyman Newcastle | 101 | Public website schedule and movie-title services, theater X11KB | Local live run passed |
| Cineworld Newcastle | — | Official Newcastle page identifies theater X06TH and website schedule service | Direct schedule request returned HTTP 403; not connected |
| ODEON Silverlink | — | Official page /cinemas/silverlink/ and Vista service | Page fetch returned 403; unauthenticated site API returned 401; not connected |
| ODEON Metrocentre | — | Official page /cinemas/metrocentre/ and same Vista service | Same access blocker; not connected |

Counts include earlier performances on the collection date. They are programme records, not a claim of current availability, completeness or future uptime. No feed was replaced.

## Implementation

collect_additional.py has independent Vue, Tyneside and Everyman adapters. It uses curl (required on the runner) and Python 3.12 standard-library parsing. Vue follows its own public anonymous visitor session flow; cookies stay in a temporary directory and are never included in results, fixtures or logs. No account login or private API key is used. Vue and Everyman's website endpoints are undocumented and may change without notice; this is not a confirmed partner-feed arrangement.

The default coverage is seven local dates in Europe/London. Exact timestamps, provider performance identifiers, booking hosts and venue identifiers are checked. Tyneside local/UTC timestamps and Vue explicit timezone offsets must agree. Failed requests, malformed responses, missing title joins and conflicting duplicate bookings fail collection before an atomic review candidate is written. Existing candidates remain intact on failure. Output named screenings.json is refused. There is no publication or automatic approval step.

Tyneside screen names are absent from the tested feed. Outputs explicitly say screen not supplied rather than guessing from a seating-plan ID. Captioned, subtitled, relaxed and other explicit session flags are retained. Non-screening event classifications cause failure for review rather than silent exclusion. Everyman captioning, Baby Club, Silver Screen, Kids friendly, Throwback and format tags are carried through; unfamiliar screening tags require review. Internal occupancy tags are not treated as ticket availability.

## Validation

13 new tests pass, alongside all 24 existing Alnwick tests (37 total). New cases cover wrong venues, missing film titles, timezone mismatches, incomplete Vue day sets, cancellation flags, booking-ID mismatches and preservation of existing files after failure. Raw public-source fixtures are in additional_tests/fixtures. No anonymous cookie or token response is included.

Live end-to-end local runs passed for all three implemented adapters. Everyman was rerun successfully after adding readable special-screening notes. In the official rendered Everyman seven-day page, all 97 active booking links matched captured records; four earlier performances remained in the API capture. In Vue's official rendered Cramlington page, all 35 displayed booking links for 18 October matched captured records. The remaining six days are API-validated, not individually browser-checked. Tyneside's official Arrietty page matched 18 October 13:15 (booking 1874601) and 19 October 11:40 (1874801), including subtitle flags; its earlier 10:30 relaxed screening remained in the API but was no longer in the active booking list. Tyneside's numeric booking URL format was separately verified against the official Spektrix iframe.

These are initial source validations, not six production connections. The new collectors have not run in GitHub Actions and have not been scheduled. Cineworld and ODEON need a supported access route or official feed before implementation can be validated; no security challenges were bypassed.

## Run

```sh
python3 -m unittest discover -s additional_tests -v
python3 -m unittest discover -s tests -v
python3 collect_additional.py vue --output work/vue-candidate.json
python3 collect_additional.py tyneside --output work/tyneside-candidate.json
python3 collect_additional.py everyman --output work/everyman-candidate.json
```

Next: run the three adapters in an isolated, manual review workflow and compare repeated captures before enabling any additional daily schedules. Pursue documented/venue-supported data access for Cineworld and both ODEON sites. Review fresh exact-commit test results and candidate data before publication.
