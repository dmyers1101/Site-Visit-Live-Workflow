# Authentication and authorization

## Authorization model

The deployed live model uses the existing dedicated service account
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` directly,
attached to the workload (Cloud Run Job). It uses no key file, and the
application uses only ambient credentials from that direct attachment. A
personal Drive identity must never be the deployed runtime identity. See
[Site Visit workflow service account](RUNBOOKS/service-account-onboarding.md).

## Minimum permissions

| Service | Minimum capability |
| --- | --- |
| Google Drive | List immediate folder contents and read/download approved source media; no rename or delete permission for the first pass |
| Cloud Storage | Create/read objects in the dedicated staging prefix; retain artifacts |
| Speech-to-Text v2 | Submit and read BatchRecognize operations and access the configured recognizer/model |
| Vertex AI | Invoke the approved extraction model only after the prompt workflow is approved |
| Google Sheets | Read the target schema and create/update draft rows by idempotent key |

## Security rules

- Never commit service-account keys, OAuth refresh/access tokens, API keys, or Drive file content.
- Prefer Application Default Credentials or workload identity over key files.
- Keep local credential paths and `.env` files outside Git tracking.
- Record permission changes and their rationale in an ADR.
- Preserve Drive source media, original name, and Drive ID as immutable evidence.

## Drive access recovery

No live cloud or Drive test is claimed by this repository. Before any explicit
intake command, confirm that the configured service account has been shared on
the single approved Shared Folder and follow
[Drive HTTP 403 recovery](RUNBOOKS/drive-access-recovery.md) if access fails.

Follow [Drive HTTP 403 recovery](RUNBOOKS/drive-access-recovery.md) before changing permissions. It separates browser-access, metadata-only OAuth, and Shared Drive checks and records the exact non-secret evidence needed to resolve the failure. Do not substitute a different folder or bypass the approval boundary.

## How to update this later

Revise this document with validated role names and scope choices. Re-review
least privilege whenever another API or output destination is introduced.
