# Setup guide

## Objective

Bring a **new machine** from zero to being able to build, deploy, and execute the
cloud-native Site Visit workflow. The workflow itself runs as a Cloud Run Job; this
machine is a deploy and review console only. Media never lands here.

> **Superseded scope note.** The original objective read: "Prepare the local environment
> for the Phase 2 single-visit workflow without processing media until Drive access,
> prompts, and the human approval gate are complete." That gate has been passed —
> Drive access, the three prompts, the staging bucket and the catalog Sheet are all in
> place — and processing now happens in the cloud, not locally. The never-rename and
> never-delete approval boundaries are unchanged.

## Required access and APIs

Enabled in project `shir-sitevisit` [VERIFIED 2026-09-17]:

- Google Drive API — folder-level access to the approved source folder.
- Cloud Storage API — the dedicated staging bucket and prefix.
- Speech-to-Text v2 API — `BatchRecognize` with Chirp 3.
- Vertex AI API (`aiplatform.googleapis.com`) — L1/L2/L3 extraction.
- Google Sheets API — the catalog Sheet.
- Cloud Run, Cloud Build, Artifact Registry — to build and run the job.
- The dedicated service-account identity and resource-sharing procedure in
  [Site Visit workflow service account](RUNBOOKS/service-account-onboarding.md).

## Local prerequisites

- Git and a clean working tree.
- Google Cloud CLI, authenticated as the **deployer** (see next section).
- Python 3.11+ only if you want to run the offline tests locally
  (`python -m pip install -e ".[test]"`, then `pytest`).
- `ffprobe` and `ffmpeg` on `PATH` **only** if you intend to run media commands locally.
  The deployed path does not need them on your machine — they ship in the image
  (ffmpeg 7.1.5 / ffprobe, Python 3.11.16).
- A local `.env` copied from `.env.example`; keep it untracked. It is used only for
  offline commands and tests; the deployed job carries its own environment variables.

## gcloud authentication — deployer only

```powershell
gcloud auth login
gcloud config set project shir-sitevisit
gcloud config set run/region us-central1
```

**The deployer is never the Drive runtime identity.** Your human Google account builds
the image and deploys/executes the job. The job then runs as
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` and it is *that* identity
which reads Drive, writes GCS, calls Chirp and Vertex, and writes the Sheet. Nothing in
the pipeline uses your personal Drive access.

Consequences to hold onto:

- Do **not** run `gcloud auth application-default login` and then run media commands
  locally against the real folder. That would put your personal OAuth identity on the
  Drive path, which is prohibited (see `docs/AUTH.md`).
- Do **not** create, download, or reference a service-account key file. Zero
  user-managed keys exist for this service account and that is a checked property.
- Do **not** use `--impersonate-service-account`. The job uses direct attachment.

Deployer permissions needed (on `shir-sitevisit`): Cloud Build submit, Artifact Registry
write, Cloud Run developer, and `iam.serviceAccounts.actAs` on the runtime service
account. [ASSUMED] exact role bindings for a *new* deployer are not re-verified here;
confirm with the project owner before the first deploy.

## Environment variable table

These are the variables the deployed Cloud Run Job needs. Values below are the real,
current ones.

| Variable | Real value | Notes |
| --- | --- | --- |
| `GOOGLE_CLOUD_PROJECT` | `shir-sitevisit` | Required by every Google-contacting command. |
| `DRIVE_SHARED_FOLDER_ID` | `1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF` | "2026-08 Executive - Parth Vaidya". 19 direct media children, 0 subfolders. |
| `GCS_STAGING_BUCKET` | `shir-sitevisit-staging` | Bucket **name** only — no `gs://`, no path. US, uniform access. |
| `GCS_STAGING_PREFIX` | `site-visit-staging` | Root prefix for all run-scoped artifacts. Defaults to this if unset. |
| `CATALOG_SHEET_ID` | `158eA2K5FgGc4dQ43xHxdTuri-KOwPSuNn8qQqsasBy0` | "Site Visit Catalog — Live Workflow", owned by `dmyers@shircapital.com`, shared to the SA as writer. |
| `CATALOG_TAB_NAME` | `Catalog` | Created by the code if absent. The default `Sheet1` tab is never touched. |
| `SPEECH_LOCATION` | `us` | The `us` **multi-region**, not `us-central1`. Chirp 3 is served only from `us`/`eu`. |
| `SPEECH_MODEL` | `chirp_3` | The legacy alias `chirp` is rejected with an explicit error, never silently remapped. |
| `VERTEX_LOCATION` | `us-central1` | Vertex region, deliberately separate from `SPEECH_LOCATION`. |
| `VERTEX_MODEL` | `gemini-2.5-flash` | Called through the `google-genai` SDK with a strict `response_schema`. |
| `RUN_ID` | e.g. `20260917T055321Z` | Run-scoped GCS prefix segment. If unset the code generates a UTC stamp. Prefer setting it per execution via `--run-id`. |
| `SITE_VISIT_ENVIRONMENT` | `deployed` | With `deployed`, the code refuses to start under any identity other than the designated service account. |
| `SITE_VISIT_RUNTIME_SERVICE_ACCOUNT` | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` | Must match the attached identity when `SITE_VISIT_ENVIRONMENT=deployed`. |
| `GOOGLE_CLOUD_REGION` | `us-central1` | Optional; general Google/Cloud Run region. Not used for Speech. |
| `GOOGLE_APPLICATION_CREDENTIALS` | **never set** | A key file is prohibited. The job takes ambient ADC from the metadata server. |

The recognizer path Chirp is called with is
`projects/shir-sitevisit/locations/us/recognizers/_` — that is
`projects/{project}/locations/{SPEECH_LOCATION}/recognizers/_`.

## Pointing at a different Drive folder or Sheet

Both are single environment variables; no code change is needed.

**Different Drive folder.** The folder must be shared with
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`. Folder-level sharing is
sufficient and is the least-privilege option — the service account is deliberately *not*
a member of the Shared Drive.

```powershell
gcloud run jobs update site-visit-workflow --region=us-central1 `
  --update-env-vars=DRIVE_SHARED_FOLDER_ID=NEW_FOLDER_ID
gcloud run jobs execute site-visit-workflow --region=us-central1 --wait --args=auth-preflight
gcloud run jobs execute site-visit-workflow --region=us-central1 --wait `
  --args=list-folder-children
```

Confirm from `list-folder-children` that the children are what you expect, and that
`auth-preflight` shows `canDownload: true` on a sample file, before running
`process-folder`. Only `video/*` children are processable; everything else (subfolders,
images such as `image/heif`, trashed items, non-downloadable items) is recorded as an
excluded item with a stated reason and is never silently dropped.

**Different Sheet.** Create the Sheet in a location a human controls, share it as
**Editor** with the service account, then:

```powershell
gcloud run jobs update site-visit-workflow --region=us-central1 `
  --update-env-vars=CATALOG_SHEET_ID=NEW_SHEET_ID,CATALOG_TAB_NAME=Catalog
```

A per-execution tab override is also available: `process-folder --sheet-name OTHER_TAB`.
The tab is created if missing. Do not have the service account create the Sheet itself:
it cannot write to the Shared Drive root, and writing a non-media file into the source
media folder would violate the single-folder immutable-source rule. See
[ADR-0007](decisions/0007-catalog-sheet-ownership-and-location.md).

## Access validation (explicit operator action)

1. Confirm the active Git remote (`dmyers1101/Site-Visit-Live-Workflow`) and intended
   branch (`agents/pasted-text-processing`).
2. Run `auth-preflight` **as the deployed job** and read the JSON record. It reports
   identity, Drive folder metadata and capabilities, GCS bucket location plus which of
   `objects.create/get/list/delete` are held, and Sheets reachability.
3. If Drive fails, complete [Drive HTTP 403 recovery](RUNBOOKS/drive-access-recovery.md)
   using the service account and the approved folder.
4. Run `list-folder-children` and compare the count to what the folder actually holds.
5. Do not proceed if access fails or returns an ambiguous scope. Do not substitute
   another folder when validation fails.

> **Historical note (superseded).** An earlier revision of this guide said "This
> repository has not performed a live cloud or Drive access test." That is no longer
> true: the deployed job completed live Drive, GCS and Sheets checks on 2026-09-17. See
> `docs/evidence/20260917T055321Z-phase2-auth-preflight/`. Steps 3–5 above were
> previously described against a local `files.list` call with `supportsAllDrives=true`
> and `includeItemsFromAllDrives=true`; the code still sends those flags, but the call
> is made from the job, not from a workstation.

## Local offline work

```powershell
python -m pip install -e ".[test]"
pytest
site-visit config-check
```

`config-check` and package import contact nothing. Do not point local media commands at
the real Drive folder.

## How to update this later

Whenever an API, runtime, environment variable, resource ID, or validation command
changes, update the table above, `docs/DEPLOYMENT.md`, `docs/AUTH.md`, and the related
GCP research note in `docs/research/gcp/` in the same pull request. Never add a secret,
token, or key path to this file or to `.env.example`.
