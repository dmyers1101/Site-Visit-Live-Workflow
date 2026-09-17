# Runbook: Drive intake

## Purpose

Create the auditable manifest for the configured Drive folder before any processing.

In the cloud-native workflow this is **Gate 1** of `process-folder`, executed inside the
Cloud Run Job. It runs before a single byte of media is staged, and it writes
`manifest.json` to GCS so the record exists independently of the log.

## Processing boundary

The confirmed boundary is **direct media children**. Folder
`1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF` ("2026-08 Executive - Parth Vaidya") holds 19 direct
media children and **zero** subfolders: 16 `video/quicktime` and 3 `image/heif`. The
three HEIC images are excluded with a recorded reason
(`EXCLUDED_UNSUPPORTED_MIME_TYPE: only video/* sources can be transcribed.`), so a
correct Gate 1 reports 16 supported and 3 excluded.

Gate 1 never recurses. A subfolder would be recorded as an excluded item with its reason,
never traversed. Deepening the boundary is an ADR and a schema change, not a config
tweak.

Exclusion reasons are fixed and always stated:

| Reason | When |
| --- | --- |
| `EXCLUDED_SUBFOLDER` | The child is a folder |
| `EXCLUDED_TRASHED` | The item is in the Drive trash |
| `EXCLUDED_UNSUPPORTED_MIME_TYPE` | Not `video/*` — e.g. the HEIC images |
| `EXCLUDED_NOT_DOWNLOADABLE` | The runtime identity lacks `canDownload` |

## Procedure (cloud-native)

1. Confirm authorization with the deployed read-only preflight; retain the JSON record:

   ```powershell
   gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
     --args=auth-preflight
   ```

   If Drive fails here, complete [Drive access recovery](drive-access-recovery.md) with
   the **service account** — not a personal identity — and the approved folder.

2. List the immediate children and compare against what the folder actually holds:

   ```powershell
   gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
     --args=list-folder-children
   ```

   Expect `immediate_child_count: 19`. Record `drive_id`, `name`, `mime_type`,
   `size_bytes`, `modified_time`, and `web_view_link` from the output.

3. Run Gate 1 by executing the pipeline. There is no separate "make the manifest"
   command — the manifest is always written first, and a dry run stops before Chirp,
   Vertex and Sheets:

   ```powershell
   gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
     --args=process-folder,--dry-run,--limit,1,--run-id,20260917-intake-check
   ```

4. Read the manifest from GCS and confirm the supported/excluded split before a real run:

   ```powershell
   gcloud storage cat gs://shir-sitevisit-staging/site-visit-staging/20260917-intake-check/manifest.json
   ```

   The document carries `processing_boundary: DIRECT_MEDIA_CHILDREN`, `supported_count`,
   `excluded_count`, `mime_type_counts`, and every excluded item with its reason.

## Legacy subfolder procedure (still supported)

The original subfolder-based path remains in the CLI and is correct for a folder that
*does* contain visit subfolders. It is superseded as the normal path.

1. Complete [Drive access recovery](drive-access-recovery.md) and retain redacted access-validation evidence.
2. Run `site-visit list-visits` to list immediate child
   folders only; record their names and IDs.
3. Select exactly one visit folder based on a documented reason (for example, a clear visit naming pattern and supported media).
4. List immediate files in the selected folder. Record `drive_file_id`, `original_file_name`, `mime_type`, `size_bytes`, `modified_time`, and `drive_web_link`.
5. Run the explicit
   `site-visit intake --visit-id VISIT_ID --output manifest.json`
   command. It writes the manifest before staging or processing; select one
   asset from that manifest later.

Against the current folder, `list-visits` correctly returns an empty list — there are no
subfolders — which is why `process-folder` is the right command here.

## Stop conditions

Stop for Drive HTTP 401/403, no supported video, or ambiguous ownership. Stop if the
child count or MIME mix does not match what you expect — a silently different folder is
the failure mode this gate exists to catch. Do not rename, move, delete, or alter Drive
sources. Do not substitute another folder.

Gate 1 also stops the whole run, by design, if the folder contains **no** supported video
children: no manifest is written and nothing is processed.

## How to update this later

Version the manifest schema and retain backwards compatibility for its immutable source
fields. Adding a supported MIME type means extending `SUPPORTED_VIDEO_MIME_PREFIXES` /
`SUPPORTED_VIDEO_MIME_TYPES` in `src/site_visit_workflow/discovery.py` with a test for
both the new inclusion and the exclusion reason it replaces — and updating the expected
counts in this runbook.
