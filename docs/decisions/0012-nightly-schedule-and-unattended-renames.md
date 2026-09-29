# ADR 0012 — Nightly schedule; unattended renames of CATALOGUED clips

## Status
Accepted (2026-09-29). Amends HANDOFF safety rule 2 ("a rename requires an
explicit human approval record"): the standing approval is now the nightly
job's configuration, approved by the operator on 2026-09-29.

## Context
Walks are uploaded over days; the operator wants new clips processed nightly
without a person present, and CATALOGUED clips renamed automatically.
Org rule: recurring work runs in the cloud, never on a workstation.

## Decision
- **Two Cloud Run jobs, one image:**
  - `site-visit-nightly` — standing args
    `process-portfolio --root <master> --catalog-sheet-id <master sheet> --max-clips 60 --rename-approved --report`,
    env `RENAME_APPROVED=true`. Only the scheduler runs it.
  - `site-visit-workflow` — manual/ops job. Standing args are the read-only
    `list-portfolio`; `RENAME_APPROVED` and the pinned `RUN_ID` removed, so a bare
    `execute` can never rename or overwrite evidence.
- **Cloud Scheduler** `site-visit-nightly-trigger` (`us-central1`, `0 2 * * *`
  America/New_York) → `POST …/jobs/site-visit-nightly:run`, OAuth as
  `site-visit-scheduler@shir-sitevisit.iam.gserviceaccount.com`, which holds
  `roles/run.invoker` on `site-visit-nightly` only.
- The rename gate still requires: both approvals, CATALOGUED, validated L1, and
  (new) an L1 location or issue (`rename.l1_has_finding`); plus Drive-ID
  stripping and sibling-collision suffixing.

## Consequences
- Renames happen with no human in the loop. Undo = rename back to
  `original_drive_name` (kept in the Sheet and in each `drive-rename.json`).
- Pause: `gcloud scheduler jobs pause site-visit-nightly-trigger`; stop renames only:
  set `RENAME_APPROVED=false` on `site-visit-nightly` (see `RUNBOOKS/change-guide.md`).
