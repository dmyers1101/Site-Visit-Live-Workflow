# Cloud Run Job deployment

## Purpose

Run an explicitly invoked single-visit CLI command in Cloud Run Jobs without
key files. The deployed workload uses the existing service account
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` directly.

## Approach

Build the supplied Python 3.11/ffmpeg image from the repository root:

```powershell
gcloud builds submit --config=infra/cloudbuild.yaml `
  --substitutions=_IMAGE=REGION-docker.pkg.dev/shir-sitevisit/WORKFLOW/site-visit:TAG .
```

Create the job with the service account attachment, non-secret environment
variables, and no `GOOGLE_APPLICATION_CREDENTIALS` variable:

```powershell
gcloud run jobs create site-visit-workflow `
  --image=REGION-docker.pkg.dev/shir-sitevisit/WORKFLOW/site-visit:TAG `
  --region=us-central1 `
  --service-account=site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com `
  --set-env-vars=SITE_VISIT_ENVIRONMENT=deployed,GOOGLE_CLOUD_PROJECT=shir-sitevisit,DRIVE_SHARED_FOLDER_ID=FOLDER_ID,GCS_STAGING_BUCKET=BUCKET,GCS_STAGING_PREFIX=site-visit-staging,CATALOG_SHEET_ID=SHEET_ID `
  --max-retries=0 --tasks=1 --parallelism=1
```

Use a command/argument override for one explicit action, for example
`site-visit intake --visit-id VISIT_ID --output /workspace/manifest.json`.
Persist manifests and records to an approved durable location; Cloud Run's
local filesystem is ephemeral. Do not schedule the job until selection,
prompt approval, and human review procedures are approved.

## Identity and safety

- Cloud Run obtains ADC from the attached service account; it uses no key file.
- `SITE_VISIT_ENVIRONMENT=deployed` rejects a different configured workload
  identity. The runtime credential factory verifies the attached identity.
- Local use must not be used for the live Drive validation. A personal Drive
  identity is never a deployed runtime identity.
- Configure one task and parallelism one; each command handles only one asset.
- Grant Drive read access initially. Rename and Sheets publication require
  their separate explicit approval records and appropriate later permissions.

## Verification

Verify the image locally with offline tests first. After deployment, inspect
the Cloud Run Job configuration for the service-account attachment and
environment values before executing any Google-contacting command. This
repository does not claim that a cloud deployment or cloud test has occurred.

For the read-only folder check, use a 180-second task timeout and execute the
job exactly once:

```powershell
gcloud run jobs execute site-visit-workflow `
  --project=shir-sitevisit --region=us-central1 --wait
```

Inspect the execution and Cloud Logging output before retaining only the
immediate child folder metadata or the non-secret Drive authorization error.
Stop waiting at three minutes; record the execution status and diagnostics and
do not proceed to intake or media processing.

## Direct-runtime validation record

On 2026-09-16, the designated service account was confirmed to exist in
`shir-sitevisit`. The required Cloud Run, Artifact Registry, and Cloud Build
APIs were enabled, and the `site-visit-workflow` Artifact Registry repository
was created. The image build was then blocked by the deployer identity with
Cloud Build `PERMISSION_DENIED: The caller does not have permission`; no image
was published. A direct-identity Cloud Run Job deployment was attempted with
the exact folder ID and service account above, but Cloud Run rejected it because
the image was not found. Therefore no job was deployed or executed, no Drive
request was made, and no Drive file metadata was observed. See the durable
[execution evidence](evidence/direct-service-account-drive-read-2026-09-16.md).

## How to update this later

Version container, IAM, environment, and concurrency changes in the deployment
definition and amend the service-account runbook and ADR in the same review.
