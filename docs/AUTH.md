# Authentication and authorization

## Authorization model

The deployed live model uses the existing dedicated service account
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` directly,
attached to the workload (Cloud Run Job). It uses no key file, and the
application uses only ambient credentials from that direct attachment. A
personal Drive identity must never be the deployed runtime identity. See
[Site Visit workflow service account](RUNBOOKS/service-account-onboarding.md).

### Two identities, never confused

| | Deployer | Runtime |
| --- | --- | --- |
| Who | A human Google account, e.g. `dmyers@shircapital.com` | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` |
| Authenticates via | `gcloud auth login` on a workstation | Ambient ADC from the Cloud Run metadata server |
| Can | Build the image, deploy/update the job, execute the job, read logs, own and share the catalog Sheet | Read the Drive folder and download media, create/read GCS objects, call Chirp and Vertex, create the `Catalog` tab and upsert rows |
| Cannot / must not | Touch media. A deployer's personal Drive access is never on the processing path. | Delete anything, anywhere. Enumerate the Shared Drive. Be replaced by a key or an impersonated principal. |
| Credential material | The operator's own gcloud login | **None stored anywhere.** Zero user-managed keys exist for this service account. [VERIFIED 2026-09-17] |

Executing the job is a deployer action; everything the job *does* is a runtime action.
That separation is the whole model: the person who ships the code is not the identity
that reads the property manager's media.

## What the runtime service account can and cannot do

Confirmed by the deployed `auth-preflight` on 2026-09-17
([authorization matrix](evidence/20260917T055321Z-phase2-auth-preflight/authorization-matrix.md)):

| Capability | Status | Evidence |
| --- | --- | --- |
| Drive: `files.get` + `files.list` on folder `1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF` | **yes** | folder get ok; 19 child files, 0 child folders |
| Drive: `canDownload` on the source media | **yes** | capability metadata on a sample `video/quicktime` file |
| Drive: `canRename` / `canEdit` | **yes, but unused** | capability present; no rename has been performed and `process-folder` never renames |
| Drive: `canDelete` | **no** | `canDelete: false` — source media cannot be destroyed by this identity |
| Drive: Shared Drive membership (`drives.get`) | **no, by design** | HTTP 404 "Shared drive not found". The SA is shared on the *folder only*. Folder-level sharing is sufficient and is the least-privilege option — do not add Shared Drive membership |
| GCS: `storage.objects.create` on `gs://shir-sitevisit-staging` | **yes** | `roles/storage.objectCreator` |
| GCS: `storage.objects.get` / `.list` | **yes** | `roles/storage.objectViewer` + `roles/storage.legacyBucketReader` |
| GCS: `storage.objects.delete` | **no, by design** | `roles/storage.objectUser` was granted during setup and then **removed**; no remaining role carries delete. [ADR-0005](decisions/0005-staging-bucket-without-delete.md) |
| Speech-to-Text v2 / Chirp 3 | **yes** | `roles/speech.client`, API enabled; recognizer `projects/shir-sitevisit/locations/us/recognizers/_` |
| Vertex AI (`gemini-2.5-flash`, `us-central1`) | **yes** | `roles/aiplatform.user`, API enabled, `google-genai` SDK |
| Sheets: read + append/update on the catalog Sheet | **yes** | Sheet `158eA2K5FgGc4dQ43xHxdTuri-KOwPSuNn8qQqsasBy0` is owned by `dmyers@shircapital.com` and shared to the SA as **writer** |
| Sheets: delete a row or a tab | **no** | the code never issues a delete, and never touches the default `Sheet1` |

Net effect: this identity can **read** the source, **create** derived artifacts, and
**update** one catalog row per asset. It can destroy nothing.

## Prohibited patterns

These are hard rules, not preferences. Each one has been checked.

- **No service-account key file.** Do not create, download, commit, mount, or reference
  one. `GOOGLE_APPLICATION_CREDENTIALS` must never be set in the job, in `.env.example`,
  or in a local `.env` used against real resources. An earlier local template carried a
  `./secrets/gcp-service-account.json` line; it was removed and must not return.
- **No impersonation.** No `--impersonate-service-account`, no
  `roles/iam.serviceAccountTokenCreator` chain in the processing path. The job uses
  direct attachment and the credential factory verifies the attached identity.
- **No personal Drive OAuth on the media path.** Do not run `gcloud auth
  application-default login` and then point a media command at the real folder. A human
  identity reading the media would defeat the whole authorization record.
- **No widening to fix a failure.** Do not grant a delete role, do not add Shared Drive
  membership, do not broaden a Drive share from folder to drive. If a stage genuinely
  needs more access, that is an ADR.
- **No secrets in the repo.** Never commit service-account keys, OAuth refresh/access
  tokens, API keys, or Drive file content. Keep local credential paths and `.env` files
  outside Git tracking.

`SITE_VISIT_ENVIRONMENT=deployed` enforces part of this in code: it refuses to start
under any runtime identity other than the designated service account, which is pinned as
a constant in `src/site_visit_workflow/config.py`.

## Minimum permissions

| Service | Minimum capability |
| --- | --- |
| Google Drive | List immediate folder contents and read/download approved source media; no delete. Rename capability exists but is never exercised without an approval record |
| Cloud Storage | Create/read objects in the dedicated staging prefix; retain artifacts; **no delete** |
| Speech-to-Text v2 | Submit and read BatchRecognize operations and access the configured recognizer/model in the `us` multi-region |
| Vertex AI | Invoke the approved extraction model (`gemini-2.5-flash`, `us-central1`) |
| Google Sheets | Read the target schema and create/update draft rows by idempotent key |

## Security rules

- Never commit service-account keys, OAuth refresh/access tokens, API keys, or Drive file content.
- Prefer Application Default Credentials or workload identity over key files.
- Keep local credential paths and `.env` files outside Git tracking.
- Record permission changes and their rationale in an ADR.
- Preserve Drive source media, original name, and Drive ID as immutable evidence.

## Re-verifying with `auth-preflight`

`site-visit auth-preflight` is strictly read-only: metadata and capability inspection
only. It downloads no media and mutates nothing. Each check captures its own sanitized
error, so one failure does not hide the rest.

```powershell
gcloud run jobs execute site-visit-workflow `
  --project=shir-sitevisit --region=us-central1 --wait `
  --args=auth-preflight

gcloud logging read `
  'resource.type="cloud_run_job" AND resource.labels.job_name="site-visit-workflow"' `
  --project=shir-sitevisit --limit=200 --format="value(textPayload)"
```

It emits one JSON record with these sections — and this is what to check in each:

| Section | What to confirm |
| --- | --- |
| `runtime_environment` | Python and installed client-library versions; `ffmpeg`/`ffprobe` present |
| `identity` | `matches_designated_identity: true`, and `credential_class` is a compute/metadata credential — **not** a `ServiceAccountCredentials` loaded from a file |
| `drive` | The folder resolves; capabilities show `canDownload: true` and `canDelete: false`; the child listing matches the folder |
| `cloud_storage` | Bucket exists; `permissions_held` includes `storage.objects.create`, `.get`, `.list` and **excludes** `storage.objects.delete` |
| `sheets` | The configured Sheet is reachable and writable |
| `catalog_sheet_creation` | Reports why a Sheet was or was not created; the operator-owned Sheet is the sanctioned arrangement |

Run it after any identity, folder, bucket, Sheet, or IAM change, and before the first
`process-folder` of a new configuration. Record a material change as a **new** dated
evidence folder under `docs/evidence/`; never overwrite an existing one.

## Drive access recovery

Before any explicit intake or `process-folder` command, confirm that the configured
service account has been shared on the single approved folder, and follow
[Drive HTTP 403 recovery](RUNBOOKS/drive-access-recovery.md) if access fails.

> **Historical note (superseded).** This section previously read "No live cloud or Drive
> test is claimed by this repository." That is no longer true: live, read-only Drive,
> GCS and Sheets checks were executed from the deployed job on 2026-09-17 and are
> recorded in `docs/evidence/20260917T055321Z-phase2-auth-preflight/`.

Follow [Drive HTTP 403 recovery](RUNBOOKS/drive-access-recovery.md) before changing permissions. It separates browser-access, metadata-only OAuth, and Shared Drive checks and records the exact non-secret evidence needed to resolve the failure. Do not substitute a different folder or bypass the approval boundary.

## How to update this later

Revise this document with validated role names and scope choices. Re-review
least privilege whenever another API or output destination is introduced. When a
capability in the can/cannot table changes, cite the dated preflight evidence folder that
established it, and update `docs/SETUP.md` and the relevant ADR in the same change.
