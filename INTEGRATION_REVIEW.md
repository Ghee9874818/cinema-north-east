# Cinema North East integration review

18 October 2026. The integrated collectors and feed/UI safeguards pass 82 unit tests. Actual GitHub Actions browser smoke passed on commits cb251b2 and 97ccf9a, covering direct booking links, notes, filters, mobile width, export metadata and unavailable states. The final proposed-feed browser gate additionally checks all seven venues against the published data.

## Fresh publication candidate

217 programme records collected by GitHub Actions at about 15:38 UTC: Alnwick Playhouse 19, Tyneside Cinema 104, Everyman Newcastle 94. Coverage is 18–24 October. Each venue retains its collection timestamp, source evidence and booking URLs. These are programme records, not seat availability or complete regional coverage.

Vue failed with HTTP 403 at its official anonymous-session endpoint. No access restriction was bypassed. Vue, Cineworld Newcastle and both ODEON venues remain available as official links with unavailable collection status. Morning cached candidates are test fixtures only and are not published.

## Integrity controls

Feed validation retains notes, formats, screens and IDs; rejects conflicting IDs, malformed dates/times and unofficial booking hosts. Everyman rejects date-only timestamps and conflicting movie metadata IDs. Official booking hosts are scoped to their cinema. Atomic single-venue replacement preserves other venues; stale, future-dated, regressing, empty and out-of-coverage candidates fail. Failed attempts can preserve last-good rows with explicit unavailable status.

## Test workflows

The additional-collector, Alnwick and interface workflows are review-only and cannot publish listings. They trigger on relevant test-branch pushes or manual dispatch. Vue failure makes the collection matrix red even when the other venues succeed; it is never relabelled as a successful empty programme.

The daily refresh pipeline is configured for 08:17 Europe/London, using validated fresh candidates, last-good preservation, explicit Pages deployment and public-byte verification. The first unscheduled end-to-end run 39142591901 passed all gates.

## Checks

python -m unittest discover -s tests -v

python -m unittest discover -s additional_tests -v

Playwright smoke: tests/ui-smoke.cjs (dependencies installed by the integrity workflow).
