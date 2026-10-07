# ADR 0014 — Work-order request flag from the transcript

## Status
Accepted (2026-10-07).

## Context
Walkers say "create work order" or "need a work order" on camera when an item
should become a work order. That intent was in the transcript but nowhere in
the catalog or the report.

## Decision
- After Gate 3, `work_order.detect_work_order_request` runs a deterministic
  phrase match (no model) on the completed transcript: create/need (any tense)
  + optional article + "work order" (also "workorder", "work-order").
- Two catalog columns are APPENDED after `attempt_count`:
  `work_order_requested` = `YES` | `NO` | blank (no transcript, not checked),
  and `work_order_phrase` (the words heard). Blank never means "no".
- `upsert_catalog_row` extends an existing header row to the right, once per
  run, only when the current header is an exact prefix; otherwise it stops.
- The report shows a red **WORK ORDER REQUESTED** marker on the item and an
  At-a-glance count.

## Consequences
- Rows catalogued before this change have blank flags until their clips are
  reprocessed or a transcript backfill is run (not built yet).
- "We already have a work order" is deliberately not flagged; a missed
  phrasing needs a regex addition and a test.
