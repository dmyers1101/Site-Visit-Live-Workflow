# Test-Folder End-to-End Trial Scorecard

**Run ID:** `<run-id>`  
**Date:** `<UTC date>`  
**Reviewer:** `<name>`  
**Overall result:** `PASS | PARTIAL | BLOCKED | FAIL`

## Scoring

Score every item as `2 = complete`, `1 = partial`, or `0 = absent/failed`.
An automatic fail on a hard safety rule makes the overall result `FAIL`,
regardless of score.

| Category | Check | Score | Evidence link / reviewer note |
| --- | --- | ---: | --- |
| Scope | The approved test-folder boundary was documented; every supported video in that boundary was processed or has a recorded stop reason. | /2 | |
| Identity | The deployed runtime was directly attached to `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`. | /2 | |
| Identity | No personal Drive runtime, service-account key, ADC Drive scope, or impersonation was used. | /2 | |
| Drive | Immediate folder/file discovery was recorded with IDs and immutable original names. | /2 | |
| Manifest | Manifest existed before staging/processing and includes every in-scope source with required metadata. | /2 | |
| Media | Probe record and mono 16 kHz WAV extraction are documented and retained. | /2 | |
| Transcription | Every source has a one-file Chirp request/result, status, timestamps, GCS URIs, and errors recorded. | /2 | |
| Empty text | Empty transcript policy was applied: one retry, then `NEEDS_REVIEW`. | /2 | |
| L1 | Every eligible transcript has versioned L1 prompt, exact schema, raw response, and validation evidence. | /2 | |
| L2 | Every L1-valid source has versioned L2 prompt, exact schema, raw response, and validation evidence. | /2 | |
| L3 | Every L2-valid source has versioned L3 prompt, exact schema, raw response, and validation evidence. | /2 | |
| Lineage | Every output preserves source asset ID and prompt/version traceability. | /2 | |
| Catalog | Google Sheets has one idempotent row per source, with Drive/transcript hyperlinks and per-row write evidence. | /2 | |
| Review | Drive rename remains blocked pending explicit human approval; proposal fields preserve original Drive name and ID. | /2 | |
| Documentation | Source map, artifact map, command ledger, GCP research, runbooks, ADR, and final handoff are complete. | /2 | |
| Reusability | A no-context future session can follow the exact next action and rollback instructions. | /2 | |

**Total:** `<0-32> / 32`

## Hard safety rules

Mark each as `PASS` or `FAIL`.

| Rule | Result | Evidence / note |
| --- | --- | --- |
| No source/local/GCS/output artifact was deleted. | | |
| No Drive source was automatically renamed, moved, or modified. | | |
| No Drive source was renamed, moved, or modified while creating the Sheets catalog. | | |
| No report, Asana task, schedule, or multi-folder automation was created. | | |
| No secret, OAuth token, or service-account key was committed. | | |
| `pilot/` and `_design/` were not modified. | | |
| External API/model/library assumptions were revalidated with current official sources. | | |
| Every failure stopped the workflow at that stage; no silent fallback occurred. | | |

## Required next-day decision

- [ ] **PASS (28–32, no safety failure):** retain artifacts; review outputs and
  approve a separate next goal for human-reviewed catalog publication or rename.
- [ ] **PARTIAL (16–27, no safety failure):** retain artifacts; address only
  documented blockers in a new narrowly scoped goal.
- [ ] **BLOCKED (0–15, no safety failure):** retain artifacts; resolve the
  first external prerequisite only. Do not rerun the entire workflow.
- [ ] **FAIL (any safety rule failed):** freeze changes, preserve evidence, and
  perform a human review before another execution.

## How to update this later

Version this template when scoring thresholds or required workflow gates change.
Do not rewrite a completed scorecard; create a new run-specific copy under
`docs/evidence/<run-id>/scorecard.md`.
