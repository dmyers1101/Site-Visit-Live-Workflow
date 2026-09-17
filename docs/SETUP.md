# Setup guide

## Objective

Prepare the local environment for the Phase 2 single-visit workflow without processing media until Drive access, prompts, and the human approval gate are complete.

## Required access and APIs

- Google Drive API, with access to the approved Shared Folder.
- Cloud Storage API and a dedicated staging bucket/path.
- Speech-to-Text v2 API, including BatchRecognize and the currently supported Chirp configuration.
- Vertex AI API only when the L1 extraction prompt is explicitly wired and approved.
- Google Sheets API for draft catalog rows only.
- The dedicated service-account identity and resource-sharing procedure in [Site Visit workflow service account](RUNBOOKS/service-account-onboarding.md).

## Local prerequisites

- Git and a clean working tree.
- Google Cloud CLI authenticated to the intended project.
- `ffprobe` and `ffmpeg` available on `PATH`.
- A supported local runtime for the eventual workflow implementation.
- A local `.env` copied from `.env.example`; keep it untracked.

## Required environment configuration

Set the project, region, service account identity, GCS staging location, catalog sheet ID, and safe local staging/output locations. Do not commit values that reveal credentials, OAuth tokens, service-account keys, or media contents. Add `DRIVE_SHARED_FOLDER_ID`, `GCS_STAGING_BUCKET`, and a non-secret `CATALOG_SHEET_ID` when the implementation is introduced.

## Access validation (explicit operator action)

1. Confirm the active Git remote and intended branch.
2. Complete [Drive HTTP 403 recovery](RUNBOOKS/drive-access-recovery.md) using the intended account and approved Shared Folder.
3. Call Drive API `files.list` with `supportsAllDrives=true` and `includeItemsFromAllDrives=true` against the folder ID.
4. List only immediate subfolders, select one, and list that folder's immediate media files.
5. Do not proceed if access fails or returns an ambiguous scope.

This repository has not performed a live cloud or Drive access test. The
operator must identify scope, membership, and Shared Drive policy before any
media operation. Do not substitute another folder when validation fails.

## How to update this later

Whenever an API, runtime, environment variable, or validation command changes, update this guide and the related GCP research note in the same pull request.
