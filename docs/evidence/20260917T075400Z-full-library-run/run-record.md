# Full-library run — 20260917T075400Z

**Run ID:** `20260917T075400Z`
**Execution:** `site-visit-workflow-jpsjp`
**Image:** `…/site-visit:pipeline-r4`
**Identity:** `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`
**Command:** `site-visit process-folder` (no limit — the whole library)
**Duration:** ~11 minutes for 16 videos, sequential

## Result

| Outcome | Count |
| --- | --- |
| CATALOGUED | 14 |
| NEEDS_REVIEW | 2 |
| FAILED | **0** |
| Catalog upserts | 16, all `UPDATED` |

Every one of the 16 upserts was an **UPDATE**, not an append. The Sheet holds
exactly 16 rows — one per video — after four separate runs. The idempotent row
key (immutable Drive asset ID) works.

Artifacts for this run occupy ~41.6 MB in
`gs://shir-sitevisit-staging/site-visit-staging/20260917T075400Z/`.

## The two NEEDS_REVIEW assets

**`IMG_3662.MOV` — empty transcript.** Chirp returned nothing on attempt 0 and
again on attempt 1. The pipeline stopped that asset's extraction path, wrote the
row with no findings, and marked it NEEDS_REVIEW. This is the designed
behaviour: it did not invent a finding from silence, which is exactly the
failure mode the pilot exhibited.

**`IMG_3667.MOV` — L3 traceability check fired.**
`L3 prior_layer_record_id does not match the validated L2 record.` The model
returned a record id that did not match the L2 record it was given. The
validator rejected it rather than accepting a broken provenance chain. L1 and
L2 for this asset are valid and are in the Sheet; only L3 is absent.

Neither is a pipeline defect. Both are the guardrails doing their job, and both
are recorded rather than silently swallowed.

## What changed since the previous full run

The previous full run (`20260917T073809Z`) had 9 of 16 assets fail with
`429 Resource has been exhausted` while polling Speech-to-Text operations —
running the library twice inside ~20 minutes exceeded the project's Chirp quota.
The poll loop now backs off (15s doubling to 120s) and keeps polling, because a
429 on the poll is a transient quota condition, not a failed transcription. This
run had zero quota failures.

The L3 prompt was also bumped to 1.2.0 to state the status/field coupling rule
as all-or-nothing, after 2 assets in run `20260917T072151Z` were rejected for
keeping a single confident field alongside `INSUFFICIENT_EVIDENCE`. Both of
those assets catalogued cleanly afterwards.

## Sample of what landed in the catalogue

Real extractions from real walkthrough audio, all `catalog_status: DRAFT` and
`drive_rename_decision: PROPOSED_ONLY_AWAITING_HUMAN_APPROVAL`:

| Video | Location | Issue | Trade | Sev |
| --- | --- | --- | --- | --- |
| IMG_3651 | outside unit 2107 | water dripping from siding, potential leak | plumbing | 2 |
| IMG_3657 | floor 3 utility closet, 2306 | unsecured utility closet | safety | 1 |
| IMG_3668 | roof | widespread damage across ≥50% of roof | structural | 1 |
| IMG_3652 | unit 1129 | threshold coming off, safety hazard | general-maintenance | 1 |
| IMG_3664 | roof | ponding, TPO membrane degrading | structural | 2 |
| IMG_3650 | outdoor amenity area | grills unclean, dog waste, no bags | cleaning | 3 |

L3 returned `INSUFFICIENT_EVIDENCE` on most assets and left
`responsible_party` and `urgency_window` null, because a walkthrough narration
rarely states who should fix something or by when. That is the correct,
conservative outcome — the pilot fabricated both in the same situation.

## How to update this later

Create a new dated directory per run; never overwrite this one. Do not re-run
the full library twice within about 30 minutes without checking Speech quota.
