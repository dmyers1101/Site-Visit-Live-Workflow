# Cloud Run Job deployment

## Purpose

Run the Site Visit workflow in Cloud Run Jobs without key files. The deployed workload
uses the existing service account
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` directly, via ambient ADC
from the metadata server.

All media processing happens inside this job. Nothing is downloaded to an operator
workstation at any point.

## Named values used below

| Name | Real value |
| --- | --- |
| Project | `shir-sitevisit` |
| Region | `us-central1` |
| Job name | `site-visit-workflow` |
| Artifact Registry repo | `site-visit-workflow` |
| Image | `us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:latest` |
| Runtime SA | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` |
| Drive folder | `1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF` |
| Staging bucket | `shir-sitevisit-staging` |
| Catalog Sheet | `158eA2K5FgGc4dQ43xHxdTuri-KOwPSuNn8qQqsasBy0` |

## 1. Build the image

The image is Python 3.11.16 with ffmpeg 7.1.5 and ffprobe, entrypoint `site-visit`.

```powershell
gcloud builds submit --config=infra/cloudbuild.yaml `
  --project=shir-sitevisit `
  --substitutions=_IMAGE=us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:latest .
```

Prefer an immutable tag over `latest` for anything you want to reproduce — for example
`:20260917a`. Deploy that exact tag in step 2.

> **[OPEN] Known gap — the prompt files are not in the image.** `infra/Dockerfile` copies
> only `pyproject.toml`, `README.md` and `src/`. It does **not** copy `prompts/`, and the
> prompts are not declared as package data in `pyproject.toml`. `process-folder` reads
> `prompts/l1-extraction.md`, `l2-enrichment.md` and `l3-refinement.md` from
> `--prompts-dir` (default `prompts`, relative to the container `WORKDIR /app`) **at
> runtime**, and a missing prompt file is a hard stop. As built today, Gate 4 will
> therefore fail with "L1 prompt file is missing at runtime" on every asset; Gates 1–3
> still succeed, so `--dry-run` runs are unaffected. Fix by adding `COPY prompts ./prompts`
> to `infra/Dockerfile` (and rebuilding) before the first non-dry `process-folder` run.
> This file does not make that change — the image definition is outside this document's
> scope — but the gap is recorded here rather than left silent.

Placeholder variant for another environment:

```powershell
gcloud builds submit --config=infra/cloudbuild.yaml `
  --project=PROJECT_ID `
  --substitutions=_IMAGE=REGION-docker.pkg.dev/PROJECT_ID/REPO/site-visit:TAG .
```

If the Artifact Registry repo does not exist yet:

```powershell
gcloud artifacts repositories create site-visit-workflow `
  --repository-format=docker --location=us-central1 --project=shir-sitevisit
```

## 2. Deploy (create or update) the job

`gcloud run jobs deploy` creates the job if it is absent and updates it if it exists, so
this one command is safe to re-run.

```powershell
gcloud run jobs deploy site-visit-workflow `
  --image=us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:latest `
  --project=shir-sitevisit `
  --region=us-central1 `
  --service-account=site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com `
  --memory=8Gi --cpu=2 `
  --task-timeout=3600s `
  --max-retries=0 --tasks=1 --parallelism=1 `
  --set-env-vars=^"SITE_VISIT_ENVIRONMENT=deployed,SITE_VISIT_RUNTIME_SERVICE_ACCOUNT=site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com,GOOGLE_CLOUD_PROJECT=shir-sitevisit,GOOGLE_CLOUD_REGION=us-central1,DRIVE_SHARED_FOLDER_ID=1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF,GCS_STAGING_BUCKET=shir-sitevisit-staging,GCS_STAGING_PREFIX=site-visit-staging,CATALOG_SHEET_ID=158eA2K5FgGc4dQ43xHxdTuri-KOwPSuNn8qQqsasBy0,CATALOG_TAB_NAME=Catalog,SPEECH_LOCATION=us,SPEECH_MODEL=chirp_3,VERTEX_LOCATION=us-central1,VERTEX_MODEL=gemini-2.5-flash^"
```

Notes on that command:

- The env-var list contains `@` and `,`. In PowerShell the `^"…^"` quoting above keeps
  the whole list as one argument. If your shell fights you, use
  `--env-vars-file=env.yaml` instead (a plain `KEY: value` YAML map) — that avoids all
  delimiter escaping and is the recommended form for repeatable deploys. Do not commit a
  file containing anything secret; none of these values are secrets, but keep the habit.
- **`GOOGLE_APPLICATION_CREDENTIALS` is never set.** Setting it would break the
  key-free model.
- `RUN_ID` is deliberately not baked into the job. Pass it per execution with
  `--args=process-folder,--run-id,<id>`; otherwise the code generates a UTC stamp.

Placeholder variant for another environment:

```powershell
gcloud run jobs deploy JOB_NAME `
  --image=REGION-docker.pkg.dev/PROJECT_ID/REPO/site-visit:TAG `
  --project=PROJECT_ID --region=REGION `
  --service-account=RUNTIME_SA_EMAIL `
  --memory=8Gi --cpu=2 --task-timeout=3600s `
  --max-retries=0 --tasks=1 --parallelism=1 `
  --env-vars-file=env.yaml
```

with `env.yaml`:

```yaml
SITE_VISIT_ENVIRONMENT: deployed
SITE_VISIT_RUNTIME_SERVICE_ACCOUNT: RUNTIME_SA_EMAIL
GOOGLE_CLOUD_PROJECT: PROJECT_ID
GOOGLE_CLOUD_REGION: REGION
DRIVE_SHARED_FOLDER_ID: FOLDER_ID
GCS_STAGING_BUCKET: BUCKET_NAME
GCS_STAGING_PREFIX: site-visit-staging
CATALOG_SHEET_ID: SHEET_ID
CATALOG_TAB_NAME: Catalog
SPEECH_LOCATION: us
SPEECH_MODEL: chirp_3
VERTEX_LOCATION: us-central1
VERTEX_MODEL: gemini-2.5-flash
```

> `SITE_VISIT_ENVIRONMENT=deployed` refuses to start under any runtime identity other
> than `SITE_VISIT_RUNTIME_SERVICE_ACCOUNT`, and the designated account is pinned in
> `config.py`. Pointing this at a different service account requires a code change and
> an ADR, not just an env var.

## 3. Sizing: why 8Gi / 2 CPU / 3600s

**This matters and the old 1Gi / 600s configuration will fail.**

- On Cloud Run, `/tmp` is an **in-memory tmpfs**. Every byte the job stages — the
  downloaded source video plus the extracted WAV — counts against `--memory`, on top of
  the Python process itself.
- One source clip can be hundreds of MB, and the WAV adds roughly 1.9 MB per minute of
  audio (mono, 16 kHz, 16-bit PCM). The work directory is deliberately never cleaned up
  (this workflow deletes nothing), so a 16-video run accumulates **all** staged sources
  and WAVs in memory for the life of the execution.
- 1Gi will OOM. `--memory=8Gi --cpu=2` is the recommended floor for a full 16-video run.
- Timing: staging + ffmpeg + a Chirp `BatchRecognize` submit-and-poll + three Vertex
  calls + one Sheets upsert, sequentially, 16 times. A 600s task timeout cannot finish
  that. `--task-timeout=3600s` is the recommended value; the CLI's own Chirp poll
  timeout defaults to 1800s (`--poll-timeout-seconds`), so keep the task timeout at
  least that much larger than one asset's worst case.
- If memory is still tight, pass `--work-dir /mnt/work` with a mounted volume, or run in
  batches with `--limit`. [OPEN] No volume mount is configured today.
- Keep `--tasks=1 --parallelism=1 --max-retries=0`. The loop is sequential by design and
  a retry would re-run already-catalogued assets (harmless — the upsert is idempotent —
  but it wastes Chirp and Vertex calls and muddies the evidence trail).

## 4. Execute

Authorization proof first, every time you change identity, folder, bucket or Sheet:

```powershell
gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
  --args=auth-preflight
```

Read-only folder listing:

```powershell
gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
  --args=list-folder-children
```

Cheap trial — everything except Chirp, Vertex and Sheets:

```powershell
gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
  --args=process-folder,--dry-run,--limit,1
```

One real asset, end to end:

```powershell
gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
  --args=process-folder,--limit,1,--run-id,20260917-trial-01
```

The whole folder:

```powershell
gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
  --args=process-folder,--run-id,20260917-full-01
```

A single named asset (for a targeted re-run):

```powershell
gcloud run jobs execute site-visit-workflow --project=shir-sitevisit --region=us-central1 --wait `
  --args=process-folder,--asset-id,DRIVE_ASSET_ID,--run-id,20260917-repair-01
```

`--args` replaces the container arguments; the entrypoint is already `site-visit`, so
each element after `--args=` is one CLI token. Commas separate tokens, which is why
`--limit,1` is written as two elements.

Per-execution overrides are also available without redeploying:

```powershell
gcloud run jobs execute site-visit-workflow --region=us-central1 --wait `
  --args=process-folder `
  --update-env-vars=DRIVE_SHARED_FOLDER_ID=OTHER_FOLDER_ID
```

## Identity and safety

- Cloud Run obtains ADC from the attached service account; it uses no key file.
- `SITE_VISIT_ENVIRONMENT=deployed` rejects a different configured workload
  identity. The runtime credential factory verifies the attached identity.
- Local use must not be used for the live Drive validation. A personal Drive
  identity is never a deployed runtime identity.
- Configure one task and parallelism one; the loop processes one asset at a time.
- Drive read is granted. Rename and any Drive mutation still require their separate
  explicit approval records; `process-folder` never renames.
- The runtime identity cannot delete anything — no GCS delete role, Drive
  `canDelete: false`. A deploy that "fixes" this by adding a delete role needs an ADR.

## Verification

Verify the image with the offline tests first (`pytest`). After deployment, inspect the
job configuration before executing any Google-contacting command:

```powershell
gcloud run jobs describe site-visit-workflow --project=shir-sitevisit --region=us-central1
```

Check: the image tag, `serviceAccountName`, memory/CPU/task-timeout, the full env-var
list, and the **absence** of `GOOGLE_APPLICATION_CREDENTIALS`.

Then read the execution output:

```powershell
gcloud run jobs executions list --job=site-visit-workflow --region=us-central1 --limit=5
gcloud logging read `
  'resource.type="cloud_run_job" AND resource.labels.job_name="site-visit-workflow"' `
  --project=shir-sitevisit --limit=200 --format="value(textPayload)"
```

The job emits one JSON line per gate and a final `"gate": "run-summary"` record, so the
log is the running evidence.

> **Historical note (superseded).** An earlier revision of this section said to use a
> 180-second task timeout and that "This repository does not claim that a cloud
> deployment or cloud test has occurred." Both are obsolete: the job is deployed and has
> executed, and 180s is only ever adequate for the read-only `auth-preflight` and
> `list-folder-children` commands.

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

**Update, 2026-09-17:** those blockers were cleared. The image was built and published,
the job `site-visit-workflow` was deployed with the service account attached directly,
and it executed successfully four times (`vrrr2`, `bhs2h`, `nnfpk`, `lhplp`), performing
live read-only Drive, GCS and Sheets checks with no key file and no impersonation. See
[the Phase 2 authorization matrix](evidence/20260917T055321Z-phase2-auth-preflight/authorization-matrix.md).

## How to update this later

Version container, IAM, environment, and concurrency changes in the deployment
definition and amend the service-account runbook and ADR in the same review. If you
change the sizing guidance, say what run size it was measured against. Keep both the
real-value commands and the placeholder variants in this file — the real values are what
make the repo runnable, the placeholders are what make it portable.
