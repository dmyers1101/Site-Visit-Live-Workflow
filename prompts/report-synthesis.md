# Report synthesis prompt — PLACEHOLDER

**Semantic version:** 0.1.0
**Status:** **PLACEHOLDER.** Deliberately simple. Written to prove the Google
Docs leg of the pipeline works end to end, not to produce a report anyone would
send to an owner. Expect to replace it wholesale.

## Purpose

Turn one run's validated catalogue records into a short executive narrative that
is written into a Google Doc. It is the last gate in the pipeline and the only
one that produces prose rather than structured data.

## Why this is a placeholder

The L1/L2/L3 prompts were derived from three logged pilot runs and real
vocabulary counts. This one has no such lineage — no prior report prompt exists
in `pilot/`, and no one has specified what the executive report should contain.
It is a scaffold so the wiring can be tested. The real version needs:

- a defined audience and length,
- a house format agreed with whoever consumes it,
- a decision on whether it groups by trade, by severity, or by building area,
- a rule for how `NEEDS_REVIEW` assets are surfaced rather than silently dropped.

## Source/reference lineage

None. Written 2026-09-18 for the first end-to-end run. `[ASSUMED]` throughout.

## Expected input JSON/text

```json
{"run_id":"string","folder_name":"string","generated_at":"ISO-8601",
 "counts":{"total":0,"catalogued":0,"needs_review":0,"failed":0},
 "by_trade":{"trade":0},"by_severity":{"1":0},
 "findings":[{"original_drive_name":"string","new_drive_name":"string or null",
   "location":"string or null","issue_description":"string or null",
   "trade":"string or null","severity":"1-4 or null",
   "recommended_action":"string or null","status":"string"}]}
```

## Exact prompt text

```text
You are writing a short internal summary of one property site visit for a
property manager. Use only the findings supplied. Write plain prose. Do not
use markdown, headings, bullets, or code fences.

Structure it as:
A one-paragraph overview stating how many clips were reviewed, how many
produced findings, and how many need human review.
Then a paragraph on the most urgent items, defined as severity 1 and 2,
naming the location and the issue for each.
Then a short paragraph on routine items, severity 3 and 4, summarised rather
than listed one by one.
Then a closing paragraph naming anything that could not be assessed and why.

Rules you must follow:
Do not invent a finding, a location, a cost, a date, a vendor, or a person.
Do not assign work to anyone or state who is responsible, because that was not
determined.
Do not state a deadline or an urgency window, because that was not determined.
If a clip produced no transcript or failed validation, say so plainly rather
than omitting it.
Refer to items by their location and issue, not by file name or Drive ID.
Keep the whole thing under 500 words.
```

## Expected output

Plain UTF-8 text. No schema, no JSON, no validation beyond a non-empty check —
this is narrative output and is not machine-consumed.

## Validation rules

- Response must be non-empty after stripping whitespace.
- Response must not begin with a code fence.
- No structural validation. A weak report is acceptable at 0.1.0; a wrong
  structured record is not, which is why the earlier layers are strict and this
  one is not.

## Known limitations / uncertainty behavior

- The model may still produce headings or bullets despite the instruction. That
  is tolerated at this version.
- Severity grouping assumes the L2 integer scale (1 urgent/safety … 4 low).
- Assets with `NEEDS_REVIEW` carry no L2 fields, so they can only be named as
  unassessed.
- The report is written into the Doc by insertion. Running the report twice
  against the same Doc appends a second report rather than replacing the first,
  because nothing in this system deletes. That is intentional, and it means the
  Doc is an append-only log of report runs.

## Safe update and Git rollback

Version this file and update `src/site_visit_workflow/report.py` in the same
change. Use `git revert <commit>` to roll back and select the prior version
explicitly; preserve previous versioned prompt payloads as audit evidence.

## How to update this later

Replace this placeholder once the report's audience and format are agreed. When
you do, bump to 1.0.0, record the lineage of the decision, and add real
validation. Until then, treat any report it produces as a wiring test, not as a
deliverable.
