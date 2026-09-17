# Go / no-go — Phase 2 authorization preflight

**Run ID:** `20260917T055321Z-phase2-auth-preflight`
**Classification:** **PARTIAL**

Authorization to Drive, Cloud Storage, Speech, and Vertex is in place. The
workflow cannot complete end to end because the Sheets catalog target does not
exist and the L2/L3 prompts have not been written.

## What is proven working

- Cloud Run Job `site-visit-workflow` runs with
  `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` attached
  directly. No key file, no impersonation, no personal Drive OAuth. Zero
  user-managed keys exist for the account.
- Drive: the folder resolves, 19 immediate children are listed
  (16 `video/quicktime`, 3 `image/heif`, 0 subfolders), and the SA holds
  `canDownload: true` and `canDelete: false` on the media.
- Cloud Storage: `gs://shir-sitevisit-staging` (US, uniform access) with
  `objectCreator` + `objectViewer` + `legacyBucketReader`, and **no delete**.
- APIs enabled: Drive, Cloud Run, Cloud Build, Artifact Registry, Cloud Storage,
  Speech-to-Text, Vertex AI, Sheets, Service Usage.
- Runtime image: Python 3.11.16, ffmpeg 7.1.5 and ffprobe present,
  `google-api-python-client 2.200.0`, `google-auth 2.58.0`,
  `google-cloud-speech 2.40.0`, `google-cloud-storage 3.14.1`,
  `google-genai 2.24.0`.
- GitHub: authenticated as `dmyers1101`, `ADMIN` on
  `dmyers1101/Site-Visit-Live-Workflow`, token scope includes `repo`.

## Processing boundary (confirmed)

The approved test folder contains **direct media children, not visit
subfolders**. `child_folders.count = 0`. Any code that discovers work by
listing subfolders will find nothing here.

## Blocking items before a full trial

| # | Blocker | Exact least-privilege action | Retest after |
| --- | --- | --- | --- |
| 1 | No catalog Sheet exists | Operator creates the Sheet, shares it as **Editor** with `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`, and supplies the Sheet ID + tab name | Redeploy with `CATALOG_SHEET_ID` set; rerun `auth-preflight` and confirm `sheets.readable` and `can_edit: true` |
| 2 | `prompts/l2-enrichment.md` missing | Author and version the L2 prompt per `prompts/prompt-governance.md` | File inventory |
| 3 | `prompts/l3-refinement.md` missing | Author and version the L3 prompt | File inventory |
| 4 | Chirp region wrong | Chirp 3 is served from the **`us`/`eu` multi-regions**; the code builds the recognizer from `GOOGLE_CLOUD_REGION=us-central1`. Add `SPEECH_LOCATION=us` and use it for the recognizer path only | One BatchRecognize submission |
| 5 | No Vertex model pinned | Pin a model ID in config (`gemini-2.5-flash` is currently available) and record the retrieval date | One L1 call |
| 6 | Nothing pushed to GitHub | `git push -u origin agents/pasted-text-processing` | `git status -sb` |
| 7 | Cloud Run not sized for media | `/tmp` is in-memory on Cloud Run and counts against the memory limit. Currently 1Gi / 600s. Raise memory (4–8Gi) and timeout, or stream Drive → ffmpeg → GCS without buffering whole files | One end-to-end asset |

## Non-blocking findings

- The SA is **not** a member of the Shared Drive (`drives.get` → 404). Folder
  level sharing is sufficient and is the least-privilege state. Do not add
  Shared Drive membership without a specific need.
- `.env.example` still contains
  `GOOGLE_APPLICATION_CREDENTIALS=./secrets/gcp-service-account.json`. The
  deployed job does not use it, but the template invites a pattern the Phase 2
  rules prohibit. Recommend removing that line.
- `apps/live-workflow` (branch `main`) has no `src/`, `infra/`, `pyproject.toml`,
  `docs/RUNBOOKS/`, or `docs/evidence/`. All Phase 2 work lives on branch
  `agents/pasted-text-processing` in the worktree. Merging to `main` is a
  separate decision.

## Media handling note

Media is never downloaded to an operator workstation. The only copy leaves Drive
inside the Cloud Run container, is transcoded to WAV, and is written to
`gs://shir-sitevisit-staging`. Speech-to-Text cannot read from Drive, so this
cloud-side hop is required; that is why Drive `canDownload` matters.

## Single next safest action

Create the catalog Sheet, share it as Editor with the service account, and
supply the Sheet ID and tab name. That unblocks the only authorization item
still outstanding.

## How to update this later

Create a new dated preflight directory for each future check; never overwrite
this one.
