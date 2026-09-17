# L1 extraction prompt

**Semantic version:** 1.0.0

## Purpose

Produce a strictly bounded proposal from an approved transcript. It is a
payload for an explicitly approved external model run; the CLI never invokes
Vertex AI or Gemini automatically.

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
State uncertainty in confidence_note; do not fabricate missing facts.
```

## Output schema

```json
{"source_asset_identifier":"string","location":"string","issue_description":"string","suggested_filename":"string","confidence_note":"string"}
```

## Validation rules

- The key set must match the schema exactly; every value is a non-empty string.
- The source identifier must equal the selected manifest asset ID.
- A valid result remains a proposal and cannot rename Drive or publish Sheets.

## Safe update and Git rollback

Version this file, update its validator and tests first, and obtain prompt
governance approval before any external execution. Use `git revert <commit>`
to roll back; preserve previous versioned prompt payloads as audit evidence.

## How to update this later

Do not expand the allowed keys without an ADR, catalog schema migration, and
new negative validation tests.
