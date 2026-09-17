# Live workflow architecture

## Phase 2 scope

Phase 2 processes **one** configured Google Drive folder. The workflow enumerates that
folder, creates an auditable manifest, stages and transcribes its media inside a Cloud
Run Job, runs a three-layer extraction, and upserts one catalog row per asset for human
review. It does not rename Drive files, create reports, create Asana tasks, or automate
multiple folders.

> **Superseded scope wording.** The original text read: "Phase 2 begins with **one** visit
> subfolder in the approved Google Drive Shared Folder … stage and transcribe one approved
> video, propose an extraction and catalog row, and stop for human review. It does not …
> publish catalog records …". Two parts have moved on: the confirmed boundary is the
> *direct media children* of one folder (the trial folder has zero subfolders), and the
> workflow does now write catalog rows automatically — the human gate moved to *reviewing*
> the `DRAFT` rows rather than approving each write. The rename gate is unchanged: renames
> still require an explicit approval record.

## Architecture and data flow

```text
Google Drive folder  (immutable source evidence)
  |
  |  Drive API v3, runtime service account, canDownload
  v
Cloud Run Job `site-visit-workflow`  (ephemeral container filesystem)
  |   Gate 1  discovery  -> manifest.json
  |   Gate 2  ffprobe + ffmpeg -> mono 16 kHz PCM s16le WAV
  v
Google Cloud Storage  gs://shir-sitevisit-staging  (run-scoped, write-once, no delete)
  |
  |  Gate 3  Speech-to-Text v2 BatchRecognize, chirp_3, locations/us
  v
transcript.txt + transcription-record.json
  |
  |  Gate 4  Vertex AI gemini-2.5-flash (google-genai, strict response_schema)
  v            L1 extraction -> L2 enrichment -> L3 refinement
catalog row
  |
  |  Gate 5  Sheets v4 upsert by immutable Drive asset ID
  v
Google Sheets "Site Visit Catalog — Live Workflow", tab `Catalog`
  |
  v
human review  ->  optional, separately approved rename
```

**Media never touches an operator workstation.** The only workstation roles are building
and deploying the image and reading the results.

GitHub remains the versioned source of truth for workflow definitions, documentation,
decisions, and prompt templates. Google Drive holds immutable source evidence; the
original Drive file ID and name remain in every manifest and catalog row. Google Cloud
Storage holds the durable run evidence. Google Sheets is an output view, not the source
of evidence.

Cloud Run Jobs use the directly attached
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` service account
and ambient ADC; no key files or impersonation are permitted.

![High-Level Architecture](diagrams/high-level-architecture.drawio.png)

> The diagrams in `diagrams/` predate the `process-folder` pipeline and still show the
> single-asset, approval-per-write flow. [OPEN] They need regenerating; the text above is
> authoritative until they are.

## Modules in `src/site_visit_workflow/`

The package is layered deliberately: the pure modules hold the logic and are unit-testable
without a network call, and **one** module owns each external boundary.

| Module | Role | Contacts Google |
| --- | --- | --- |
| `config.py` | `Settings` frozen dataclass built from the environment, required-variable checking, `gcs_uri`, `default_run_id`. Pins the designated service account and refuses to start under a different identity when `SITE_VISIT_ENVIRONMENT=deployed`. Rejects the legacy `chirp` model alias rather than remapping it | No |
| `errors.py` | The error vocabulary: `WorkflowError`, `ValidationError`, `ApprovalRequiredError`, `ExternalServiceError`. `main()` turns a `WorkflowError` into exit code 2 | No |
| `models.py` | Domain records and pure policy: `VisitFolder`, `DriveMediaFile`, `VisitManifest`, `TranscriptionRecord`/`TranscriptStatus`, `L1Extraction`, `L2Enrichment`, `L3Refinement`, `CatalogDraft`, `ReviewApproval`/`ReviewAction`, plus `evaluate_transcript`, `l3_is_permitted`, `require_approval` | No |
| `jsonio.py` | Read/write dataclasses as JSON and rehydrate them with validation | No |
| `discovery.py` | **Pure Gate 1.** Classifies raw Drive child metadata into supported videos vs excluded items with stated reasons, builds the `VisitManifest` and the manifest document, and applies the `--asset-id`/`--limit` selectors. Never recurses | No |
| `media.py` | **Gate 2 tooling.** `ffprobe`/`ffmpeg` subprocess wrappers: probe, extract mono 16 kHz `pcm_s16le`, verify the produced WAV really matches the contract, SHA-256 both files. Always writes a new file; never overwrites | No (local ffmpeg) |
| `google.py` | **The only Google boundary.** `runtime_credentials`, `DriveGateway` (list, folder metadata, stage/download, rename), `StorageGateway` (upload/write/read/list, every write guarded by `if_generation_match=0`), the run/asset/WAV/speech-output prefix functions, Chirp submit/await/read, and the Sheets tab-ensure and row upsert | Yes |
| `extraction.py` | **Gate 4.** Builds the Vertex `google-genai` client, loads `prompts/l1-extraction.md`, `l2-enrichment.md`, `l3-refinement.md` **at runtime**, and runs each layer with a strict `response_schema` | Yes (Vertex) |
| `catalog.py` | **Pure Gate 5 logic.** `FULL_CATALOG_HEADERS` (schema 2.0) and `build_catalog_row` / `row_values`. Asserts the row never drifts from the header order. Writes nothing | No |
| `preflight.py` | Strictly read-only authorization report: runtime environment, identity, Drive, Cloud Storage, Sheets. Each check captures its own sanitized error | Yes (read-only) |
| `cli.py` | Argument parsing and orchestration. `cmd_process_folder` runs Gates 1–5 sequentially, one asset at a time, emitting one JSON line per step and continuing past a single asset's failure | Via the modules above |

Boundary rules the layering encodes ([ADR-0008](decisions/0008-layer-boundaries-enforced-in-code.md)):
`discovery`, `catalog`, `models` and `media` never import `google`; `cli` never inlines a
Google call into the processing loop; adding a gate means adding a helper, not widening
the loop.

## Components and contracts

| Stage | Input | Output | Guardrail |
| --- | --- | --- | --- |
| Gate 1 — discovery | Drive folder ID | `manifest.json` in GCS, with every excluded child and its reason | Direct media children only; no recursion; no supported video means no manifest and no run |
| Gate 2 — media preparation | One Drive video | `media-preparation.json`, WAV in GCS | Source Drive file is never edited or deleted; the WAV is verified to be mono 16 kHz `pcm_s16le`; no overwrite |
| Gate 3 — transcription | WAV in GCS | `transcript.txt`, `transcription-record.json` | One `BatchRecognize` per attempt; `chirp_3` in `locations/us`; retry an empty transcript once, then `NEEDS_REVIEW`; never fabricate |
| Gate 4 — L1/L2/L3 extraction | Transcript text and source ID | Strict-JSON layer results in GCS | Each layer gated on the previous validating; L3 only for `ENRICHED` L2; a failed layer keeps the validated upstream evidence |
| Gate 5 — catalog | Manifest, transcription record, validated layers | One upserted Sheet row + `catalog-row.json` | Keyed by the immutable Drive asset ID; `NOT_RUN` and blanks rather than invented values; `catalog_status` stays `DRAFT` |
| Review | Catalog rows and GCS evidence | Approval or correction | Proposed descriptive names require explicit approval; nothing is deleted |

## Runtime and platform

| | |
| --- | --- |
| Container | Python 3.11.16, ffmpeg 7.1.5 + ffprobe, entrypoint `site-visit` |
| Compute | Cloud Run Job `site-visit-workflow`, `us-central1`, one task, parallelism one, no retries |
| Identity | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`, ambient ADC, no key, no impersonation |
| Storage | `gs://shir-sitevisit-staging` (US, uniform access), run-scoped prefixes, write-once, **no delete permission** |
| Speech | Speech-to-Text v2, `chirp_3`, recognizer `projects/shir-sitevisit/locations/us/recognizers/_` |
| Extraction | Vertex AI `gemini-2.5-flash` in `us-central1` via `google-genai` |
| Catalog | Sheets v4, spreadsheet `158eA2K5FgGc4dQ43xHxdTuri-KOwPSuNn8qQqsasBy0`, tab `Catalog` |

`SPEECH_LOCATION` is deliberately separate from the Cloud Run region: Chirp 3 is served
from the `us`/`eu` multi-regions only ([ADR-0006](decisions/0006-speech-location-separate-from-run-region.md)).

## How to update this later

When adding a service, record its trigger, input/output schema, owner, environment variables, failure mode, and review impact here and in the relevant runbook. Update the diagrams and ADR when a new external system or automation boundary is introduced.
Keep the module table in step with `src/site_visit_workflow/`: a new module needs a row
stating whether it contacts Google, and a module that starts contacting Google needs an
ADR, not just an edit here.
