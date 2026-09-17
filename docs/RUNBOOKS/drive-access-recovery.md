# Runbook: recover Drive access

## Purpose

Recover read access to the one configured Shared Folder without using a key
file, substituting a folder, or processing media. This repository records no
completed live Drive or cloud access test.

## Deployed workload

Cloud Run Jobs must attach
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` directly. Ask the
folder/Shared Drive manager to share only the configured folder with that
service-account address at the minimum read role. Do not create a
user-managed key or add edit permission to work around access failures.

## Local validation

1. Confirm `GOOGLE_CLOUD_PROJECT`, `DRIVE_SHARED_FOLDER_ID`, and
   `SITE_VISIT_RUNTIME_SERVICE_ACCOUNT` in untracked local configuration.
2. Run the read-only check from the Cloud Run Job directly attached to the
   designated service account. Do not use local credentials or impersonation.
   Local operator ADC is permitted only for development; it is never deployed
   as a personal Drive runtime identity.
3. Confirm the Drive API is enabled and that the service account is a folder
   member. Capture only timestamp, project, folder ID, HTTP status, and
   redacted error reason.
4. Run `site-visit intake --visit-id VISIT_ID --output manifest.json` only
   after the owner has selected an immediate child folder. The command rejects
   a non-child selection and makes no Drive mutation.

## Stop conditions

Stop on 401/403/404, an absent immediate visit, no immediate videos, a scope
error, or organization policy restriction. Do not choose another folder or
use a personal runtime deployment identity. Escalate the exact redacted error
and requested least-privilege access to the resource owner.

## How to update this later

Keep this runbook aligned with the credential factory and Cloud Run deployment
definition. Document only redacted, confirmed evidence; never state that a
live test occurred unless an approved operations record independently proves it.
