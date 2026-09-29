# Cloud Scheduler → Cloud Run Jobs (pulled 2026-09-29)

Source: https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule (page updated 2026-09-29)

Confirmed command shape:

```
gcloud scheduler jobs create http NAME --location REGION --schedule "CRON" \
  --time-zone "America/New_York" \
  --uri "https://run.googleapis.com/v2/projects/PROJECT_ID/locations/REGION/jobs/JOB:run" \
  --http-method POST --oauth-service-account-email INVOKER_SA
```

- Auth is **OAuth** (not OIDC) to `run.googleapis.com`.
- The invoker SA needs `roles/run.invoker` on the job (scoped to the one job here).
- The creator needs `roles/cloudscheduler.admin` (or `cloudscheduler.jobs.create`) and
  `iam.serviceAccountUser` on the invoker SA.
- Arg overrides in the request body were not documented on that page; this build avoids them by
  giving the nightly job (`site-visit-nightly`) its own standing args.

No client library involved (gcloud + REST only).
