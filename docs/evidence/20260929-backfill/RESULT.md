# Portfolio backfill + nightly go-live — 2026-09-29

**Status: COMPLETE.** Every clip under the master folder has a row in the master Sheet;
the nightly trigger is ENABLED (first scheduled run 2026-09-30 06:00 UTC / 02:00 ET).

## Batches
| # | Execution | Image | Result |
| --- | --- | --- | --- |
| 1 | `site-visit-workflow-l7hvq` (36m) | `portfolio-20260929d` | Venue/Laura 38, Alma/Catalina 22 processed; reports written. **Alta visit FAILED**: >100 children rejected by the single-visit listing → fixed (pagination). |
| 2 | `site-visit-nightly-6nvhm` | `portfolio-20260929e` | 46 clips processed (Alta 45 + …), then **container crashed**: `BrokenPipeError` in the report due-check Sheet read (outside any handler) → fixed (inside try; `execute(num_retries=5)`). Rows were kept. |
| 3 | `site-visit-nightly-w4lqk` (37m) | `portfolio-20260929f` | Alma/Catalina 21, Hedge 38, Alta retry 1 (FAILED); reports written incl. Alta self-heal. |
| 4 | `site-visit-nightly-gg9h6` (25m) | `portfolio-20260929g` | Hedge 13, Veer 24; IMG_8054 3rd failure, now with the real ffmpeg error. |
| fix | `site-visit-nightly-dddn9` (4m) | `portfolio-20260929h` | `--visit-id <Alta> --retry-failed`: IMG_8054 CATALOGUED (not renamed: L1 had no finding). |

**IMG_8054.MOV root cause:** iPhone file with a codec-less (spatial) audio stream; ffmpeg's
automatic stream choice picked it ("no decoder found for: none"). Fix: `media.select_audio_stream`
+ explicit `-map 0:<index>`. ffmpeg errors now keep the stderr tail.

## Invariants
| Invariant | Result | Numbers |
| --- | --- | --- |
| I1 coverage | PASS | walk = 7 visits / 5 properties / 224 clips; 9 empty visit folders cross-checked with operator Drive access |
| I2 row count, no dupes | PASS | master Sheet 224 rows = 224 clips (row key = Drive ID) |
| I3 idempotency | PASS | scheduler-fired run `site-visit-nightly-ws2rr`: processed 0, reports 0 |
| I4 no delete | PASS | no delete/trash/clear/deleteTab call exists; SA has no delete permission |
| I5 rename gate | PASS | NEEDS_REVIEW and no-finding clips not renamed (e.g. IMG_8054) |
| I6 uploader ≠ SA | PASS | uploaders: pvaidya, paregional, lbeynon, cmorini |
| I7 no blank-means-something | PASS | empty transcripts → NEEDS_REVIEW (not "no issue") |
| I8 report counts = Sheet | PASS | code-written counts line, e.g. Alma/Parth 14 + 2 = 16 |
| I9 migration 16→16 | PASS | source Sheet untouched |
| I10 budget | PASS | each batch ≤ 60 clips |

Final state: 210 CATALOGUED, 14 NEEDS_REVIEW (human queue), 0 FAILED.

## Outputs
- Master Sheet `1oFq1rzag23706HYXSGoBseuLj5ouFyQ0BHuIAaLtj-o` (`Catalog`, `Reports`).
- Report Docs: Alma (`1PRnJhG1…`, 2 tabs), Venue (`12jxtI37…`, 2 tabs), Alta, Hedge 1 & 2, Veer (1 tab each).
- Scheduler `site-visit-nightly-trigger` ENABLED; manual test fired `site-visit-nightly-ws2rr`.

## Open items
- Uploader names are Drive account names (`cmorini`, `paregional`), not full names (ADR 0011).
- Three Venue rows still say `RENAMED_TO:…` for clips restored to `IMG_` names (see 20260929-portfolio-venue).
- Speech/Vertex throughput: ~35 min per 60 clips; nightly cap 60 is ample for normal upload volume.
