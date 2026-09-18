# End-to-end run result — 20260918T100802Z

**Status: SUCCESS.** The complete workflow ran for the first time, in the Shared
Drive, as the service account, including the two gates never previously
attempted: **renaming the source videos** and **drafting a report in Google
Docs**.

## Headline

| | |
| --- | --- |
| Run ID | `20260918T100802Z` |
| Execution | `site-visit-workflow-2t5jq` |
| Image | `…/site-visit:e2e-20260918` (build `84179f6c-2191-412b-b6bd-c3c9853b202f`) |
| Identity | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` |
| Command | `process-folder --rename-approved --report` |
| Duration | 13m 2s for 16 videos |
| Assets | **14 CATALOGUED · 2 NEEDS_REVIEW · 0 FAILED** |
| Renames | **14 RENAMED · 2 skipped (not eligible)** |
| Report | **WRITTEN** |

## Artifacts the service account created in the Shared Drive

Both were created **by the service account**, inside
`1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF`, during the run. Neither existed beforehand.

| Artifact | ID |
| --- | --- |
| Catalog spreadsheet | `1GW3fg8IeobZn9uhs_4W5yOUUURISI0Ll0xRYhpOu22U` |
| Report document | `1l2htL4V3Lyy8nI1jiw00nr-pCM-qEWH6Eh9eN4W4ZTU` |

This is a behavioural change worth stating plainly: the catalog Sheet ID used to
be a **required input** (`CATALOG_SHEET_ID`). It is now an **output** of the
run. The run was deliberately launched with neither ID set, so the
resolve-or-create path was genuinely exercised rather than bypassed.

## Independent verification

The run's own summary was not trusted. A second job,
`site-visit-workflow-verify`, re-listed the folder from Drive as the service
account. Raw output is kept at `post-rename-drive-listing-raw.json`.

The folder now holds **21 immediate children**, decomposing exactly as expected:

```
16 videos + 3 HEIC images + 2 files created by the service account = 21
```

- **14 videos carry new descriptive names.**
- **2 videos are still `IMG_3653.MOV` / `IMG_3662.MOV`** — correctly skipped,
  because both were NEEDS_REVIEW. The eligibility gate held.
- **3 HEICs untouched**, still excluded with a recorded reason.

This settles the capability question that shaped the earlier plan: the service
account can create files in the Shared Drive and rename files in place. An
earlier preflight saw `drives.get` return 404 and I wrongly concluded the
account was not a Shared Drive member. It is. `drives.get` failing only proves
the account cannot enumerate the drive object, not that it cannot write to it —
and the contradicting evidence (`canAddChildren: true`) was in the same JSON.

## Renames applied

See `PRE-RENAME-STATE.md` for the before state. The Drive file ID never changes
and remains the catalogue row key, so renaming cannot break idempotency.

| Original | New |
| --- | --- |
| IMG_3650.MOV | `Alma_Apartments_Unclean_Grills_Dog_Feces_No_Bags_Dirty_Curbs.MOV` |
| IMG_3651.MOV | `1p-9pppEYKrgVPVIlG-dSp9Df7u4EstOw_multiple_hallway_issues.MOV` |
| IMG_3652.MOV | `Unit_1129_threshold_coming_off_safety_hazard.MOV` |
| IMG_3653.MOV | *(unchanged — NEEDS_REVIEW)* |
| IMG_3654.MOV | `Alma_Apartments_Floor2_Maintenance_Issues.MOV` |
| IMG_3655.MOV | `Alma_Apartments_Floor_2_Hallways_Issues.MOV` |
| IMG_3656.MOV | `Alma_Apartments_Floor3_AC_Leak_Violations.MOV` |
| IMG_3657.MOV | `Alma_Apartments_Floor3_Hallways_Utility_Closet_Issues_Trash_Unsecured_…MOV` |
| IMG_3658.MOV | `Stagnant_Water_Lower_Roof_Unit_1331.MOV` |
| IMG_3661.MOV | `Alma_Roof_Electrical_Room_Ponding_Issue.MOV` |
| IMG_3662.MOV | *(unchanged — NEEDS_REVIEW, empty transcript)* |
| IMG_3664.MOV | `Roof_Ponding_TPO_Degradation_Drainage_Issue.MOV` |
| IMG_3665.MOV | `Gym_Door_Locked_Out.MOV` |
| IMG_3666.MOV | `Hallway_One_Dirty_Not_Looking_Good.MOV` |
| IMG_3667.MOV | `Alma_Apartments_Laundry_Room_AC_Machines_Lint_Issues.MOV` |
| IMG_3668.MOV | `roof_bad_shape.MOV` |

## Known imperfections — deliberately not fixed

These are recorded rather than polished away. The run was to prove the workflow,
not to produce a finished product.

1. **One filename is poor.** `IMG_3651.MOV` became
   `1p-9pppEYKrgVPVIlG-dSp9Df7u4EstOw_multiple_hallway_issues.MOV` — L1 emitted
   a `suggested_filename` with the Drive ID baked into it. The sanitizer did its
   job faithfully; the fault is upstream. The L1 prompt does not forbid putting
   the asset ID in the filename, and Gate 6 trusts whatever string L1 produced.
   **Fix belongs in `prompts/l1-extraction.md`.**

2. **The report contains an arithmetic error.** It says "16 clips were
   reviewed. Of these, 15 clips produced specific findings, while 2 clips
   require further human review" — which sums to 17 — then closes by saying
   "One clip could not be assessed", contradicting its own earlier 2. The real
   figures are 14 catalogued and 2 needs-review.

   This is the predictable cost of a deliberate design choice: the report is the
   **only unvalidated model output in the system**. Every structured layer
   (L1/L2/L3) has a strict schema and rejects bad output; the narrative layer
   has none, because a weak sentence is tolerable where a wrong structured
   record is not. At 0.1.0 that trade is acceptable. It is the first thing the
   real report prompt must address — the counts should be computed in code and
   handed to the model, not left for it to total up.

3. **`roof_bad_shape.MOV`** is terse compared to its siblings. Naming
   consistency is not enforced anywhere.

4. **No sibling-collision check.** If two clips produced the same suggested
   filename, both would be renamed to it. Drive tolerates duplicate names, so
   this would not error — it would just be confusing.

5. **The Doc is append-only.** Running the report again adds a second report
   below the first rather than replacing it, because nothing in this system
   deletes. Intentional, but it means the Doc is a log, not current state.

## What this run proves

1. The service account can create Sheets and Docs in the Shared Drive.
2. It can rename source videos in place, with the Drive ID preserved as the row
   key so idempotency survives a rename.
3. The eligibility gate prevents renaming assets that failed or need review.
4. The Docs API leg works: prompt → Vertex → `batchUpdate`/`insertText`.
5. The resolve-or-create path for output files works when no ID is supplied.
6. The dual approval gate (`RENAME_APPROVED` env **and** `--rename-approved`
   flag) is wired and was exercised.

## How to update this later

Create a new dated evidence directory per run; never overwrite this one. Before
any future rename run, re-capture the pre-rename state from the newest manifest
so the before/after pair comes from one source of truth.
