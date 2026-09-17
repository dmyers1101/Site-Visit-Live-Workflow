# Runbook: catalog

## Draft catalog schema

| Field | Purpose |
| --- | --- |
| `row_key` | Idempotent key, such as immutable Drive file ID |
| `visit_drive_id` | Selected visit manifest Drive identifier |
| `source_asset_identifier` | Immutable source Drive identifier |
| `original_drive_name` | Original evidence name |
| `drive_link` | Source link |
| `wav_gcs_uri` / `transcript_output_gcs_uri` | Retained transcription artifact locations |
| `transcript_status` | Completed, failed, or `NEEDS_REVIEW` |
| `location` | L1 proposal field |
| `issue_description` | L1 proposal field |
| `suggested_filename` | Proposed only; not a rename command |
| `confidence_note` | L1 uncertainty disclosure |
| `catalog_status` | Always `DRAFT` until explicit publication approval |
| `transcription_started_at` / `transcription_completed_at` | Processing audit timestamps |

## Procedure

Validate the L1 JSON exactly against its approved schema. Upsert one draft row by `row_key`; retain the original Drive name and ID. Set `workflow_status` to review required. Publish or rename only after a human records approval.

## How to update this later

Version the schema before adding fields and retain the idempotency key across migrations.
