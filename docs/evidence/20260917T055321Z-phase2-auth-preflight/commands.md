# Command ledger — Phase 2 authorization preflight

**Run ID:** `20260917T055321Z-phase2-auth-preflight`
**Deployer identity:** `dmyers@shircapital.com` (inspection and deployment only)
**Runtime identity for all Google Drive/GCS/Sheets API calls:**
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`

No secrets, tokens, keys, or credentials appear in this ledger.

| UTC time | Exact command or configuration check | Executed by identity | Target system | Read/write/mutate | Result | Sanitized output/error | Evidence link |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 05:52 | `gcloud run jobs describe site-visit-workflow --project=shir-sitevisit --region=us-central1 --format=yaml` | deployer | Cloud Run | read | OK | `serviceAccountName: site-visit-workflow@…`; no volumes/secrets/`GOOGLE_APPLICATION_CREDENTIALS` | `raw/job-describe.yaml` |
| 05:53 | `gcloud services list --enabled --project=shir-sitevisit` | deployer | Service Usage | read | OK | Drive/Run/Build/AR/Storage/Speech/Vertex/ServiceUsage enabled; **Sheets disabled** | `raw/apis-enabled.txt` |
| 05:54 | `gcloud projects get-iam-policy shir-sitevisit --format=json` | deployer | IAM | read | OK | SA held only `roles/aiplatform.user`, `roles/speech.client` | `raw/project-iam-policy.json` |
| 05:55 | `gcloud storage buckets list --project=shir-sitevisit` | deployer | GCS | read | OK | Only `shir-sitevisit-pilot`, `shir-sitevisit_cloudbuild`; no staging bucket | `raw/buckets.txt` |
| 05:55 | `gcloud iam service-accounts keys list --iam-account=site-visit-workflow@… --managed-by=user` | deployer | IAM | read | OK | `Listed 0 items.` — no user-managed keys exist | — |
| 05:56 | `gcloud builds submit --config=infra/cloudbuild.yaml --substitutions=_IMAGE=…:preflight-20260917 .` | deployer | Cloud Build | write (image) | SUCCESS | Build `9f54fbd8…` | — |
| 05:58 | `gcloud run jobs deploy site-visit-workflow … --args=auth-preflight --service-account=site-visit-workflow@…` | deployer | Cloud Run | mutate (job config) | SUCCESS | SA attached; `maxRetries 0` | — |
| 05:58 | `gcloud run jobs execute site-visit-workflow --async` | deployer → runs as SA | Cloud Run | read (Drive) | SUCCESS | Output lost to Cloud Logging line-drop; rerun required | exec `bhs2h` |
| 06:03 | `gcloud builds submit … :preflight-20260917-r2` | deployer | Cloud Build | write (image) | SUCCESS | Build `89991bf6…` | — |
| 06:05 | `gcloud run jobs execute site-visit-workflow --async` | deployer → runs as SA | Cloud Run | read | SUCCESS | Single 25 KB log line dropped entirely by Cloud Logging | exec `nnfpk` |
| 06:09 | `gcloud builds submit … :preflight-20260917-r3` | deployer | Cloud Build | write (image) | SUCCESS | Build `fc394d41…` | — |
| 06:14 | `gh auth status` / `gh repo view dmyers1101/Site-Visit-Live-Workflow` | deployer | GitHub | read | OK | Logged in as `dmyers1101`; scopes `gist, read:org, repo`; `viewerPermission: ADMIN` | — |
| 06:15 | `git rev-parse --abbrev-ref --symbolic-full-name @{u}` | deployer | Git | read | ERROR | `fatal: no upstream configured for branch 'agents/pasted-text-processing'` — 2 commits unpushed | — |
| 06:16 | `gcloud builds log fc394d41-… \| grep "Successfully installed"` | deployer | Cloud Build | read | OK | `google-api-python-client 2.200.0`, `google-auth 2.58.0`, `google-cloud-speech 2.40.0`, `google-cloud-storage 3.14.1` | — |
| 06:17 | WebFetch `docs.cloud.google.com/speech-to-text/v2/docs/chirp_3-model` | deployer | Google docs | read | OK | Model id `chirp_3`; recognizer `projects/{p}/locations/{region}/recognizers/_`; **served from `us`/`eu` multi-regions**; BatchRecognize + GCS supported | `../../research/gcp/speech-to-text-v2.md` |
| 06:18 | WebSearch — Vertex Gemini model IDs / structured output | deployer | Google docs | read | OK | `gemini-2.5-flash` available; `response_mime_type` + `response_schema` for strict JSON | — |
| 06:20 | `gcloud storage buckets create gs://shir-sitevisit-staging --location=us --uniform-bucket-level-access` | deployer | GCS | **mutate (approved)** | SUCCESS | Bucket created, US, UBLA on | — |
| 06:20 | `gcloud storage buckets add-iam-policy-binding … --role=roles/storage.objectUser` | deployer | IAM | **mutate (approved)** | SUCCESS | Later reverted — this role includes `storage.objects.delete` | — |
| 06:20 | `gcloud services enable sheets.googleapis.com --project=shir-sitevisit` | deployer | Service Usage | **mutate (approved)** | SUCCESS | Sheets API now enabled | — |
| 06:21 | `gcloud storage buckets add-iam-policy-binding … --role=roles/storage.objectCreator` and `…objectViewer`; `remove-iam-policy-binding … --role=roles/storage.objectUser` | deployer | IAM | **mutate (approved)** | SUCCESS | Delete permission removed; create + read retained | — |
| 06:21 | `gcloud builds submit … :preflight-final` | deployer | Cloud Build | write (image) | SUCCESS | Build `d7fd83ec…`; `google-genai 2.24.0` installed | — |
| 06:24 | `gcloud run jobs deploy … --memory=1Gi --task-timeout=600s --set-env-vars=…,GCS_STAGING_BUCKET=shir-sitevisit-staging,CREATE_CATALOG_SHEET=true` | deployer | Cloud Run | mutate (job config) | SUCCESS | SA attached; no key/impersonation | — |
| 06:24 | `gcloud run jobs execute site-visit-workflow --async` | deployer → **runs as SA** | Drive / GCS / Sheets | read (+1 approved conditional write, not triggered) | SUCCESS | Identity match `true`; folder ok; 19 files; `canDownload true`, `canDelete false`; GCS 403 on `storage.buckets.get`; Sheet creation refused (no Shared Drive ID) | exec `lhplp`, `raw/preflight-raw.json` |
| 06:28 | `gcloud storage buckets add-iam-policy-binding … --role=roles/storage.legacyBucketReader` | deployer | IAM | **mutate (approved)** | SUCCESS | Resolves the `storage.buckets.get` 403 | — |

## Sanitized errors worth preserving

1. **Shared Drive enumeration** — `HTTP 404: Shared drive not found: 0AGzXWk46WhgyUk9PVA`.
   Cause: the SA is shared on the folder only, not a member of the Shared Drive.
   This is the least-privilege state and is acceptable.
2. **GCS bucket metadata** — `403 … does not have storage.buckets.get access to
   the Google Cloud Storage bucket`. Cause: `objectCreator`/`objectViewer` do not
   include bucket-level metadata read. Resolved by granting
   `roles/storage.legacyBucketReader`.
3. **Catalog Sheet creation** — refused by our own guard:
   `No Shared Drive ID resolved; refusing to create in SA My Drive.`

## How to update this later

Append to this ledger for any follow-up check in this run. Start a new run
directory and a new ledger for a future preflight.
