# Phase 2 authorization matrix

**Run ID:** `20260917T055321Z-phase2-auth-preflight`
**Date (UTC):** 2026-09-17
**Direct runtime identity:** `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`
**Project / region:** `shir-sitevisit` / `us-central1`
**Target Drive folder:** `1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF` — "2026-08 Executive - Parth Vaidya"
**Overall result:** **PARTIAL**

All live Google API checks in this matrix originated from the deployed Cloud Run
Job `site-visit-workflow`, running with the service account attached directly.
No personal Drive OAuth, no impersonation, and no service-account key was used.

| Workflow stage | Runtime identity | Resource | Required access | Evidence/test used | Result | Missing least-privilege grant or configuration | Safe next action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Deployed Cloud Run runtime | `site-visit-workflow@…` | Cloud Run Job `site-visit-workflow` | Job runs with the SA attached directly; no key/impersonation | `gcloud run jobs describe`; 4 successful executions (`vrrr2`, `bhs2h`, `nnfpk`, `lhplp`) | **PASS** | None | None |
| Drive folder discovery | `site-visit-workflow@…` | Folder `1Q_VVI…` | `drive.files.get` + `files.list` on immediate children | `auth-preflight` exec `lhplp`: folder_get ok, 0 child folders, 19 child files | **PASS** | None | None |
| Drive source-video read/download | `site-visit-workflow@…` | 16 × `video/quicktime` in that folder | `canDownload` so the **cloud job** can read bytes for transcode | Capability metadata on `IMG_3651.MOV`: `canDownload: true` | **PASS** | None | None |
| Future approved Drive rename | `site-visit-workflow@…` | Source video files | `canRename` for a human-approved rename later | Capability metadata: `canRename: true`, `canEdit: true` | **PASS** (capability only; no rename performed) | None | Keep rename gated behind explicit human approval |
| Drive source protection | `site-visit-workflow@…` | Source video files | Deletion must be impossible | Capability metadata: `canDelete: false` | **PASS** | None | None |
| Shared Drive membership | `site-visit-workflow@…` | Shared Drive `0AGzXWk46WhgyUk9PVA` | `drives.get` to enumerate the Shared Drive | `drives().get` → **HTTP 404 "Shared drive not found"** | **FAIL (by design)** | SA is shared on the *folder* only, not a member of the Shared Drive | Acceptable. Folder-level sharing is sufficient and is the least-privilege option. Do not add Shared Drive membership unless a later stage needs it |
| GCS WAV upload | `site-visit-workflow@…` | `gs://shir-sitevisit-staging` (US) | `storage.objects.create` | Bucket IAM: `roles/storage.objectCreator` granted this run | **PASS** | None | Live object write intentionally not performed during preflight |
| GCS workflow-artifact read | `site-visit-workflow@…` | `gs://shir-sitevisit-staging` | `storage.objects.get` / `.list` | Bucket IAM: `roles/storage.objectViewer` + `roles/storage.legacyBucketReader` | **PASS** | None | None |
| GCS delete protection | `site-visit-workflow@…` | `gs://shir-sitevisit-staging` | Delete must be absent | `roles/storage.objectUser` was granted then **removed**; no role now carries `storage.objects.delete` | **PASS** | None (absence is intentional) | None |
| Speech-to-Text v2 / Chirp | `site-visit-workflow@…` | `speech.googleapis.com` | `roles/speech.client` + API enabled | `gcloud services list` (enabled); project IAM shows `roles/speech.client` | **PARTIAL** | Region misconfiguration: code builds the recognizer from `GOOGLE_CLOUD_REGION=us-central1`, but Chirp 3 is served from the **`us`/`eu` multi-regions** | Add a separate `SPEECH_LOCATION=us` setting and use it for the recognizer path |
| Vertex AI L1 | `site-visit-workflow@…` | `aiplatform.googleapis.com` | `roles/aiplatform.user` + API + SDK | API enabled; `roles/aiplatform.user` present; `google-genai 2.24.0` now installed | **PARTIAL** | No model ID pinned in code/config; no live model call attempted | Pin the model ID in config and revalidate against current docs before first call |
| Vertex AI L2 | `site-visit-workflow@…` | `aiplatform.googleapis.com` | As above + `prompts/l2-enrichment.md` | File inventory of `prompts/` | **FAIL** | `prompts/l2-enrichment.md` does not exist | Author and version the L2 prompt before any L2 call |
| Vertex AI L3 | `site-visit-workflow@…` | `aiplatform.googleapis.com` | As above + `prompts/l3-refinement.md` | File inventory of `prompts/` | **FAIL** | `prompts/l3-refinement.md` does not exist | Author and version the L3 prompt before any L3 call |
| Google Sheets catalog read | `site-visit-workflow@…` | Catalog Sheet | `sheets.spreadsheets.get` + Drive read on the Sheet | `sheets.googleapis.com` **enabled this run**; no Sheet exists to read | **FAIL** | No catalog Sheet exists; `CATALOG_SHEET_ID` is empty | Operator creates the Sheet and shares it as **Editor** with the SA (see note below) |
| Future Google Sheets row upsert | `site-visit-workflow@…` | Catalog Sheet tab | `sheets.spreadsheets.values.append/update` + `canEdit` | Not testable — no Sheet | **FAIL** | Same as above | Retest capability after the Sheet is shared |
| Durable evidence/log storage | Deployer + job | `docs/evidence/<run-id>/`, Cloud Logging | Durable, versioned evidence | This directory; Cloud Logging for execution output | **PARTIAL** | Branch `agents/pasted-text-processing` has **no upstream**; nothing pushed to GitHub | `git push -u origin agents/pasted-text-processing` |

## Why the catalog Sheet was not created

The approved plan was for this preflight to create the Sheet inside the Shared
Drive so it would be visible to the operator. That is not cleanly possible:

- `drives().get` returns **404 Shared drive not found**, which confirms the
  service account is shared on the *folder only* and is not a member of the
  Shared Drive. It therefore cannot create a file in the Shared Drive root.
- The folder itself reports `canAddChildren: true`, so the SA *could* create the
  Sheet inside `2026-08 Executive - Parth Vaidya`. That was deliberately not
  done: it would write a non-media file into the immutable source-media folder,
  which conflicts with the single-folder immutable-source rule.
- Creating it in the service account's own My Drive would leave it invisible to
  the operator and is subject to service-account Drive storage limits.

**Least-privilege resolution:** the operator creates the Sheet in a location
they control and shares it as **Editor** with
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`, then sets
`CATALOG_SHEET_ID`. No Drive or IAM change beyond that one share is required.

## How to update this later

Create a new dated preflight evidence folder for each future authorization
check; never overwrite this one. Update `docs/AUTH.md`, `docs/SETUP.md`, and the
GCP research records only when a preflight establishes a new confirmed fact.
