# Goal: Direct Service Account Drive Read

## User Request

Connect the existing service account to read the working Drive folder files,
document the exact repeatable steps, and report once complete. The workflow
must be live, run directly as the service account, and must not use
service-account impersonation.

## Refined Goal

Deploy and execute one manually invoked Cloud Run Job in project
`shir-sitevisit` that runs directly as
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`. The job must
perform only a read-only listing of the immediate child folders of Drive folder
`1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF` and retain durable, non-secret execution
evidence. Remove local impersonation from the live workflow path and document
the exact direct-service-account deployment and verification procedure for
future operators.

## Acceptance Criteria

- [ ] A deployed Cloud Run Job is configured with
  `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` as its direct
  service identity, contains no `GOOGLE_APPLICATION_CREDENTIALS` setting, and
  does not use service-account impersonation.
- [ ] One manually invoked job execution completes a read-only `list-visits`
  request against Drive folder `1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF`, reporting
  only immediate child folder metadata or a clear Drive authorization error.
- [ ] The live connection/listing completes within three minutes. If it does
  not, stop waiting, record the job status and diagnostics, and do not advance.
- [ ] The repository records repeatable direct-runtime setup, deploy,
  configuration-inspection, execution, evidence-retention, and rollback steps,
  including the actual non-secret execution outcome.
- [ ] The live workflow has no service-account-key path and no
  `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` configuration/code path.
- [ ] `python -m pytest` passes and `git diff --check` reports no errors.

## Scope Boundaries

**In scope:**

- Existing `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`
  identity only.
- Cloud Run Job build, deployment/update, configuration inspection, and one
  manual `list-visits` execution.
- Read-only Drive listing of the exact test folder.
- Durable non-secret logs/evidence and direct-runtime documentation.

**Out of scope:**

- Service-account creation, user-managed keys, local impersonation, or personal
  Drive credentials.
- Media download, manifests, ffprobe/ffmpeg, GCS uploads, transcription,
  Vertex AI, Sheets writes, Drive renames, reports, scheduling, retries, or
  multi-folder automation.
- Changing Drive content, sharing permissions, or Google Cloud IAM roles.

## Applicable Project Conventions

**Quality gate command:**

- `python -m pytest`
- `git diff --check`

**Commit convention:**

- Conventional commits (observed: `chore: initialize live workflow foundation`)
- Builder title: `type(scope): [B] description`, 72 characters or fewer
- Inspector title: `chore(scope): [I] description`, 72 characters or fewer
- Builder trailer: `Assisted-by: OpenAI:GPT-5.6 Luna`
- Inspector trailer: `Assisted-by: OpenAI:GPT-5.6 Sol`

**Guidelines:**

- No `AGENTS.md`, `CONSTITUTION.md`, `.agents/guidelines/`, or
  `.github/guidelines/` files exist.

**Rules:**

- `docs/` is the canonical operating record.
- Google is contacted only by explicit CLI commands.
- The deployed workload must attach the designated service account directly and
  must use no key file or impersonation.
- Inspect the deployed Cloud Run Job identity/configuration before its first
  Google-contacting execution.
- Preserve human review gates; do not advance beyond read-only discovery.
