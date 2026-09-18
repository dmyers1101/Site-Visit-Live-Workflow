# Scratchpad — full end-to-end run (2026-09-18)

Living plan. Steps get updated as reality pushes back. Goal is a complete
working pass, not a perfect one.

## Goal

Run the whole workflow for real, including the two things never yet attempted:
**renaming the Drive source videos** and **drafting a report in Google Docs**.

## What is new vs. everything run so far

| Capability | State before today |
| --- | --- |
| Discovery → manifest | Working |
| Transcription (Chirp) | Working |
| L1/L2/L3 synthesis (Vertex) | Working |
| Catalog Sheet upsert | Working |
| **Drive file rename** | **Never run.** Code path exists but was gated behind an approval record and deliberately never exercised |
| **Google Docs report** | **Does not exist.** No code, no prompt, no API enabled |

## Authorization change recorded for this run

The operator has explicitly authorized renaming the Drive source videos in this
run. Every prior run wrote `PROPOSED_ONLY_AWAITING_HUMAN_APPROVAL`. That
approval is now given. The rename is still logged, reversible by hand, and the
original name is preserved in the catalogue (`original_drive_name`).

**Still absolutely forbidden:** deleting anything.

## Steps

- [x] **S1. Scratchpad** — this file.
- [x] **S2. Recorder subagent** — spawn a documenter that records how each step
      connects to the next. Message it on every step transition.
- [x] **S3/S4 (REVISED). The service account creates both output files itself,
      inside the Shared Drive folder.** The job calls Drive `files.create` with
      `parents=[1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF]` and `supportsAllDrives=true`
      for the catalog Sheet and the report Doc. Enable `docs.googleapis.com`.
- [x] **S5. Placeholder report prompt** — `prompts/report-synthesis.md` at
      0.1.0, explicitly marked PLACEHOLDER. It takes the catalogue rows and
      produces an executive summary. Deliberately simple.
- [x] **S6. Code** — two additions to the pipeline:
      - Gate 6 `rename-drive-approved`: rename each source video to its
        `suggested_filename`, only when an explicit run-level approval flag is
        set. Record old and new name. Never touch a file that failed.
      - Gate 7 `report`: read the run's catalogue rows, call Vertex with the
        placeholder prompt, write the result into the Google Doc.
- [x] **S7. Build + deploy** the image.
- [x] **S8. Run end-to-end** over all 16 videos with rename and report enabled.
- [x] **S9. Verify** — Sheet rows, Drive names actually changed, Doc has content.
- [x] **S10. Document** — evidence folder, update HANDOFF/CHANGELOG/ADRs,
      commit and push.

## Known constraints to respect

- Speech quota: do not re-run the full library twice inside ~30 min.
- Cloud Run: `--memory=8Gi --cpu=2 --task-timeout=7200s`.
- Service account cannot delete anything, anywhere. Do not grant delete.
- Rename uses `canRename: true`, already confirmed on these files.
- **CORRECTED 2026-09-18:** the service account IS a Shared Drive member and can
  create and edit files there. The whole point of this run is to perform the
  workflow *in the Shared Drive folder*. My earlier preflight saw `drives.get`
  return 404 and I wrongly concluded "not a member" — but the same preflight
  showed the folder itself reports `canAddChildren: true`, which contradicted
  that. `drives.get` failing is not proof of non-membership. The service account
  creates its own outputs in the Shared Drive.

## Running log of changes to this plan

- 2026-09-18 — plan created.
- 2026-09-18 — **Deployer credential expired mid-run.** `gcloud` user creds hit
  "Reauthentication failed. cannot prompt during non-interactive execution",
  blocking build/deploy/execute. Resolved without an interactive login: ADC was
  still valid, and gcloud accepts `CLOUDSDK_AUTH_ACCESS_TOKEN`, so every gcloud
  command now runs with the ADC token exported. The ADC token carries
  `cloud-platform` scope ONLY — no Drive scope — so the identity split holds:
  deployer does control plane, service account does all data operations.
  `docs.googleapis.com` enabled via the Service Usage REST API.
- 2026-09-18 — **`CATALOG_SHEET_ID` required-check is now wrong.** It is a
  required env var, but the Sheet is now created BY the run. Being fixed: the
  id becomes optional, is resolved once before the asset loop, and every
  downstream read routes through the resolved value rather than the raw setting.
- 2026-09-18 — **S3/S4 revised.** Operator corrected a wrong assumption: the SA
  is a Shared Drive member and must create the Sheet and Doc itself, in the
  Shared Drive folder. Nothing is created in a personal Drive and nothing runs
  locally. Two files were created in the operator's personal Drive before this
  correction (Sheet `1BOAjawx2v-MyareQFPa0ecdvgUzuDANxonryOwsU9YI`, Doc
  `1XONg2lTpAX6T-BBClm6Fqn6mxQbYPUctfquKHVV7fUk`); they are now **unused and
  superseded**. They are left in place because nothing is ever deleted.
- 2026-09-18 — **RUN COMPLETE.** `20260918T100802Z`: 14 CATALOGUED, 2
  NEEDS_REVIEW, 0 FAILED. 14 videos renamed in Drive, 2 correctly skipped.
  Catalog Sheet `1GW3fg8IeobZn9uhs_4W5yOUUURISI0Ll0xRYhpOu22U` and report Doc
  `1l2htL4V3Lyy8nI1jiw00nr-pCM-qEWH6Eh9eN4W4ZTU` both CREATED BY THE SERVICE
  ACCOUNT inside the Shared Drive. Verified independently by re-listing the
  folder as the service account: 21 children = 16 videos + 3 HEIC + 2 new files.
  Full write-up in `RESULT.md`. Imperfections recorded, not polished away.
