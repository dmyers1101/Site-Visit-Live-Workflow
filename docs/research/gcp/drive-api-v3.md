# Google Drive API v3 — confirmed research record

**Date pulled:** 2026-09-16
**Pulled for:** direct service-account read of immediate folder children from a
deployed Cloud Run Job.

## Sources

- https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list
- https://pypi.org/project/google-api-python-client/

## Confirmed client library

| Library | Pinned in `pyproject.toml` | Notes |
| --- | --- | --- |
| `google-api-python-client` | `>=2.169.0` | Discovery documents are cached in the library since 2.0; `cache_discovery=False` is used to avoid the file-cache warning. |
| `google-auth` | `>=2.40.0` | Supplies ambient ADC from the Cloud Run metadata server. |

## Confirmed `files.list` shape for shared-drive children

Verified against the live API on 2026-09-16 (execution `site-visit-workflow-vrrr2`):

- `q`: `'<folderId>' in parents and trashed = false` — returns **immediate**
  children only; Drive parentage is not recursive here.
- `supportsAllDrives=true` **and** `includeItemsFromAllDrives=true` are both
  required for shared-drive items. Omitting either silently returns fewer items.
- `fields`: must be requested explicitly. `webViewLink` is **not** returned by
  default — it must be named in `fields` or the Drive link comes back `None`.
- `pageSize`: default 100 for shared drives, max 1000. The gateway refuses to
  proceed when `nextPageToken` is present rather than silently truncating.
- `corpora` / `driveId` are not needed when querying a specific folder by ID.

## Scopes

`files.list` accepts `drive`, `drive.readonly`, `drive.metadata.readonly`,
`drive.file`, `drive.metadata`, `drive.appdata`, and the two `*.readonly` media
scopes.

**Gotcha worth knowing:** a Cloud Run service account obtains its token from the
metadata server, which issues `cloud-platform`. The `scopes=` argument passed to
`google.auth.default()` does not re-scope that token. The Drive call
nevertheless succeeded from the deployed job, so `cloud-platform` is accepted
here. If a future Drive call returns `insufficient scopes`, that is the cause —
not a missing IAM role.

## Project prerequisite

`drive.googleapis.com` must be enabled on the project. When it is not, the API
returns HTTP 403 `reason: accessNotConfigured` / `domain: usageLimits` — this
reads like a permission error but is an API-enablement error. Enabled on
`shir-sitevisit` on 2026-09-16.

## How to update this later

Re-pull before the next Drive change, and record the tested request shape and
the library version actually installed in the image.
