# Change log — overnight orchestrated run

**Run ID:** `20260917T055321Z-phase2-auth-preflight` (continued as the overnight build)
**Operator authorization:** create the Google Sheet; edits permitted; **no deletions**; no further permission prompts.
**Orchestrator:** Claude (this session). Subagents used for prompt authoring and pipeline code.

Every change below is additive or an in-place edit. Nothing was deleted.

## External / cloud changes

| UTC | Change | Identity | Detail |
| --- | --- | --- | --- |
| 06:20 | Created GCS bucket `gs://shir-sitevisit-staging` | deployer | US multi-region, uniform bucket-level access |
| 06:20 | Enabled `sheets.googleapis.com` | deployer | Was disabled |
| 06:21 | Granted SA `roles/storage.objectCreator` + `roles/storage.objectViewer` on the bucket | deployer | Create + read |
| 06:21 | Removed SA `roles/storage.objectUser` from the bucket | deployer | That role carries `storage.objects.delete`; removed so the SA cannot delete. **No data was deleted — this removed a permission, not content.** |
| 06:28 | Granted SA `roles/storage.legacyBucketReader` | deployer | Fixes `storage.buckets.get` 403 |
| 06:42 | **Created Google Sheet** "Site Visit Catalog — Live Workflow" | dmyers@shircapital.com | ID `158eA2K5FgGc4dQ43xHxdTuri-KOwPSuNn8qQqsasBy0`, in the operator's Drive so it is visible to them |
| 06:42 | Shared that Sheet with the service account as **writer** | dmyers@shircapital.com | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` |

Note on the Sheet: the preflight could not create it as the service account,
because the SA is shared on the source folder only and is not a member of the
Shared Drive (`drives.get` → 404). Creating it in the operator's own Drive and
sharing it to the SA is the least-privilege resolution and keeps it visible to
the operator.

## Repository changes

| File | Type | Description |
| --- | --- | --- |
| `src/site_visit_workflow/preflight.py` | new | Read-only authorization preflight checks |
| `src/site_visit_workflow/cli.py` | edit | Added `auth-preflight` and `list-folder-children` commands |
| `src/site_visit_workflow/google.py` | edit | Added `list_immediate_children()` |
| `pyproject.toml` | edit | Added `google-genai` dependency |
| `docs/evidence/20260917T055321Z-phase2-auth-preflight/` | new | Preflight evidence: matrix, command ledger, go/no-go, source map, raw outputs |
| `docs/research/gcp/drive-api-v3.md` | new | Drive API v3 research record |
| `docs/evidence/direct-service-account-drive-read-2026-09-16.md` | edit | Updated with the successful direct-SA read |

Subagent-authored changes are appended below as they land.

## How to update this later

Append a row per change. Never rewrite history in this file; add corrections as
new dated rows.
