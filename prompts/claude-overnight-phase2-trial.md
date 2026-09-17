# Claude Overnight Phase 2 Trial

**Prompt version:** 1.1  
**Purpose:** Run an end-to-end, production-style trial over the approved test
folder video library and leave a complete, repeatable operating record for a
no-context future session.

## Your mission

Work only in this live workspace:

```text
C:\Users\SHIRA\My Drive\Site Visit App\apps\live-workflow
```

Establish and document an end-to-end trial over every supported video in the
approved test folder using the existing Google Cloud service account as the
live workflow identity. Connect the versioned GitHub prompt files to the live
GCP workflow for the L1, L2, and L3 extraction sequence, and create/update the
real Google Sheets catalog. The primary deliverable is a repeatable, safe
workflow and its evidence—not unrelated broad automation.

## Non-negotiable rules

1. **Never delete anything.** Do not delete Drive files, local files, staged
   audio, GCS objects, logs, output artifacts, prompts, or documentation.
2. Work only in `apps/live-workflow`. Do not modify `pilot/` or `_design/`.
   `pilot/` is read-only reference evidence.
3. GitHub is the versioned source of truth for code, prompts, decisions, and
   documentation. Google Drive is the source-media library. Google Cloud is the
   processing platform.
4. For live Drive/GCP processing, use the existing deployed runtime identity:
   `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`. Do not create
   another account, a user-managed key, or a personal Drive runtime path.
5. Do not use `GOOGLE_APPLICATION_CREDENTIALS`,
   `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`, service-account impersonation, or
   `gcloud auth application-default login --scopes=...drive...`.
6. Do not rename, move, edit, or delete a Drive source video automatically.
   Descriptive names are proposals until a human explicitly approves them.
7. Create and update the approved Google Sheets catalog with idempotent rows
   for this test-folder run. Record the target Sheet ID, tab name, row key, and
   per-row outcome. Do not publish to another system.
8. Do not create reports, Asana tasks, a scheduled job, or multi-folder
   automation.
9. Process every supported video in the approved test-folder scope. First
   enumerate the folder and document whether the videos are direct children or
   belong to immediate visit subfolders. Do not recursively process unrelated
   folders or another library. Use one-file Speech-to-Text v2 BatchRecognize
   requests and conservative, documented concurrency.
10. Before using or wiring a GCP API/model/library, obtain current official
    Google documentation and record its retrieval date, URL, installed/current
    library version, required setup, and caveats. Do not treat pilot model IDs
    or API behavior as current facts.
11. If an interactive login, Drive share, IAM grant, or other external
    authorization is required, stop that action. Record the exact sanitized
    error, identity, least-privilege permission needed, and resume point. Do
    not substitute a workaround.
12. Before each external command, record its purpose, runtime identity, target
    system, whether it reads/writes/mutates, intended output, and rollback or
    cleanup action. After it runs, record the exact non-secret command and
    result.

## Required reading and source map

Read these first and record each path in `docs/evidence/<run-id>/source-map.md`:

### Live authoritative documents

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/SETUP.md`
- `docs/AUTH.md`
- `docs/OPERATIONS.md`
- `docs/DEPLOYMENT.md`
- `docs/RUNBOOKS/drive-intake.md`
- `docs/RUNBOOKS/transcription.md`
- `docs/RUNBOOKS/catalog.md`
- `docs/RUNBOOKS/service-account-onboarding.md`
- `docs/research/gcp/`
- `prompts/`

If an originally expected live document is absent, record it as a gap; do not
invent that it was read.

### Pilot references (read-only; revalidate before reuse)

- `C:\Users\SHIRA\My Drive\Site Visit App\pilot\README.md`
- `C:\Users\SHIRA\My Drive\Site Visit App\pilot\SETUP_LOG.md`
- `C:\Users\SHIRA\My Drive\Site Visit App\pilot\GOTCHAS.md`
- `C:\Users\SHIRA\My Drive\Site Visit App\pilot\run_pipeline.py`
- `C:\Users\SHIRA\My Drive\Site Visit App\pilot\spikes\process-review-spike\handoff-package\README.md`
- `C:\Users\SHIRA\My Drive\Site Visit App\pilot\spikes\process-review-spike\handoff-package\01-prompt-index.md`
- `C:\Users\SHIRA\My Drive\Site Visit App\pilot\spikes\process-review-spike\handoff-package\02-lessons-observations.md`
- `C:\Users\SHIRA\My Drive\Site Visit App\pilot\spikes\process-review-spike\handoff-package\03-open-questions.md`
- `C:\Users\SHIRA\My Drive\Site Visit App\pilot\logs\20260807T080639Z_L1_prompt.txt`
- `C:\Users\SHIRA\My Drive\Site Visit App\pilot\logs\20260807T080639Z_L2_prompt.txt`
- `C:\Users\SHIRA\My Drive\Site Visit App\pilot\logs\20260807T080639Z_L3_prompt.txt`

Use `run_pipeline.py` symbols `L1_INSTR`, `L2_INSTR`, and `L3_INSTR` as the
traceable pilot prompt baseline. Do not copy pilot code wholesale. The pilot
shows these candidate patterns that require live revalidation:

- extract mono 16 kHz WAV before Chirp for `.MOV` sources;
- use GCS `gs://` audio input for BatchRecognize;
- start one-file BatchRecognize requests at low concurrency;
- record and handle empty transcripts explicitly;
- use L1 factual extraction, L2 enrichment, and L3 refinement;
- current model IDs, quotas, SDK versions, and response behavior are not
  assumed from pilot observations.

## Required prompt workflow

Create or update these separate, versioned Markdown prompt files under
`prompts/`:

1. `drive-intake.md`
2. `l1-extraction.md`
3. `l2-enrichment.md`
4. `l3-refinement.md`
5. `catalog-row.md`
6. `prompt-governance.md`

Every prompt file must contain:

- purpose;
- semantic version;
- source/reference lineage;
- expected input JSON/text;
- exact prompt text;
- expected output JSON schema;
- validation rules;
- known limitations/uncertainty behavior;
- safe update process;
- Git rollback instructions;
- `How to update this later`.

### Prompt boundaries

L1 may produce only factual fields:

```json
{
  "source_asset_identifier": "string",
  "location": "string or null",
  "issue_description": "string or null",
  "suggested_filename": "string",
  "confidence_note": "string"
}
```

L2 may enrich a validated L1 result only with controlled analysis fields
documented in its own schema, such as trade, area type, severity, and
recommended action. L3 may refine validated L2 results only with controlled
ownership, urgency, and uncertainty/note fields. Every layer must preserve the
immutable source asset ID and prior-source traceability. The exact live schemas
must be reviewed and versioned before an API call.

No layer may rename Drive files, create tasks, create reports, publish Sheets
rows, or silently convert an empty transcript into a maintenance finding.

## One-asset trial sequence

### Gate 0: establish direct runtime identity

1. Inspect the deployed workload configuration before any Drive/GCP action.
2. Record its exact attached service-account email.
3. Confirm no key-file or impersonation configuration exists.
4. Confirm the exact Drive test-library folder configured for the trial.
5. Run only a read-only immediate-child Drive listing.
6. If the execution does not start/complete within three minutes, stop waiting,
   record execution/task/log diagnostics, and do not retry automatically.

### Gate 1: enumerate the test library and create a manifest

1. List the approved test folder's immediate children and determine the
   documented processing boundary: direct media files or immediate visit
   subfolders.
2. List every supported media file inside that documented boundary. Do not
   traverse any deeper or substitute another folder.
3. Record file name, Drive ID, MIME type, size, modified time, Drive link, and
   original immutable name.
4. Create a single `manifest.json` before downloading/staging anything. It must
   include every discovered supported source asset and a stable run-level
   manifest ID.
5. Record the supported-file count, file types, naming patterns, and every
   excluded item with its reason.

### Gate 2: media preparation

1. For each manifest asset, download/stage a copy without overwriting an
   existing staged file.
2. Record `ffprobe` output for every source asset.
3. Extract a mono 16 kHz PCM WAV with `ffmpeg` for every supported source
   asset.
4. Retain every staged video and WAV; record their paths and checksums if
   available.

### Gate 3: transcription

1. Upload each WAV to a uniquely named GCS staging path that includes the run
   ID and immutable Drive asset ID.
2. Submit one Speech-to-Text v2 / Chirp BatchRecognize request per WAV.
3. Record request/operation ID, timestamps, input/output GCS URIs, transcript
   status, and sanitized errors.
4. If the transcript is empty, retry once only. If still empty, record
   `NEEDS_REVIEW`, stop the extraction path, and preserve all artifacts.

### Gate 4: L1 to L3 prompt trial

1. Preserve a local immutable copy/reference of every transcript used.
2. Run L1 with the versioned GitHub prompt file for every completed,
   non-empty transcript and validate strict JSON.
3. Run L2 only if that asset's L1 validates; validate strict JSON and source
   linkage.
4. Run L3 only if that asset's L2 validates; validate strict JSON and source
   linkage.
5. Store every prompt version, input reference/checksum, raw response, parsed
   output, validation result, model ID, SDK/library version, timestamp, and
   sanitized error under the run evidence directory for each asset/layer.
6. Do not change any Drive source.

### Gate 5: Google Sheets catalog and review package

1. Define/version the Google Sheets catalog schema with the immutable Drive
   asset ID as the idempotent row key.
2. Create a local draft catalog JSON/CSV/Markdown record for every manifest
   asset before writing to Sheets.
3. Create or update one Google Sheets row per source asset using the
   idempotent Drive asset ID row key. Include source Drive hyperlink, immutable
   original filename, transcript GCS link/reference, transcript status, L1/L2/L3
   outputs, suggested filename, confidence/uncertainty, and timestamps.
4. Record every Sheets upsert outcome and its row reference in the evidence.
5. Create a human-review package that compares original name, proposed name,
   transcript status, L1/L2/L3 outputs, uncertainty, and actions that remain
   blocked.
6. Do not rename Drive media.

## Required documentation and evidence

Use a unique UTC run ID:

```text
docs/evidence/<YYYYMMDDTHHMMSSZ>-one-asset-trial/
```

Create at least:

```text
source-map.md
goal-and-scope.md
preflight.md
artifact-map.md
commands.md
runtime-identity.md
drive-discovery.json
selection-decision.md
manifest.json
media-preparation.md
transcription-record.json
prompt-execution/
catalog-draft.json
human-review-package.md
catalog-upsert-record.json
scorecard.md
final-handoff.md
```

Update the live architecture, setup, auth, operations, runbooks, ADRs, and GCP
research records whenever the trial establishes or changes a rule. Every new
component/document must have a `How to update this later` section.

In `commands.md`, use a table:

| UTC time | Command | Identity | System | Read/write/mutate | Result | Artifact/log link |
| --- | --- | --- | --- | --- | --- | --- |

Never place secrets, OAuth tokens, service-account keys, unredacted credentials,
or full unnecessary media contents in Git or evidence.

## Failure behavior

For Drive, ffmpeg, GCS, Speech-to-Text, Vertex AI, prompt validation, or Sheets
failure:

1. Preserve all existing artifacts.
2. Record the precise sanitized error and the stage where it occurred.
3. Record the runtime identity and input/output references.
4. Record the smallest next safe remediation.
5. Do not silently fall back to another account, API, folder, model, or prompt.
6. Do not proceed past the failed stage.

## Final deliverable before ending

Create `docs/evidence/<run-id>/final-handoff.md` for a no-context future
session. It must include:

- goal, scope, and all hard safety rules;
- selected Drive folder, processing boundary, and every source-asset identifier
  and link;
- source-document map and pilot-reference lineage;
- deployed runtime identity and direct-service-account proof;
- exact commands run, sanitized outputs/errors, and evidence links;
- artifact map with locations and retention policy;
- prompt file names, versions, schemas, and L1 -> L2 -> L3 sequence;
- GCP API/model/SDK validation record;
- catalog schema and idempotent key;
- human-review requirements before rename or publication;
- completed, blocked, and intentionally unattempted work;
- exact next command/action;
- rollback instructions;
- `How to update this later`.

Do not summarize success loosely. State exactly which gates have completed and
which have not.

## Required final response

Return a concise report containing:

1. run ID;
2. direct runtime service-account email;
3. test-folder boundary, source-file count, completed/blocked asset counts, and
   any excluded files;
4. completed gate results;
5. blocked gate results and sanitized errors;
6. exact files created/updated;
7. scorecard result;
8. exact next safe action.

## How to update this later

Create a new version of this prompt when workflow scope changes. Preserve this
version and its evidence lineage. Restore a prior version with Git:

```powershell
git log -- prompts/claude-overnight-phase2-trial.md
git checkout <known-good-commit> -- prompts/claude-overnight-phase2-trial.md
```
