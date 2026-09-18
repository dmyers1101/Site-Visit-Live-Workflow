# Changelog

All notable changes to the live workflow are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries are additive. Corrections are added as new dated entries; history in
this file is not rewritten.

## [Unreleased]

Run of 2026-09-18: Gate 6 (approval-gated Drive rename) and Gate 7 (Google Docs
report) added, and the run's output files become self-provisioned. Operator
authorization: rename the Drive source videos in this run; create the Sheet and
the Doc in the Shared Drive folder; **no deletions, anywhere, ever**.

### Added

- **`src/site_visit_workflow/rename.py` — Gate 6.** `build_new_name` sanitizes a
  model-suggested filename while preserving the ORIGINAL file's extension and
  its case; `execute_rename` renames only a CATALOGUED asset with a validated
  L1 record, and only when BOTH `RENAME_APPROVED` and `--rename-approved` are
  present. It reuses the existing `DriveGateway.rename`; no second Drive rename
  path exists. Per-asset outcome is recorded as `RENAMED`,
  `SKIPPED_NOT_APPROVED`, `SKIPPED_NO_SUGGESTION`,
  `SKIPPED_ASSET_NOT_ELIGIBLE`, `SKIPPED_DRY_RUN` or `FAILED`.
- **`src/site_visit_workflow/report.py` — Gate 7.** Builds a compact JSON
  summary from the run's in-memory catalogue rows (never re-reading the Sheet),
  calls Vertex once with `prompts/report-synthesis.md` read at runtime from
  `--prompts-dir`, and inserts the plain-text narrative into a Google Doc with a
  single `insertText` at index 1. No `response_schema`; no delete request of any
  kind, so the Doc is an append-only log of report runs.
- **Self-provisioned output files.** `google.ensure_catalog_spreadsheet` and
  `google.ensure_report_document` reuse a configured ID or create the file in
  `DRIVE_OUTPUT_PARENT_ID` via Drive `files.create` with `supportsAllDrives`.
  Both IDs are resolved once, before the asset loop, emitted immediately as a
  `"gate": "outputs"` log line, and repeated in the run summary - so a later
  failure still leaves the created files discoverable.
- **New settings:** `REPORT_DOC_ID`, `DRIVE_OUTPUT_PARENT_ID` (defaults to
  `DRIVE_SHARED_FOLDER_ID`), `RENAME_APPROVED`.
- **New `process-folder` flags:** `--rename-approved`, `--report`,
  `--report-doc-id`, `--catalog-sheet-id`.
- **Tests:** `tests/test_rename.py` and `tests/test_report.py` (50 new tests,
  none of which contacts a Google API), covering extension preservation
  including uppercase `.MOV`, sanitization, unusable suggestions, over-long
  stems, the eligibility and double-approval rules, and the catalogue row key
  being unaffected by a rename.

### Changed

- **`CATALOG_SHEET_ID` is no longer required by `process-folder`.** The sheet ID
  is now an OUTPUT of that command when it is not supplied. The required-set
  check was not dropped but replaced: `config.assert_output_targets_resolvable`
  fails the run before any asset is processed unless either an explicit ID or a
  creatable Drive parent exists, for the Sheet and (when `--report` is given)
  the Doc. `CATALOG_SHEET_ID` remains required for `publish-catalog`.
- **The per-asset `drive_rename` record is the ACTUAL outcome.** It was a
  hardcoded `"NOT_ATTEMPTED; suggested names are proposals only."` string that
  was archived to GCS as evidence; it now carries the real Gate 6 record. The
  catalogue's `drive_rename_decision` column likewise carries
  `RENAMED_TO:<name>` or the real skip reason, and keeps the historical
  proposal wording only when no approval was given. `original_drive_name`
  always remains the DISCOVERY-time name.
- **The `process-folder` boundary comment corrected.** "Creates nothing,
  renames nothing, deletes nothing" was two-thirds false as of this change. The
  one clause that never changes - **deletes nothing, anywhere** - now stands on
  its own, and the two clauses that became untrue are corrected in place rather
  than removed.


## [Unreleased] — earlier: overnight orchestrated run of 2026-09-17

Overnight orchestrated run of 2026-09-17, continuing preflight run
`20260917T055321Z-phase2-auth-preflight`. Operator authorization: create the
Google Sheet; edits permitted; **no deletions**.

### Added

- **`docs/RUNBOOKS/full-pipeline.md`** — end-to-end `process-folder` runbook:
  the five gates, the cheap-trial ladder, what to check after a run, and a
  failure-handling table.

### Changed

- **Operator documentation rewritten for the cloud-native workflow.**
  `README.md`, `docs/SETUP.md`, `docs/DEPLOYMENT.md`, `docs/OPERATIONS.md`,
  `docs/AUTH.md`, `docs/ARCHITECTURE.md` and the Drive-intake, transcription
  and catalog runbooks now describe the deployed Cloud Run Job path (Drive ->
  container -> GCS, media never on a workstation), carry the real project,
  folder, bucket, Sheet, model and region values, document the deployer vs
  runtime identity split, and state the no-delete constraint and its
  operational consequences. Superseded wording is marked in place rather than
  removed.
- **`docs/DEPLOYMENT.md` Cloud Run sizing.** The documented configuration moves
  from 1Gi / 600s to `--memory=8Gi --cpu=2 --task-timeout=3600s`: `/tmp` is an
  in-memory tmpfs that counts against `--memory`, and the never-cleaned work
  directory accumulates every staged source and WAV for the life of the
  execution, so the old sizing would OOM or time out on a 16-video run.

### Known gaps

- **[OPEN] `infra/Dockerfile` does not copy `prompts/` into the image**, and the
  prompt files are not declared as package data. `process-folder` reads
  `prompts/l1-extraction.md`, `l2-enrichment.md` and `l3-refinement.md` at
  runtime and treats a missing file as a hard stop, so Gate 4 will fail on
  every asset until `COPY prompts ./prompts` is added and the image is rebuilt.
  Gates 1-3 and `--dry-run` runs are unaffected. Recorded in
  `docs/DEPLOYMENT.md` and `docs/RUNBOOKS/full-pipeline.md`.

- **Phase 2 authorization preflight evidence** under
  `docs/evidence/20260917T055321Z-phase2-auth-preflight/` — authorization
  matrix, command ledger, go/no-go, source map, and raw outputs. Overall
  result **PARTIAL**. All live API checks originated from the deployed Cloud
  Run Job with the service account attached directly: no key file, no
  impersonation, no personal Drive OAuth.
- **GCS staging bucket `gs://shir-sitevisit-staging`** — US multi-region,
  uniform bucket-level access. The runtime service account holds
  `objectCreator` + `objectViewer` + `legacyBucketReader` and deliberately
  **no delete permission**.
- **Catalog Google Sheet** "Site Visit Catalog — Live Workflow", ID
  `158eA2K5FgGc4dQ43xHxdTuri-KOwPSuNn8qQqsasBy0`, tab `Catalog`. Created in the
  operator's Drive by `dmyers@shircapital.com` and shared to
  `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` as writer.
- **L2 and L3 prompts** — `prompts/l2-enrichment.md` and
  `prompts/l3-refinement.md`, versioned and derived from the logged pilot runs.
  These closed preflight blockers 2 and 3.
- **Cloud-native media pipeline** — Drive → Cloud Run container (ephemeral) →
  GCS. Media is never downloaded to an operator workstation. Speech-to-Text v2
  cannot read from Drive, so the cloud-side hop is mandatory.
- **ADR 0004** — cloud-native media path (`docs/decisions/0004-cloud-native-media-path.md`).
- **ADR 0005** — dedicated staging bucket the workflow cannot delete from
  (`docs/decisions/0005-staging-bucket-without-delete.md`).
- **ADR 0006** — Chirp recognizer location separate from the Cloud Run region
  (`docs/decisions/0006-speech-location-separate-from-run-region.md`).
- **ADR 0007** — catalog Sheet ownership and location
  (`docs/decisions/0007-catalog-sheet-ownership-and-location.md`).
- **ADR 0008** — L2/L3 layer boundaries enforced in code, not prompt text
  (`docs/decisions/0008-layer-boundaries-enforced-in-code.md`).
- **`docs/research/gcp/vertex-ai.md`** — dated research record: `google-genai`
  2.24.0 installed in the image, model `gemini-2.5-flash`, structured output via
  `response_mime_type` + `response_schema`. Pilot model IDs were explicitly not
  assumed current.
- **`docs/research/gcp/speech-to-text-v2.md`** — dated research record with the
  2026-09-17 revalidation: `chirp_3`, recognizer path pattern, `us`/`eu`
  multi-region constraint, `BatchRecognize` + GCS, `google-cloud-speech` 2.40.0.
- **`docs/research/gcp/drive-api-v3.md`** — Drive API v3 research record.
- **`src/site_visit_workflow/preflight.py`** and the `auth-preflight` /
  `list-folder-children` CLI commands.
- **`SPEECH_LOCATION`** setting (default `us`), distinct from
  `GOOGLE_CLOUD_REGION` and `VERTEX_LOCATION`.
- This `CHANGELOG.md`.

### Changed

- `docs/research/gcp/api-research.md` — added a dated 2026-09-17 section
  recording confirmed API enablement for Drive, Cloud Run, Cloud Build,
  Artifact Registry, Cloud Storage, Speech-to-Text, Vertex AI, Sheets, and
  Service Usage. The existing table is unchanged.
- `sheets.googleapis.com` enabled on `shir-sitevisit` (was disabled).
- `.env.example` — the `GOOGLE_APPLICATION_CREDENTIALS` key-file line commented
  out; a key file is prohibited by the Phase 2 rules. Live Phase 2 settings
  added.
- `pyproject.toml` — added the `google-genai` dependency.
- Bucket IAM corrected: `roles/storage.objectUser` was briefly granted at 06:20
  UTC, then **removed** at 06:21 UTC and replaced with `objectCreator` +
  `objectViewer`, because `objectUser` carries `storage.objects.delete`. This
  removed a permission; no data was deleted. `legacyBucketReader` added at
  06:28 UTC to resolve a `storage.buckets.get` 403.

### Fixed

- **Chirp recognizer region bug.** The recognizer path was built from
  `GOOGLE_CLOUD_REGION=us-central1`, but Chirp 3 is served from the `us` / `eu`
  multi-regions. Found in preflight; addressed by the separate `SPEECH_LOCATION`
  setting (ADR 0006). Retest is one `BatchRecognize` submission.

### Known issues

Outstanding blockers from
`docs/evidence/20260917T055321Z-phase2-auth-preflight/go-no-go.md`:

- Cloud Run is sized 1Gi / 600s, too small for site-visit video. `/tmp` is
  in-memory and counts against the memory limit; raise memory (4–8Gi) and
  timeout, or stream Drive → ffmpeg → GCS without buffering.
- No live Vertex AI call and no live `BatchRecognize` submission has been made.
  Model availability and request shapes are documentation facts, not observed
  ones.
- Branch `agents/pasted-text-processing` has no upstream; nothing pushed to
  GitHub.
- The service account is not a member of the Shared Drive (`drives.get` → 404).
  This is the intended least-privilege state, not a defect.

## How to update this later

Add a new entry under `## [Unreleased]` for every meaningful change, grouped
under Added / Changed / Deprecated / Removed / Fixed / Security. Move
`[Unreleased]` to a dated version heading at release. Never rewrite an existing
entry; correct it with a new one.
