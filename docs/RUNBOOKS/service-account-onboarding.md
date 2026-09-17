# Runbook: Site Visit workflow service account

## Purpose

This runbook records the dedicated automation identity for the Site Visit workflow and the minimum access it needs. Use it instead of creating or sharing a second human Google account.

## Identity

| Item | Value |
| --- | --- |
| Service account | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` |
| Google Cloud project | `shir-sitevisit` |
| Created | 2026-09-16 |
| User-managed keys | None; do not create any |

The service account is an automation identity, not a person. It cannot sign in to Drive in a browser. It receives access when a Drive or Sheets owner shares the relevant resource with its email address.

## Cloud access already granted

The following project-level roles have been granted:

| Role | Why it is needed | What it does not grant |
| --- | --- | --- |
| `roles/speech.client` | Submit and read the approved Speech-to-Text workflow request. | Drive, Sheets, Cloud Storage, or permission to change source media. |
| `roles/aiplatform.user` | Invoke the approved Vertex AI extraction model after the required prompts are reviewed. | Drive, Sheets, Cloud Storage, or permission to change source media. |

Do not invoke either processing API until the four required versioned prompt files exist, one visit and one asset are explicitly selected, and the manifest is created.

## One-time Drive sharing: your click steps

Complete this only as a Drive owner or Shared Drive manager:

1. Open the approved Drive folder or Shared Drive.
2. Click **Share** or **Manage members**.
3. Add `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`.
4. Select the minimum role that allows the workflow to list contents and read an explicitly approved source file. Start with **Viewer**.
5. Turn off any setting that grants edit, move, organize, or delete rights.
6. Click **Send** or **Share**.
7. If Google says external members are not allowed, ask the Google Workspace or Shared Drive administrator to approve this service-account address or provide the organization-approved workload-identity alternative. Do not create a user-managed key as a workaround.

This share is read-only and does not modify any source media.

## One-time Sheets sharing: your click steps

Complete this only after the catalog sheet is approved:

1. Open the catalog Google Sheet.
2. Click **Share**.
3. Add `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`.
4. Select **Editor**, because the approved workflow creates or updates draft catalog rows.
5. Click **Send** or **Share**.

The workflow must write only idempotent draft rows and still requires human approval before publication.

## Storage access: do this only after creating the dedicated staging bucket

Do not grant a project-wide Storage role. After a dedicated staging bucket exists, replace `YOUR_STAGING_BUCKET` and run:

```powershell
$serviceAccount = 'serviceAccount:site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com'
gcloud storage buckets add-iam-policy-binding gs://YOUR_STAGING_BUCKET --member=$serviceAccount --role=roles/storage.objectCreator
gcloud storage buckets add-iam-policy-binding gs://YOUR_STAGING_BUCKET --member=$serviceAccount --role=roles/storage.objectViewer
```

These bucket-scoped roles allow the workflow to create uniquely named transient artifacts and read their status/output without granting delete permission. Configure lifecycle retention separately; do not delete artifacts automatically.

## Runtime use

Use the service account only as the direct identity attached to the Cloud Run
Job. Do not use service-account impersonation, personal Drive credentials, or
download a JSON key.

## Validation checklist

- Confirm the service account exists:

  ```powershell
  gcloud iam service-accounts describe site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com --project=shir-sitevisit
  ```

- Confirm its project roles:

  ```powershell
  gcloud projects get-iam-policy shir-sitevisit --flatten='bindings[].members' --filter='bindings.members:serviceAccount:site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com' --format='table(bindings.role,bindings.members)'
  ```

- After the Drive manager completes sharing, run only the metadata and immediate-child checks in [Drive HTTP 403 recovery](drive-access-recovery.md). Do not select or process media as part of access validation.

## How to update this later

Record every new role, shared resource, role rationale, grantor, and removal date in this runbook and an ADR. Prefer resource-level IAM to project-wide grants, and remove access when the workflow no longer needs it.
