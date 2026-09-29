# ADR 0009 — Portfolio boundary: every visit folder under the master folder

## Status
Accepted (2026-09-29). Extends, does not supersede, ADR 0002 (single folder,
immutable source): each visit folder is still processed with the
`DIRECT_MEDIA_CHILDREN` boundary.

## Context
The pipeline was proven on one visit folder. Production needs every visit under
the master folder `1UkjYIHnSs-igeOy9k-Iw_d1-bEnH-mwN`. The tree is not uniformly
deep (observed 2026-09-29):

- `Master / State / Property / Visit` — e.g. `TX / Alma / 2026-08 Executive - Parth Vaidya`
- `Master / State / Property / Group / Visit` — e.g. `PA / Legacy / Oakland / …`

## Decision
- A **visit folder** is any folder with at least one direct video child, found by
  a recursive, read-only walk (`portfolio.walk_portfolio`, max depth 6).
- Path segment 1 is **State**, segment 2 is **Property**, anything between Property
  and the visit is **property_group**.
- `process-portfolio` reuses `cmd_process_folder` per visit (one implementation of
  Gates 1–6), passing: a skip list, a clip budget, and per-clip portfolio columns.
- **Incremental rule:** skip a clip whose master-Sheet row is `CATALOGUED` or
  `NEEDS_REVIEW`; retry `FAILED` until `attempt_count` reaches 3
  (`portfolio.select_pending`). NEEDS_REVIEW is the human queue and is never
  auto-retried, so quota is not re-spent on the same silent clip nightly.
- Clip budget `--max-clips` (nightly: 60) caps one execution; leftovers roll to
  the next run.

## Consequences
- A new property or visit needs no config: create the folder, upload clips.
- A folder convention change (new level above State) means changing
  `portfolio.split_path` + `tests/test_portfolio.py` and a new ADR.
- Reprocessing a NEEDS_REVIEW clip is a manual action: clear its row's
  `asset_status` in the master Sheet (or run `process-folder --asset-id`).
