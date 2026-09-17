# GCP API research record

**Research date:** 2026-09-16

The CLI has an intentionally explicit integration boundary for these APIs, but
this repository has not executed live cloud tests. Validate current API
behavior, regional availability, SDK versions, pricing, quotas, and model
configuration before any live command.

| Service | Official documentation | Setup and caveats |
| --- | --- | --- |
| Google Drive API | https://developers.google.com/workspace/drive/api/guides/about-sdk | Immediate-child listing uses `supportsAllDrives` / `includeItemsFromAllDrives`; validate configured-folder access before execution. |
| Cloud Storage | https://cloud.google.com/storage/docs | Use a dedicated staging prefix and least-privilege object access; retain staged artifacts. |
| Speech-to-Text v2 | https://cloud.google.com/speech-to-text/v2/docs | The explicit batch boundary requests `chirp_3` for one WAV; confirm current regional availability and request shape before execution. |
| Vertex AI | https://cloud.google.com/vertex-ai/generative-ai/docs | Use only the approved extraction prompt and strict JSON response validation. Confirm model IDs at implementation time. |
| Google Sheets API | https://developers.google.com/workspace/sheets/api | Upsert draft rows using the immutable source ID rather than appending duplicates. |

## 2026-09-17 — confirmed API enablement status

Confirmed during preflight run `20260917T055321Z-phase2-auth-preflight` via
`gcloud services list --enabled --project=shir-sitevisit` at 05:53 UTC, with
Sheets re-checked after it was enabled at 06:20 UTC. Raw output is retained at
`docs/evidence/20260917T055321Z-phase2-auth-preflight/raw/apis-enabled.txt`.

This section supersedes nothing above; the table above records the intended
integration boundary, this one records observed enablement on the project.

| Service | API | Enabled on `shir-sitevisit` | Runtime SA role | Certainty |
| --- | --- | --- | --- | --- |
| Google Drive | `drive.googleapis.com` | Yes (enabled 2026-09-16) | resource-level folder share; `canDownload: true`, `canDelete: false` | [VERIFIED] |
| Cloud Run | `run.googleapis.com` | Yes | job runs with the SA attached directly | [VERIFIED] |
| Cloud Build | `cloudbuild.googleapis.com` | Yes | deployer identity only | [VERIFIED] |
| Artifact Registry | `artifactregistry.googleapis.com` | Yes | deployer identity only | [VERIFIED] |
| Cloud Storage | `storage.googleapis.com` | Yes | `objectCreator` + `objectViewer` + `legacyBucketReader` on `gs://shir-sitevisit-staging`; **no delete** (ADR 0005) | [VERIFIED] |
| Speech-to-Text v2 | `speech.googleapis.com` | Yes | `roles/speech.client` | [VERIFIED] |
| Vertex AI | `aiplatform.googleapis.com` | Yes | `roles/aiplatform.user` | [VERIFIED] |
| Google Sheets | `sheets.googleapis.com` | **Enabled during this run** (was disabled at 05:53 UTC; enabled 06:20 UTC) | writer on one Sheet by resource share, not IAM | [VERIFIED] |
| Service Usage | `serviceusage.googleapis.com` | Yes | deployer identity only | [VERIFIED] |

Notes carried from the preflight:

- Enablement is not authorization. Speech and Vertex were both enabled *and*
  role-granted yet still classified **PARTIAL** — Speech for a wrong recognizer
  location (ADR 0006), Vertex for having no model ID pinned
  (`docs/research/gcp/vertex-ai.md`).
- Drive and Sheets access is granted at the **resource** level (a folder share,
  a file share), not by project IAM. A project IAM policy read will not show
  it.
- A disabled API returns HTTP 403 `reason: accessNotConfigured`, which reads
  like a permission error but is an enablement error. Check enablement first.
- Dated research records now exist for Drive (`drive-api-v3.md`), Speech
  (`speech-to-text-v2.md`), and Vertex (`vertex-ai.md`). Cloud Storage and
  Sheets have no dedicated record yet. [OPEN]

## How to update this later

Before wiring each API, add the exact library version, configuration command, tested request shape, and dated official URL to this record. Never include credential values.
