# Secret Manager + Cloud Run Jobs secrets (pulled 2026-10-08)

Sources (all "last updated 2026-10-07"):
- https://docs.cloud.google.com/run/docs/configuring/jobs/secrets
- https://docs.cloud.google.com/secret-manager/docs/creating-and-accessing-secrets
- https://docs.cloud.google.com/secret-manager/docs/add-secret-version
- https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule (re-pulled; unchanged from cloud-scheduler-run-jobs.md)

Confirmed:
- Create: `gcloud secrets create ID --replication-policy=automatic`
- Add version from stdin: `... | gcloud secrets versions add ID --data-file=-`; use a no-newline
  writer (`printf '%s'`). Passing the value on the command line is discouraged (process list, history).
- Job env from secret: `--set-secrets ENV=SECRET:VERSION` (comma-separated pairs) on
  `gcloud run jobs create|update` (this repo also uses `deploy`, which accepts the same flag).
- **Pin a numbered version** for env-var secrets (resolved at instance start), not `latest`.
- Job SA needs `roles/secretmanager.secretAccessor`; deployer needs `roles/run.admin` +
  `roles/iam.serviceAccountUser` on the SA.
- Scheduler: `gcloud scheduler jobs create http ... --uri=https://run.googleapis.com/v2/projects/P/locations/R/jobs/J:run --http-method=POST --oauth-service-account-email=SA`; invoker SA needs `roles/run.invoker` on the job.

No client library: gcloud + REST only. The app reads plain env vars (`appfolio.load_credentials`).
