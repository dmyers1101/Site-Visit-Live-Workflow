# L1 extraction prompt

**Semantic version:** 1.2.0

## Purpose

Produce a strictly bounded proposal from an approved transcript. It is a
payload for an approved model run.

**Changed in 1.1.0 (2026-09-17):** this file previously stated that "the CLI
never invokes Vertex AI or Gemini automatically." That is no longer accurate.
The `process-folder` command invokes Vertex AI directly from the deployed
Cloud Run Job, as authorized for the Phase 2 trial. The prior statement is
preserved here as superseded text rather than removed. The substantive
boundaries are unchanged and are now enforced in code as well as prompt text
(see `docs/decisions/0008-layer-boundaries-enforced-in-code.md`): no layer may
rename a Drive file, create a task or report, publish a catalog row without the
documented upsert path, or derive a finding from an empty transcript.

**Changed in 1.2.0 (2026-09-17):** `location` and `issue_description` are now
explicitly nullable. The governing trial spec defines both as "string or null",
but this file previously required non-empty strings for every value, which
would have failed any clip with no identifiable location. The validator in
`src/site_visit_workflow/models.py` accepts `null` for these two fields; an
empty string is still rejected, so "no location was stated" stays
distinguishable from "the model dropped the field."

## Expected input JSON/text

```json
{"source_asset_identifier":"Drive ID","original_drive_name":"string","transcript_text":"string"}
```

## Exact prompt text

```text
Return JSON only. Use the transcript as evidence. Return exactly these five
keys and no others: source_asset_identifier, location, issue_description,
suggested_filename, confidence_note. Copy source_asset_identifier exactly.
Do not return severity, priority, trade, task, report, diagnosis, or actions.
If the transcript does not state a location, return null for location rather
than guessing or returning an empty string. If it states no issue, return null
for issue_description. suggested_filename and confidence_note are always
required non-empty strings. State uncertainty in confidence_note; do not
fabricate missing facts.
```

## Output schema

```json
{"source_asset_identifier":"string","location":"string|null","issue_description":"string|null","suggested_filename":"string","confidence_note":"string"}
```

## Validation rules

- The key set must match the schema exactly.
- `source_asset_identifier`, `suggested_filename`, and `confidence_note` must be
  non-empty strings.
- `location` and `issue_description` are each either a non-empty string or
  `null`. An empty string is a validation failure, not a substitute for `null`.
- The source identifier must equal the selected manifest asset ID.
- A valid result remains a proposal and cannot rename Drive or publish Sheets.

## Safe update and Git rollback

Version this file, update its validator and tests first, and obtain prompt
governance approval before any external execution. Use `git revert <commit>`
to roll back; preserve previous versioned prompt payloads as audit evidence.

## How to update this later

Do not expand the allowed keys without an ADR, catalog schema migration, and
new negative validation tests.
