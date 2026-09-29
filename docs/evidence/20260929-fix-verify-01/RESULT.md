# Fix verification run — 20260929-fix-verify-01

**Status: SUCCESS.** One-asset run verifying commit `1fdc04f` (fixes for the
defects recorded in `../20260918-e2e-full-run/RESULT.md`).

| | |
| --- | --- |
| Execution | `site-visit-workflow-7zlsx` (5m43s) |
| Image | `…/site-visit:fix-20260929` (build `96260d82-a3a3-4acf-a97b-cc9dc990731d`) |
| Identity | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` |
| Args (per-execution override) | `process-folder --asset-id 1p-9pppEYKrgVPVIlG-dSp9Df7u4EstOw --run-id 20260929-fix-verify-01 --report --catalog-sheet-id 1GW3fg8I… --report-doc-id 1l2htL4V…` |
| Rename | **Not approved for this run** (`--rename-approved` omitted) → `SKIPPED_NOT_APPROVED`. No source file changed. |

## Results

- Asset `CATALOGUED`; catalog row 2 `UPDATED` (idempotent key held).
- L1 prompt `1.3.0` loaded; `suggested_filename` = `unit_2107_siding_water_leak`
  — no Drive ID. (The Drive-ID strip in `rename.build_new_name` is covered by
  unit tests; it was not exercised live because no rename was approved.)
- Report prompt `0.2.0` loaded; the Doc's new entry opens with the code-written line
  `Clips reviewed: 1. Catalogued with findings: 1. Needs human review: 0. Failed: 0.`
  and the narrative states no counts.

## Observations

1. **The new report was inserted ABOVE the 09-18 report**, not below it. The Doc
   is newest-first, not an append-at-end log as `report-synthesis.md` describes.
2. **L1 now picks a different single issue for this clip** (09-18:
   "multiple_hallway_issues"; now "unit_2107_siding_water_leak"). The clip
   narrates several issues; L1 summarises one. Model variance, not a regression.
3. **Job defaults are risky:** the job's standing args include
   `--rename-approved` and env has `RENAME_APPROVED=true` and
   `RUN_ID=20260918T100802Z`. A bare `gcloud run jobs execute` would rename
   source videos and write into the 09-18 evidence prefix. Always override
   `--args` and `RUN_ID` per execution.
4. The Sheet and Doc now sit in the source folder and are listed as excluded
   items (5 excluded, not 3). Harmless; they are also in Gate 6's collision set.
