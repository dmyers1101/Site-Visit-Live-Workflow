# Direct service-account Drive read — evidence

**Date:** 2026-09-16 (execution timestamps in UTC fall on 2026-09-17)
**Status:** SUCCESS — Definition of Done #1 met.

The deployed Cloud Run Job executed with the designated service account attached
directly and successfully read the immediate children of the target Drive folder.

## Outcome

| Item | Value |
| --- | --- |
| Result | **Drive listing succeeded** |
| Project | `shir-sitevisit` (number `847827326811`) |
| Region | `us-central1` |
| Workload | Cloud Run Job `site-visit-workflow` |
| Execution ID | `site-visit-workflow-vrrr2` |
| Image | `us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:direct-sa-20260916-r3` |
| Image digest | `sha256:0d8dfef3136d07422af1215d26c8648e7843b8e00a91665f032ae94e322220f3` |
| Cloud Build ID | `3ebf5f9b-ef13-4d4c-8fd8-da3e35f41a3f` |
| Attached service account | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` |
| Target Drive folder ID | `1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF` |
| Execution started | `2026-09-17T04:36:15Z` |
| Task started | `2026-09-17T04:36:37Z` |
| Completed | `2026-09-17T04:38:36Z` (1m58.69s task; 2m21s wall from start) |
| Within 3-minute ceiling | Yes |
| Container exit code | `0` |
| Immediate children returned | 19 |

## Credential assurance

Explicit confirmation, verified against the live deployed configuration:

- **No personal Google Drive OAuth identity was used.** The Drive request
  originated inside the deployed Cloud Run task, authenticated by the Cloud Run
  metadata server as the attached service account.
- **No service-account impersonation.** No `--impersonate-service-account` flag
  was used, and the job spec contains no impersonation configuration.
- **No service-account JSON key was created, downloaded, or used.**
  `gcloud iam service-accounts keys list --managed-by=user` returned
  `Listed 0 items.` for the service account.
- **No key-file credential setting exists.** The job spec contains no
  `GOOGLE_APPLICATION_CREDENTIALS` variable, no mounted secrets, and no volumes.
- **No second service account was created.** The pre-existing
  `site-visit-workflow` account was used unchanged.
- **No Drive item was renamed, moved, downloaded, uploaded, modified, or
  deleted.** The only Drive call issued was a read-only `files.list`.
- The workload additionally self-verifies its identity at runtime:
  `runtime_credentials()` in `src/site_visit_workflow/google.py` refuses to
  proceed unless the resolved credential's `service_account_email` matches
  `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`.

## One configuration change made (reported and approved beforehand)

The first execution (`site-visit-workflow-m7wc6`) failed with this exact,
specific Drive error:

```
HttpError 403 ... "Google Drive API has not been used in project 847827326811
before or it is disabled." reason: 'accessNotConfigured', domain: 'usageLimits'
```

This was reported before any change was made, and the fix was approved:

```bash
gcloud services enable drive.googleapis.com --project=shir-sitevisit
```

This enabled an API only. **No IAM policy binding and no Drive sharing setting
was changed.** The service account already had the necessary Drive access to the
target folder, which the successful listing confirms.

## Pre-execution inspection (required step)

```bash
gcloud run jobs describe site-visit-workflow \
  --project=shir-sitevisit --region=us-central1 --format=yaml
```

Confirmed before executing:

- `serviceAccountName: site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`
- `args: [list-folder-children]`, `command: [site-visit]`
- `maxRetries: 0`, `taskCount: 1`, `parallelism: 1`, `timeoutSeconds: '180'`
- `SITE_VISIT_ENVIRONMENT=deployed`, `DRIVE_SHARED_FOLDER_ID=1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF`
- No volumes, no secrets, no `GOOGLE_APPLICATION_CREDENTIALS`

```bash
gcloud iam service-accounts keys list \
  --iam-account=site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com \
  --managed-by=user --project=shir-sitevisit
# -> Listed 0 items.
```

## Exact commands run

```bash
# 1. Enable the Drive API (the one approved change)
gcloud services enable drive.googleapis.com --project=shir-sitevisit

# 2. Build and push the image
gcloud builds submit --project=shir-sitevisit \
  --config=infra/cloudbuild.yaml \
  --substitutions=_IMAGE=us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:direct-sa-20260916-r3 .

# 3. Deploy the job with the service account attached directly
gcloud run jobs deploy site-visit-workflow --project=shir-sitevisit \
  --region=us-central1 \
  --image=us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:direct-sa-20260916-r3 \
  --service-account=site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com \
  --command=site-visit --args=list-folder-children \
  --tasks=1 --parallelism=1 --max-retries=0 --task-timeout=180s \
  --set-env-vars=SITE_VISIT_ENVIRONMENT=deployed,GOOGLE_CLOUD_PROJECT=shir-sitevisit,DRIVE_SHARED_FOLDER_ID=1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF,SITE_VISIT_RUNTIME_SERVICE_ACCOUNT=site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com

# 4. Inspect before executing
gcloud run jobs describe site-visit-workflow --project=shir-sitevisit \
  --region=us-central1 --format=yaml

# 5. Execute exactly once
gcloud run jobs execute site-visit-workflow --project=shir-sitevisit \
  --region=us-central1 --async

# 6. Read status and output
gcloud run jobs executions describe site-visit-workflow-vrrr2 \
  --project=shir-sitevisit --region=us-central1 --format=yaml
gcloud logging read 'resource.type="cloud_run_job" AND labels."run.googleapis.com/execution_name"="site-visit-workflow-vrrr2"' \
  --project=shir-sitevisit --limit=500 --order=asc --format="value(textPayload)"
```

## Drive API call issued

Exactly one read-only call, `drive.files.list` (Drive API v3):

```
q=<folderId> in parents and trashed = false
spaces=drive
fields=nextPageToken,files(id,name,mimeType,webViewLink,size,modifiedTime)
supportsAllDrives=true
includeItemsFromAllDrives=true
pageSize=100
```

## Immediate child metadata returned

Metadata only. No media content was read, downloaded, or processed.

| # | name | Drive ID | MIME type | Drive link |
| --- | --- | --- | --- | --- |
| 1 | `IMG_3651.MOV` | `1p-9pppEYKrgVPVIlG-dSp9Df7u4EstOw` | `video/quicktime` | [open](https://drive.google.com/file/d/1p-9pppEYKrgVPVIlG-dSp9Df7u4EstOw/view?usp=drivesdk) |
| 2 | `IMG_3650.MOV` | `1xAsMvY129zKNHEJkSkekbyIT1HwTjZ-5` | `video/quicktime` | [open](https://drive.google.com/file/d/1xAsMvY129zKNHEJkSkekbyIT1HwTjZ-5/view?usp=drivesdk) |
| 3 | `IMG_3653.MOV` | `19APrhXj5hKEd0FMiAXfJxvLwtAksE_Km` | `video/quicktime` | [open](https://drive.google.com/file/d/19APrhXj5hKEd0FMiAXfJxvLwtAksE_Km/view?usp=drivesdk) |
| 4 | `IMG_3655.MOV` | `15MSI4CAuiWRGBxoiYnyW7l5tyo2DEaAD` | `video/quicktime` | [open](https://drive.google.com/file/d/15MSI4CAuiWRGBxoiYnyW7l5tyo2DEaAD/view?usp=drivesdk) |
| 5 | `IMG_3656.MOV` | `1G0PFnVar7X7mAFAB3CrlB6pS29VgKjZr` | `video/quicktime` | [open](https://drive.google.com/file/d/1G0PFnVar7X7mAFAB3CrlB6pS29VgKjZr/view?usp=drivesdk) |
| 6 | `IMG_3657.MOV` | `1YvJ0kftlgbMoi2yzcXGmCG1LFNryu4KA` | `video/quicktime` | [open](https://drive.google.com/file/d/1YvJ0kftlgbMoi2yzcXGmCG1LFNryu4KA/view?usp=drivesdk) |
| 7 | `IMG_3667.MOV` | `1bdvj5-sPHWIes1N2EpXHc_a9fSW9YDeJ` | `video/quicktime` | [open](https://drive.google.com/file/d/1bdvj5-sPHWIes1N2EpXHc_a9fSW9YDeJ/view?usp=drivesdk) |
| 8 | `IMG_3654.MOV` | `138LpQaFUhXYyisEDCvryac4Ux7-QWXnt` | `video/quicktime` | [open](https://drive.google.com/file/d/138LpQaFUhXYyisEDCvryac4Ux7-QWXnt/view?usp=drivesdk) |
| 9 | `IMG_3668.MOV` | `10NV-GdosSRy-ImsM_Pfl4SJjQoIDvJrj` | `video/quicktime` | [open](https://drive.google.com/file/d/10NV-GdosSRy-ImsM_Pfl4SJjQoIDvJrj/view?usp=drivesdk) |
| 10 | `IMG_3652.MOV` | `1DePF0BQnVFWsZlaPbYRLCvIfSjNPZJ3E` | `video/quicktime` | [open](https://drive.google.com/file/d/1DePF0BQnVFWsZlaPbYRLCvIfSjNPZJ3E/view?usp=drivesdk) |
| 11 | `IMG_3658.MOV` | `1WKVsHTQS8T8SwcmEl0Awn2WQiktfDcXo` | `video/quicktime` | [open](https://drive.google.com/file/d/1WKVsHTQS8T8SwcmEl0Awn2WQiktfDcXo/view?usp=drivesdk) |
| 12 | `IMG_3664.MOV` | `1P3n_Mf3ozlrzn8I96adf2z7f1U9wI3Yt` | `video/quicktime` | [open](https://drive.google.com/file/d/1P3n_Mf3ozlrzn8I96adf2z7f1U9wI3Yt/view?usp=drivesdk) |
| 13 | `IMG_3666.MOV` | `1UsWhVbxTZCErBr8BCyuD4w-eAc9Qz5pb` | `video/quicktime` | [open](https://drive.google.com/file/d/1UsWhVbxTZCErBr8BCyuD4w-eAc9Qz5pb/view?usp=drivesdk) |
| 14 | `IMG_3661.MOV` | `1EaaGxce15IJmtKU-9paYkAyiJKdTyPTT` | `video/quicktime` | [open](https://drive.google.com/file/d/1EaaGxce15IJmtKU-9paYkAyiJKdTyPTT/view?usp=drivesdk) |
| 15 | `IMG_3665.MOV` | `1SkUMgeXIXHMvciQ5gc9iwj868OtoEzM8` | `video/quicktime` | [open](https://drive.google.com/file/d/1SkUMgeXIXHMvciQ5gc9iwj868OtoEzM8/view?usp=drivesdk) |
| 16 | `IMG_3662.MOV` | `1pGXzxmWLKCryutoH6-IZcBQONWMFuOGK` | `video/quicktime` | [open](https://drive.google.com/file/d/1pGXzxmWLKCryutoH6-IZcBQONWMFuOGK/view?usp=drivesdk) |
| 17 | `IMG_3663.HEIC` | `1La2hU5Q5a1umoJ6IipQR8DM1k992aBl6` | `image/heif` | [open](https://drive.google.com/file/d/1La2hU5Q5a1umoJ6IipQR8DM1k992aBl6/view?usp=drivesdk) |
| 18 | `IMG_3660.HEIC` | `1AS9KnGN1JojU2WN0IUfV4Uf1maWm4ILU` | `image/heif` | [open](https://drive.google.com/file/d/1AS9KnGN1JojU2WN0IUfV4Uf1maWm4ILU/view?usp=drivesdk) |
| 19 | `IMG_3659.HEIC` | `1w7OBl4e5eiyQ4yBqRihISFTppzfO4fN9` | `image/heif` | [open](https://drive.google.com/file/d/1w7OBl4e5eiyQ4yBqRihISFTppzfO4fN9/view?usp=drivesdk) |
Summary: 16 × `video/quicktime` (`.MOV`), 3 × `image/heif` (`.HEIC`).
No sub-folders are present, so the earlier folder-only `list-visits` command
would have returned an empty list against this folder; `list-folder-children`
was added to return every immediate child with its MIME type.

## Where this runs

- **Runs as:** `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`
- **Scheduled:** nowhere — this is a **manually invoked** Cloud Run Job. No
  Cloud Scheduler trigger, no Routine, and nothing scheduled on a local machine.
- **Output written to:** Cloud Logging only (stdout of the job). Nothing is
  written to Drive, GCS, or Sheets by this command.
- **Source of record:** this repository, under the company Google Drive path
  `My Drive/Site Visit App/apps/live-workflow…`.

## Repeatable procedure for future runs

The job is already deployed. To re-run the same read-only check:

```bash
gcloud run jobs describe site-visit-workflow --project=shir-sitevisit \
  --region=us-central1 --format=yaml   # confirm SA, no secrets, no key file

EXEC=$(gcloud run jobs execute site-visit-workflow --project=shir-sitevisit \
  --region=us-central1 --async --format="value(metadata.name)")

gcloud run jobs executions describe "$EXEC" --project=shir-sitevisit \
  --region=us-central1 --format="value(status.succeededCount,status.failedCount)"

gcloud logging read "resource.type=\"cloud_run_job\" AND labels.\"run.googleapis.com/execution_name\"=\"$EXEC\"" \
  --project=shir-sitevisit --limit=500 --order=asc --format="value(textPayload)"
```

To point at a different folder, redeploy with a new `DRIVE_SHARED_FOLDER_ID`.
Do not substitute a local credential, key file, impersonation, or personal
identity.

Note: allow roughly 2–3 minutes of wall-clock time; container provisioning took
about 2 minutes before the task itself started. Status is confirmed via
`status.succeededCount`, not `status.completionStatus`, which is not populated
by this API version.

## Rollback / removal

```bash
# Remove the Cloud Run Job
gcloud run jobs delete site-visit-workflow --project=shir-sitevisit \
  --region=us-central1 --quiet

# Remove the image tag built for this verification
gcloud artifacts docker images delete \
  us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:direct-sa-20260916-r3 \
  --project=shir-sitevisit --quiet

# Optional: remove the whole Artifact Registry repository
gcloud artifacts repositories delete site-visit-workflow \
  --project=shir-sitevisit --location=us-central1 --quiet

# Optional: disable the Drive API again (reverts the one change made here)
gcloud services disable drive.googleapis.com --project=shir-sitevisit
```
