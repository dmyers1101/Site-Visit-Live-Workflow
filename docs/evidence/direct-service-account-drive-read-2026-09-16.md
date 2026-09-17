# Direct service-account Drive read evidence

## Outcome

**Blocked before deployment and execution.** No Drive request was issued from
the workstation, and no Drive file contents or metadata were recorded.

## Non-secret diagnostics

- Project: `shir-sitevisit`
- Intended job: `site-visit-workflow`
- Intended region: `us-central1`
- Intended direct identity:
  `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`
- Intended read-only folder:
  `1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF`
- Service-account description succeeded; the account exists and is enabled.
- Cloud Run, Artifact Registry, and Cloud Build APIs were enabled.
- Artifact Registry repository `site-visit-workflow` was created.
- `gcloud builds submit` failed before a build was created:
  `PERMISSION_DENIED: The caller does not have permission`.
- The direct-identity Cloud Run Job deployment was attempted with one task,
  one-way parallelism, zero retries, and a 180-second timeout. It failed with:
  `Image 'us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:direct-sa-20260916' not found.`
- Consequently, there was no deployed job to inspect or execute, and no
  `list-visits` execution was started. The three-minute execution ceiling was
  not entered.

## Required continuation

An operator with permission to create Cloud Builds must rebuild and publish the
image, then inspect the job configuration before the single manual execution:

```powershell
gcloud builds submit --project=shir-sitevisit `
  --config=infra/cloudbuild.yaml `
  --substitutions=_IMAGE=us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:direct-sa-20260916 .

gcloud run jobs deploy site-visit-workflow --project=shir-sitevisit `
  --region=us-central1 `
  --image=us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:direct-sa-20260916 `
  --service-account=site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com `
  --command=site-visit --args=list-visits --tasks=1 --parallelism=1 `
  --max-retries=0 --task-timeout=180s `
  --set-env-vars=SITE_VISIT_ENVIRONMENT=deployed,GOOGLE_CLOUD_PROJECT=shir-sitevisit,DRIVE_SHARED_FOLDER_ID=1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF,SITE_VISIT_RUNTIME_SERVICE_ACCOUNT=site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com

gcloud run jobs describe site-visit-workflow --project=shir-sitevisit `
  --region=us-central1 --format=yaml
gcloud run jobs execute site-visit-workflow --project=shir-sitevisit `
  --region=us-central1 --wait
```

Do not substitute a local credential, key, impersonation, folder, or command.
