# Catalog draft-row prompt

**Semantic version:** 1.0.0

## Purpose

Map a validated L1 proposal and transcription record to an unpublished Sheets
draft. The immutable Drive ID is the row key, preventing duplicate rows.

## Expected input JSON/text

```json
{"manifest":"VisitManifest v1.0","l1":"validated L1 JSON","transcription":"TranscriptionRecord"}
```

## Exact prompt text

```text
Create one DRAFT catalog row. Set row_key and source_asset_identifier to the
immutable Drive asset ID. Preserve original_drive_name, drive_link, visit ID,
transcription status, and transcription times. Copy only validated L1 fields.
Do not publish, rename, delete, overwrite source evidence, or invent fields.
```

## Output schema

```json
{"row_key":"Drive ID","source_asset_identifier":"Drive ID","original_drive_name":"string","drive_link":"string|null","visit_drive_id":"string","location":"string","issue_description":"string","suggested_filename":"string","confidence_note":"string","transcription_status":"string","wav_gcs_uri":"gs://...","transcript_output_gcs_uri":"gs://...","transcription_started_at":"RFC3339","transcription_completed_at":"RFC3339|null","catalog_status":"DRAFT"}
```

## Validation rules

- `row_key` equals `source_asset_identifier` exactly.
- The source identifier must exist in the manifest and match L1/transcription.
- Only `DRAFT` is valid until a matching human publication approval exists.

## Safe update and Git rollback

Version schema changes, test idempotent upsert behavior, and update the
catalog runbook before deployment. Use `git revert <commit>` for rollback; do
not change old row keys.

## How to update this later

Add columns only through a documented schema migration that retains Drive-ID
idempotency and human publication gating.
