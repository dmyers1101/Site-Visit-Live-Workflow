# Runbook: Drive intake

## Purpose

Create the auditable manifest for one selected visit subfolder before any processing.

## Procedure

1. Complete [Drive access recovery](drive-access-recovery.md) and retain redacted access-validation evidence.
2. Run `python -m site_visit_workflow.cli list-visits` to list immediate child
   folders only; record their names and IDs.
3. Select exactly one visit folder based on a documented reason (for example, a clear visit naming pattern and supported media).
4. List immediate files in the selected folder. Record `drive_file_id`, `original_file_name`, `mime_type`, `size_bytes`, `modified_time`, and `drive_web_link`.
5. Run the explicit
   `python -m site_visit_workflow.cli intake --visit-id VISIT_ID --output manifest.json`
   command. It writes the manifest before staging or processing; select one
   asset from that manifest later.

## Stop conditions

Stop for Drive HTTP 401/403, no clear visit subfolder, no supported video, or ambiguous ownership. Do not rename, move, delete, or alter Drive sources.

## How to update this later

Version the manifest schema and retain backwards compatibility for its immutable source fields.
