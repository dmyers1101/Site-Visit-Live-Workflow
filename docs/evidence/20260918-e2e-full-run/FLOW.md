# End-to-end run flow — 2026-09-18

This is the narrative of one live end-to-end run of the Site Visit workflow, written for the
engineer who later has to change it. It is deliberately **not** a status log and **not** a list of
commands. It describes **the seams**: what each step produced, exactly where that artifact lives,
what the next step needed from it, and where the handoff was fragile or broke.

## What is being attempted, and why this run is different

Every prior run stopped short of touching the customer's own data. Discovery, transcription
(Chirp), the L1/L2/L3 synthesis (Vertex), and the catalogue Sheet upsert have all run before
(see the sibling evidence folders `20260917T055321Z-phase2-auth-preflight`,
`20260917T070454Z-one-asset-trial`, `20260917T071718Z-one-asset-trial-pass`,
`20260917T075400Z-full-library-run`). Two things have never run:

1. **Renaming the Drive source videos.** The code path exists (`cmd_rename_drive` in
   `cli.py`, `DriveGateway.rename`) but the end-to-end `process-folder` command has always
   written the literal string
   `"NOT_ATTEMPTED; suggested names are proposals only."` into each asset summary, and prior
   evidence recorded `PROPOSED_ONLY_AWAITING_HUMAN_APPROVAL`. The operator has explicitly
   authorized the rename for this run. Deleting anything remains forbidden.
2. **Drafting the executive report into a Google Doc.** As of the start of this run there is no
   code, no prompt, and `docs.googleapis.com` is not enabled.

So this run adds two new gates on the end of an already-working chain — which means two new seams,
both untested, both attached to the part of the system that writes to things a human will see.

## Step map

The table below is the *planned* wiring (S1–S10 per the scratchpad). Each row is filled in and
corrected in its own section below as the step actually runs.

| Step | Produces | Consumed by | Contract between them |
| --- | --- | --- | --- |
| S1 Scratchpad | `SCRATCHPAD.md` — the plan, the authorization record, the constraints | Humans; this recorder | Plain prose. The authorization sentence in it is the only record that the rename was approved — no machine reads it |
| S2 Recorder subagent | This `FLOW.md` | Future engineers | Orchestrator messages at each transition; recorder appends. No automated feed |
| S3 Fresh Google Sheet **(revised)** | A catalog Sheet created **by the job, as the service account**, inside the Shared Drive folder `1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF` | S8 (the run itself) | **Inverted from the original plan.** The Sheet ID is no longer a pre-known env var; it is *produced by* the run. Downstream steps must read it out of the run's own output |
| S4 Google Doc **(revised)** | A report Doc created the same way, same parent folder; `docs.googleapis.com` enabled | S6 (Gate 7 code), S8 (the run) | Same inversion: the Doc ID is an output of the run, not an input. Docs API enablement is the one precondition that remains external |
| S5 Report prompt | `prompts/report-synthesis.md` at 0.1.0, marked PLACEHOLDER, no lineage | S8 — read from `--prompts-dir` at runtime by Gate 7 | **The historical failure seam.** The prompt must be present *inside the built image* (`COPY prompts ./prompts`), not merely in the repo. Output is plain text with no `response_schema` — the only unvalidated model output in the system |
| S6 Code | `rename.py` (Gate 6) and `report.py` (Gate 7); 178 tests passing (128 existing + 50 new) | S7 (build) | Gate 6 consumes L1 `suggested_filename` + `original_drive_name`, requires **both** `RENAME_APPROVED` env and `--rename-approved` flag. Gate 7 consumes the run's **in-memory** catalogue records, not a Sheet re-read. Gate 7 runs after Gate 6 by call order only |
| S7 Build + deploy | Image `…/site-visit:e2e-20260918`, Cloud Build `84179f6c-2191-412b-b6bd-c3c9853b202f` | S8 | Build context `apps/live-workflow` included `prompts/`, so `report-synthesis.md` shipped in the image and Gate 7 found it at runtime. **Seam risk 1 handled correctly this time** |
| S8 Run end-to-end | Execution `site-visit-workflow-2t5jq`, run id `20260918T100802Z`; Sheet `1GW3fg8IeobZn9uhs_4W5yOUUURISI0Ll0xRYhpOu22U` (created), Doc `1l2htL4V3Lyy8nI1jiw00nr-pCM-qEWH6Eh9eN4W4ZTU` (created), 14 renamed files | S9 | Deployed **without** `CATALOG_SHEET_ID` / `REPORT_DOC_ID` so the resolve-or-create path was exercised, not bypassed. Everything keys off `run_id` and `row_key = asset.drive_id` |
| S9 Verify | An independent re-list of the Shared Drive folder by a second job, `site-visit-workflow-verify` | S10 | Verification read Drive itself as the service account, **not** the job's own log. **Seam risk 8 actually satisfied for the first time** |
| S10 Document | Evidence folder, HANDOFF/CHANGELOG/ADR updates | Future work | Prose only |

### The identifiers everything hangs on

Three keys tie the whole chain together, and all three are conventions rather than enforced
contracts:

- **`run_id`** — from `RUN_ID` or `default_run_id()` in `config.py`. It becomes the GCS prefix
  (`run_prefix(settings)`) and is written into every catalogue row. If two runs share a `run_id`
  they will overwrite each other's evidence silently.
- **`row_key` = `asset.drive_id`** — set in `catalog.py` (`"row_key": asset.drive_id`). This is the
  idempotency key for the Sheet upsert. It is the Drive **file ID**, not the filename, which is the
  reason a rename is safe here where the laptop prototype's rename broke its own resume key and
  produced the 201-row blow-up recorded in `docs/HANDOFF.md` §5.
- **`suggested_filename`** — produced by L1 extraction, stored in the catalogue row, and consumed
  by Gate 6 as the new Drive name. Nothing validates that it is a legal or unique filename.

---

## S1 — Scratchpad

Created `apps/live-workflow/docs/evidence/20260918-e2e-full-run/SCRATCHPAD.md` as the living plan
for the run: the goal, a table of what is new versus what already works, the authorization change,
the ten steps, and the constraints to respect (Speech quota, Cloud Run sizing
`--memory=8Gi --cpu=2 --task-timeout=7200s`, no delete permission anywhere, `canRename: true`
already confirmed on the source files, and the fact that the service account is not a Shared Drive
member and therefore cannot create the Sheet or the Doc itself).

**Artifact:** `C:\Users\SHIRA\My Drive\Site Visit App\apps\live-workflow\docs\evidence\20260918-e2e-full-run\SCRATCHPAD.md`

**What the next step needs from it:** nothing mechanical. S1's only outputs that matter downstream
are (a) the human authorization for the rename and (b) the constraint that the Sheet and Doc must
be created by the operator account and *shared to* the service account rather than created by it.

**Seam note:** the rename authorization is prose in a Markdown file. The code will read an
environment flag. Nothing connects the two — if the flag is set on a future run, no approval record
is consulted. That is a convention, not a check.

## S2 — Recorder subagent

A documentation-only subagent was spawned with write access limited to this evidence folder. It
maintains this file. It receives no telemetry; it is fed by explicit messages from the orchestrator
at each step transition.

**Artifact:** this file —
`C:\Users\SHIRA\My Drive\Site Visit App\apps\live-workflow\docs\evidence\20260918-e2e-full-run\FLOW.md`

**What the next step needs from it:** nothing. It is a sink.

**Seam note:** this record is only as complete as the messages sent to it. A step that runs without
a transition message leaves a hole here, and the hole will not be visible.

## S3 / S4 — Catalog Sheet and report Doc (REVISED after an operator correction)

### What was originally planned, and why it was wrong

The plan recorded in `SCRATCHPAD.md` had the operator's personal account create both the catalog
Sheet and the report Doc and then share each to the runtime service account as writer. The stated
reason was that "the service account is NOT a Shared Drive member, so it cannot create files in the
Shared Drive root."

**That inference was wrong, and the operator corrected it.** The service account *is* a Shared Drive
member and can create and edit files there. The belief came from a preflight in which Drive's
`drives.get` returned `404 Shared drive not found`, which was read as proof of non-membership. It is
not. A failing `drives.get` proves only that the service account cannot enumerate the *drive object*
itself; it says nothing about whether it can write into a folder on that drive.

The evidence that would have caught this was in the same preflight output: the target folder came
back with **`canAddChildren: true`**, which directly contradicts "cannot create files here." Two
fields in one JSON document disagreed, and the run proceeded on the pessimistic one without anyone
reconciling them.

This matters beyond the fact of the correction, because creating the artifacts inside the Shared
Drive folder is the entire point of the run. Had the wrong inference stood, the run would have
"succeeded" while writing its outputs to the wrong place.

### The revised contract

The deployed job, running as `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`, calls
Drive `files.create` with `parents=[1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF]` and
`supportsAllDrives=true` to create **both** the catalog Sheet and the report Doc inside the Shared
Drive folder. Nothing is created in a personal Drive.

**The ordering dependency this introduces is real and is new.** In every prior run,
`CATALOG_SHEET_ID` was a static, pre-known environment variable — the target existed before the job
started, and `Settings.from_environment` treated it as required for a non-dry run. Now the Sheet ID
and the Doc ID **do not exist until the job runs**. They are outputs, not inputs. Any step, script,
or human that wants to look at the catalogue for this run has to obtain the ID from the run's own
output rather than from configuration. Anything that still reads `CATALOG_SHEET_ID` from the
environment is, for this run, reading a stale or empty value.

### Superseded artifacts (left in place — nothing is ever deleted)

- Sheet `1BOAjawx2v-MyareQFPa0ecdvgUzuDANxonryOwsU9YI` — operator's personal Drive, now unused.
- Doc `1XONg2lTpAX6T-BBClm6Fqn6mxQbYPUctfquKHVV7fUk` — operator's personal Drive, now unused.

Both were created under the original (incorrect) plan. They are retained deliberately.

### API enablement

`docs.googleapis.com` is now **enabled**. Confirmed enabled on the project: `docs`, `sheets`,
`drive`, `speech`, `aiplatform`.

### What broke at this seam, and how it was resolved

Nothing broke at runtime — the error was caught by the operator before the job ran. The failure was
one of inference: a capability boundary was assumed from an adjacent API call's failure rather than
tested at the point of use. Resolved by inverting the design so the job creates its own artifacts.

## Interlude — the deployer credential expired mid-run

Partway through, `gcloud` user credentials failed with
`Reauthentication failed. cannot prompt during non-interactive execution.` That blocked every
control-plane action at once: build, deploy, and execute.

It was resolved **without an interactive login**. The Application Default Credentials were still
valid, so the Cloud Run, Cloud Build, and Service Usage REST APIs are now being driven directly with
the ADC token.

The detail that matters for the wiring: **the ADC token carries the `cloud-platform` scope only — no
Drive scope.** So the identity split in this system is not just intended, it is provable:

- **Control plane** — `dmyers@shircapital.com`, via ADC. Enables APIs, builds images, updates and
  starts the Cloud Run Job. Cannot touch Drive at all.
- **Data plane** — `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`, from inside the
  container. Every Drive, Sheets, Docs, Speech, and Vertex operation happens here.

The uncomfortable consequence is that the control plane depends on a *human* credential that expires
silently, while the data plane uses a service account that does not. A run can therefore die between
steps for reasons that have nothing to do with the workflow.

---

## S5 — Placeholder report prompt

Wrote `prompts/report-synthesis.md` at version 0.1.0, explicitly marked **PLACEHOLDER**. It takes
the catalogue rows and produces an executive summary, and it is deliberately simple.

**It has no lineage, and that distinguishes it from every other prompt in the system.** The L1, L2,
and L3 prompts were derived from three logged pilot runs; this one was written from scratch to make
the plumbing exist. Anyone reading a report produced by this run should treat the *wiring* as the
deliverable and the *prose* as provisional.

**Artifact:** `apps/live-workflow/prompts/report-synthesis.md`

**What the next step needs from it:** the prompt is read **from disk at runtime**, from
`--prompts-dir`, exactly like the L1/L2/L3 files. That means it must ship inside the image via
`COPY prompts ./prompts`. **This is the same seam that silently broke Gate 4 before** — a green
build with a prompt the container cannot find. Seam risk 1 is therefore not historical trivia on
this run; it is the specific thing S7 has to get right.

**Output contract:** plain text, with **no `response_schema`**. This is the only unvalidated model
output in the system, and that is a deliberate call: a weak narrative is acceptable where a wrong
structured record is not. Everything that feeds the catalogue stays schema-validated; only the
human-readable summary is free-form.

**A property that falls out of the never-delete rule.** The Doc is written with `insertText` only,
never `deleteContentRange`. Running the report a second time therefore **appends a second report
rather than replacing the first**. The report Doc is an append-only log of report runs, not a
current-state document. That is a consequence of the safety rule rather than a design goal, and a
reader opening the Doc later needs to know that the newest report is at the bottom and that earlier
sections may describe a superseded state of the world.

## S6 — Gate 6 (rename) and Gate 7 (report)

Two new modules: `src/site_visit_workflow/rename.py` and `src/site_visit_workflow/report.py`.
178 tests passing — 128 existing, 50 new.

### Gate 6 — rename

**Consumes:** L1's `suggested_filename` plus the asset's `original_drive_name`.
**Produces:** `<asset>/drive-rename.json` in the run's GCS evidence prefix, and a per-asset
`RenameOutcome` carried into the run summary.

`build_new_name` preserves the **original extension** and sanitizes the stem, and returns `None` to
mean "skip." That directly answers seam risk 6 — `suggested_filename` is no longer passed raw to
Drive.

**Approval is belt and braces:** the rename requires **both** the `RENAME_APPROVED` environment
variable **and** the `--rename-approved` CLI flag. Either one alone is not enough. This is the right
shape for an operation that mutates the operator's own source library, and it partly answers seam
risk 4 — an env var inherited in a Job config can no longer trigger a rename on its own, because the
flag must also be passed per invocation.

**Eligibility is narrow:** only `CATALOGUED` assets with a validated L1 are eligible.
`NEEDS_REVIEW` and `FAILED` assets are never renamed. This is what seam risk 7 asked for — a file
whose processing went wrong keeps the name its operator gave it.

### Gate 7 — report

**Consumes:** the run's **in-memory** catalogue records. This is an explicit decoupling: Gate 7 does
**not** re-read the Sheet. The advantage is that the report cannot be corrupted by concurrent edits
to the Sheet and does not depend on the Sheet write having succeeded. The cost is that the report
describes what the run *believes* it wrote, not what is actually in the Sheet — so the report is not
independent verification of the catalogue, and must not be read as such.

**Produces:** text appended into the report Doc via Docs API `batchUpdate` / `insertText`.

### Ordering

Gates 1–5, then 6, then 7. The report runs **after** the rename so that it can reflect the new
filenames. **Nothing enforces this beyond the order of the calls in `cmd_process_folder`.** There is
no assertion that renames are complete before the report is built; reordering the two call sites
would silently produce a report describing pre-rename names, and no test or runtime check would
object.

### The ordering inversion from S3/S4 is resolved

The problem recorded in S3/S4 — that the Sheet and Doc IDs became outputs of the run rather than
inputs — has been handled properly rather than worked around. Output IDs are resolved **once, before
the asset loop**, and emitted as a dedicated `"gate": "outputs"` log line, so the IDs appear in the
evidence before any media is touched.

Critically, **the validation was replaced rather than dropped.** `CATALOG_SHEET_ID` became optional,
but `assert_output_targets_resolvable` now fails *before any asset is processed* unless either an
explicit ID or a creatable parent exists. That preserves the fail-fast property the required-env
check used to provide. Every downstream read routes through the resolved local value; the only
remaining reads of `settings.catalog_sheet_id` are in `cmd_publish_catalog`, which legitimately
operates on a pre-existing sheet.

### Seam risk 11 is closed

The hardcoded `"NOT_ATTEMPTED; suggested names are proposals only."` string no longer reaches the
evidence record. The per-asset record now carries the real outcome, and a `drive_rename_decision`
field carries either `RENAMED_TO:<name>` or the actual skip reason. The docstring clause "deletes
nothing, anywhere" has been separated out to stand alone, away from the two clauses that went false
this run.

---

## S7 — Build and deploy

**Image:** `us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:e2e-20260918`
**Cloud Build:** `84179f6c-2191-412b-b6bd-c3c9853b202f`

The build context was `apps/live-workflow` and **included `prompts/`**. This is the seam that
silently broke Gate 4 once before — code reading a prompt file at runtime that the image never
shipped — and this time it was handled correctly: `report-synthesis.md` was in the image and Gate 7
found it at runtime. Worth being precise about what that means, though: it was handled by the build
context happening to be right, not by any check that would have caught it being wrong. Seam risk 1
was avoided on this run; it is not closed.

## S8 — The live end-to-end run

**Execution:** `site-visit-workflow-2t5jq` · **run id:** `20260918T100802Z` · completed
successfully in **13m2s**.

Deployed with `--args=process-folder,--rename-approved,--report` and `RENAME_APPROVED=true` — both
halves of the belt-and-braces approval present, as Gate 6 requires.

**Deliberately deployed *without* `CATALOG_SHEET_ID` and `REPORT_DOC_ID`.** This matters: it means
the resolve-or-create path was genuinely exercised rather than bypassed by handing the job
pre-existing IDs. The ordering inversion first recorded in S3/S4 — that the output IDs became
products of the run instead of inputs to it — worked end to end. Neither ID existed before the run.

### Results

| Field | Value |
| --- | --- |
| `status_counts` | 14 `CATALOGUED`, 2 `NEEDS_REVIEW`, 0 `FAILED` |
| `catalog_sheet_id` | `1GW3fg8IeobZn9uhs_4W5yOUUURISI0Ll0xRYhpOu22U` — **created: true** |
| `report_doc_id` | `1l2htL4V3Lyy8nI1jiw00nr-pCM-qEWH6Eh9eN4W4ZTU` — **created: true** |
| `report_status` | `WRITTEN` |
| `rename_summary` | `RENAMED` 14, `SKIPPED_ASSET_NOT_ELIGIBLE` 2 |

The two skipped assets are the two `NEEDS_REVIEW` assets. The eligibility rule and the status counts
agree, which is the first sign the rename gate did what it claimed.

## S9 — Independent verification

**This is the read-back that seam risk 8 said the system did not have.** The run's own summary was
not trusted. A second Cloud Run job, `site-visit-workflow-verify`, ran `list-folder-children` as the
service account and re-listed the Shared Drive folder from Drive itself.

The folder now holds **21 immediate children**, decomposing exactly as predicted:
**16 videos + 3 HEIC images + 2 files created by the service account.**

- **14 videos carry their new descriptive names**, for example
  `Unit_1129_threshold_coming_off_safety_hazard.MOV`,
  `Alma_Apartments_Laundry_Room_AC_Machines_Lint_Issues.MOV`,
  `Roof_Ponding_TPO_Degradation_Drainage_Issue.MOV`.
- **`IMG_3653.MOV` and `IMG_3662.MOV` still carry their original names** — correctly skipped as
  `SKIPPED_ASSET_NOT_ELIGIBLE` because both were `NEEDS_REVIEW`. **The eligibility gate held under
  real conditions.** This is the single most important negative result of the run: the pipeline
  declined to touch the two files it was least confident about.
- **The 3 HEICs are untouched**, still excluded by the manifest classification.
- **Both service-account-created files exist in the Shared Drive:**
  `Site Visit Catalog - 2026-08 Executive - Parth Vaidya` (spreadsheet) and
  `Site Visit Report - 2026-08 Executive - Parth Vaidya - 20260918T10…` (document).

So the service account **demonstrably created files in the Shared Drive and renamed files in place.**
That settles the capability question behind seam risk 9: the earlier `drives.get` 404 inference was
simply wrong, and it has now been disproven at the point of use rather than argued about.

---

## Verified outcome

The end-to-end run succeeded, and the success was confirmed by reading the live systems rather than
by reading the job's own log.

**What is now true that was never true before:** the workflow renamed the operator's real source
videos in the Shared Drive, and it drafted an executive report into a real Google Doc. Both had
never been run. Both were created *by the service account, inside the Shared Drive*, with no
operator-account file creation and no personal Drive involved.

**Confirmed by independent read-back (S9):** 21 folder children = 16 videos + 3 HEICs + 2 new files;
14 videos renamed; 2 `NEEDS_REVIEW` videos left untouched; 3 HEICs untouched; Sheet and Doc present.

**Two imperfections, recorded honestly. Neither blocks the result.**

**1. One filename is ugly, and the cause is upstream.**
`IMG_3651.MOV` became
`1p-9pppEYKrgVPVIlG-dSp9Df7u4EstOw_multiple_hallway_issues.MOV`.
L1 emitted a `suggested_filename` that embedded the Drive ID as a prefix. `build_new_name`
sanitized it faithfully — it did its job correctly. The defect is in the L1 prompt, which does not
forbid putting the asset ID in the filename. **The seam here is that Gate 6 trusts L1's string for
meaning, not just for safety.** Sanitization checks that a name is *legal*; nothing checks that it
is *human-useful*, and a descriptive filename is the whole point of the rename.

**2. The report contains an arithmetic inconsistency.**
It opens with "16 clips were reviewed. Of these, 15 clips produced specific findings, while 2 clips
require further human review" — 15 + 2 = 17. It then closes by saying "One clip could not be
assessed," contradicting the 2 it stated earlier. The true figures are **14 catalogued and 2
needs-review.**

This is the concrete, predicted cost of the design choice recorded in S5: the narrative gate is the
only unvalidated output in the system, and a 0.1.0 placeholder prompt with no lineage and no
`response_schema` produced exactly the kind of error that implies. The choice itself still looks
right — a weak narrative is recoverable where a wrong structured record is not, and the catalogue
figures are correct. But it means **the report cannot currently be forwarded to a reader without a
human checking its numbers against the Sheet**, and fixing this is the first item for the real
report prompt.

---

## S10 — Documentation and handoff

Everything is committed and pushed to `main` as **`c932cbd`**; local matches the remote exactly.
178 tests pass.

The evidence folder `docs/evidence/20260918-e2e-full-run/` holds the complete record:

| File | What it is |
| --- | --- |
| `FLOW.md` | This file — the **wiring narrative**: how each step connects to the next |
| `RESULT.md` | The **human-readable outcome** — what happened and what came out of it |
| `SCRATCHPAD.md` | The live plan, now closed out with the run result |
| `PRE-RENAME-STATE.md` | The folder as it stood before Gate 6 touched it |
| `manifest.json` | Gate 1 output — what was discovered and what was excluded |
| `run-summary.json` | The job's own self-report |
| `post-rename-drive-listing-raw.json` | The S9 independent read-back, raw |

The division of labour between the two prose documents matters: **`RESULT.md` tells you what
happened; `FLOW.md` tells you how the parts are joined and where the joins are weak.** Read
`RESULT.md` to learn the outcome, read this file before you change anything.

Note that `run-summary.json` and `post-rename-drive-listing-raw.json` are deliberately both
present — the claim and the independent check, kept side by side, so a future reader can compare
them rather than take the run's word for it.

---

## The two findings most worth carrying forward

Everything in **Seam risks** below is worth reading, but two entries are the real lessons of this
run and should not be lost in a numbered list.

### A feature can fail silently while every layer reports success (risk 16)

`IMG_3651.MOV` was renamed to
`1p-9pppEYKrgVPVIlG-dSp9Df7u4EstOw_multiple_hallway_issues.MOV`.

Nothing errored. L1 produced a `suggested_filename`, `build_new_name` sanitized it correctly and
preserved the extension, Drive accepted the rename, the catalogue recorded it, and the run reported
`RENAMED`. **Full green status, and the output is a name nobody would ever want.**

The gap is precise: sanitization proved the name was *legal*. Nothing asked whether it was *useful*
— and usefulness is the entire point of the rename feature. A pipeline that validates safety at
every step and meaning at none can pass all its checks while failing at its purpose. This is the
most instructive thing in the run, and it generalizes well beyond filenames.

### The report's bad arithmetic is a design error, not a prompt-quality problem (risk 17)

The report claims "15 clips produced specific findings, while 2 clips require further human review"
against 16 reviewed, then later says "One clip could not be assessed." The true figures are 14 and 2.

The tempting fix is a better prompt. **That is the wrong fix.** The counts already exist in code —
`status_counts` is computed from the catalogue records before the report is ever built. The actual
design error is asking a language model to perform arithmetic over numbers it was never given.

The remedy is one of two things, both cheap: pass the computed counts into the prompt as given
facts, or post-check the generated text against `status_counts` before `insertText` writes it to
the Doc. Until one of those exists, the report cannot be forwarded to a reader without a human
reconciling its figures against the Sheet.

---

## Seam risks

A running list of every coupling in this system that is implicit, undocumented, or held together by
convention rather than by a check. Seeded with the three failures this project has already had, and
extended as this run surfaces more.

1. **Runtime-read files that the image does not ship.** *(Historical — already bit us.)* A
   Dockerfile did not copy `prompts/`, but the code read prompt files from disk at runtime. The
   build was green; the run failed in the container only. This run adds `prompts/report-synthesis.md`
   as a *new* runtime-read file, so the exact same failure mode is live again.
   **Safer:** a startup assertion that every prompt the code can ask for exists on disk, failing
   fast at container start rather than mid-run; plus a build-time test that runs the image and
   lists the prompt directory.
   **AVOIDED this run, not closed.** The S7 build context (`apps/live-workflow`) included
   `prompts/`, so `report-synthesis.md` shipped and Gate 7 read it at runtime. But it was right
   because the context happened to be right — no check would have caught it being wrong. The
   remedy above is still unimplemented.
2. **An artifact uploaded by one step and re-uploaded by the next.** *(Historical.)* The WAV was
   staged to GCS by the media gate and then written a second time by transcription. The current
   code carries a comment marking this — Gate 2 uploads the attempt-0 WAV and passes
   `staged_wav_uri` into `_gate3_transcribe`, which "must not write that object a second time."
   The correctness of that is a comment plus a parameter, not an invariant.
   **Safer:** make the upload idempotent by object name and have the transcription gate accept only
   a URI, with no ability to upload at all.
3. **A resource built from the wrong region variable.** *(Historical.)* A recognizer was constructed
   from the wrong location setting. `config.py` deliberately keeps `speech_location` (default `us`)
   and `vertex_location` (default `us-central1`) as separate fields with a comment explaining why,
   and `region` is a third, distinct value. Three region-ish variables in one settings object is a
   standing hazard, and the new Docs call adds a fourth service with its own location semantics.
   **Safer:** name the fields by the service they belong to everywhere they are used, and never pass
   a bare `location` string between modules.
4. **Prose approval vs. environment flag.** The rename authorization lives in `SCRATCHPAD.md`; the
   code will gate on a run-level flag. Nothing binds them. A future run that inherits the flag in a
   Job config renames files with no human in the loop.
   **Safer:** require the approval to be an explicit CLI argument per run, never a Job-level env
   var, and echo the approving operator into the evidence record.
   **Largely addressed in S6:** Gate 6 requires **both** `RENAME_APPROVED` and `--rename-approved`,
   so an inherited env var cannot rename anything on its own. Still open: the prose approval in
   `SCRATCHPAD.md` and the machine flags remain unconnected, and no operator identity is recorded.
5. ~~**Two new external resources created by hand.**~~ *(Superseded by the S3/S4 revision — the job
   now creates both artifacts itself. Kept for the record; the premise, that the service account
   could not create files in the Shared Drive, was false. See risk 9.)* The residual version of this
   risk is smaller but still live: `docs.googleapis.com` enablement remains an external
   precondition that fails only at first write.
   **Safer:** extend the existing `preflight.py` / `auth-preflight` command to probe every API the
   run will use before any media is processed.
6. **`suggested_filename` is unvalidated input to a destructive-ish operation.** It comes out of an
   LLM, goes into the catalogue, and Gate 6 will use it as a real Drive filename. Nothing checks it
   for length, illegal characters, or collisions with a sibling file.
   **Safer:** sanitize and de-duplicate before rename, and record both old and new names in the
   evidence row (the plan does record `original_drive_name`, which is good).
   **Mostly addressed in S6:** `build_new_name` sanitizes the stem, preserves the original
   extension, and returns `None` to skip. Still open: **collision with a sibling file is not
   mentioned** — two clips whose L1 proposes the same filename would both be renamed to it.
7. **Ordering dependency between the rename gate and the catalogue.** Gate 6 needs the L1
   `suggested_filename`, which is produced inside the per-asset loop; Gate 7 needs the run's
   catalogue rows, which are only complete after the loop ends. Whether Gate 6 runs inside the loop
   or as a second pass changes the failure semantics (a mid-run crash leaves a partially renamed
   folder either way, but only a second pass can skip assets that failed).
   **Safer:** make Gate 6 a distinct pass that reads the finished catalogue and refuses to act on
   any row whose `asset_status` is not `CATALOGUED`.
   **Addressed in S6:** Gate 6 is a distinct pass and only `CATALOGUED` assets with a validated L1
   are eligible; `NEEDS_REVIEW` and `FAILED` are never renamed. The *new* ordering dependency it
   creates — Gate 7 must run after Gate 6 to report post-rename names — is enforced only by call
   order, with no assertion.
8. **Self-reported success.** The job emits its own run summary JSON and that is what gets read.
   Nothing in the run reads back the Sheet, the Drive names, or the Doc to confirm the writes
   landed. S9 is a human doing that by hand.
   **Safer:** a verification pass in code that re-reads each written resource by ID.
   **SATISFIED for this run — by hand, not by code.** S9 deployed a second job,
   `site-visit-workflow-verify`, which re-listed the Shared Drive folder as the service account and
   confirmed 21 children, 14 renames, and 2 correct skips. That is a genuine independent read-back.
   It is not automated, so the next run gets no such check unless someone repeats it deliberately.
   Note also that Gate 7 building its report from in-memory records (S6) means the report is *not*
   a second opinion on the Sheet — read-back has to come from outside the run, as it did here.
9. **A capability boundary inferred from the wrong signal, with the contradicting evidence sitting
   in the same JSON.** *(Found in this run — see S3/S4.)* A `404` from `drives.get` was read as "the
   service account is not a Shared Drive member and cannot create files there." The same preflight
   output reported `canAddChildren: true` on the target folder, which says the opposite. The
   pessimistic reading won by default and shaped the plan for two whole steps, and it would have
   sent this run's outputs into a personal Drive instead of the Shared Drive the run exists to
   write into.
   **Safer:** test a capability at its point of use, not via an adjacent API call. If the question
   is "can this identity create a file in this folder," the answer is a `files.create` of a
   throwaway probe file in that folder — not an inference from a different endpoint. And when two
   fields in one response disagree, reconcile them before building on either.
   **SETTLED by S9.** The service account created both the Sheet and the Doc inside the Shared
   Drive and renamed 14 files in place. The `drives.get` 404 inference is now disproven by
   observation, and `canAddChildren: true` was the signal that had been right all along.
10. **The control plane runs on an expiring human credential; the data plane does not.**
    *(Found in this run.)* `gcloud` user credentials hit
    `Reauthentication failed. cannot prompt during non-interactive execution.` mid-run, blocking
    build, deploy, and execute. The workflow itself was fine — the *deployer* was not. Work
    continued only because ADC was still valid and the Cloud Run / Cloud Build / Service Usage REST
    APIs could be driven with that token directly. A long or unattended run can therefore die
    between steps for reasons entirely unrelated to the workflow.
    **Safer:** run the control plane under a non-expiring identity (a deploy service account with
    workload identity or an impersonation chain), and fail loudly and early with a credential
    freshness check rather than mid-build. The silver lining worth keeping: the ADC token's scope is
    `cloud-platform` only, with **no Drive scope**, so the control-plane/data-plane identity split is
    provable rather than merely intended.
11. **Documentation that asserts behaviour the code is about to stop having.** *(Live as of this
    run.)* Two statements in `cli.py` become false the moment Gate 6 lands:
    - `cmd_process_folder` hardcodes `"drive_rename": "NOT_ATTEMPTED; suggested names are proposals
      only."` into every asset summary. That string is written into the evidence record, so a stale
      claim does not just mislead a reader — it gets *archived as evidence*.
    - The module docstring above `cmd_process_folder` states the command "creates Drive nothing,
      renames Drive nothing, and deletes nothing anywhere." One third of that sentence stops being
      true with Gate 6, and another third stops being true now that the job creates its own Sheet
      and Doc. Only "deletes nothing" survives — and that one is the load-bearing safety claim, so
      burying it in a sentence whose other clauses have gone stale actively devalues it.
    **Safer:** derive the `drive_rename` field from what actually happened rather than hardcoding
    it, and split the docstring's safety claims apart so the invariant that must never change
    ("deletes nothing, anywhere") stands alone and is not eroded by its neighbours drifting.
    **CLOSED in S6.** The per-asset record now carries the real outcome plus a
    `drive_rename_decision` of `RENAMED_TO:<name>` or the real skip reason, and the "deletes
    nothing" clause was separated out to stand alone.
12. **The installed package points at a different source tree than the one being edited.**
    *(Found in this run.)* `pip` has this package installed editable against
    `apps/live-workflow.worktrees/pasted-text-processing/src`, **not** `apps/live-workflow/src`.
    Running `python -m pytest` from the primary folder imports the **worktree** copy and cannot find
    the new `rename.py` / `report.py` modules at all; the run had to set `PYTHONPATH` explicitly to
    get a true result. The image is unaffected, because the Dockerfile copies `src` from the build
    context — and that divergence is exactly the danger: **local test results and image contents can
    disagree silently, in either direction.** A green local suite can be testing code that will
    never ship, and shipped code can be untested. This is the Drive-sync duplicate-tree hazard from
    the root `CLAUDE.md` resurfacing as an import-path problem.
    **Safer:** reinstall the package editable against the primary tree and add a test that asserts
    `site_visit_workflow.__file__` resolves under the expected root, so a mismatched install fails
    the suite instead of quietly changing what the suite means.
13. **The new Drive name is not a catalogue column.** Adding one would be a header change and a
    migration of `FULL_CATALOG_HEADERS`, so the new name lives only in the run summary, the
    per-asset evidence JSON, and the report input. **The Sheet therefore records that a rename
    happened but not, in a column, what the file became.** Anyone reconciling the Sheet against
    Drive by name has to go to the GCS evidence to do it.
    **Safer:** append (never insert) a `new_drive_name` column to `FULL_CATALOG_HEADERS` — the
    module comment already documents append-only as the supported way to add a column — so the
    catalogue stays self-sufficient.
14. **`report.py` depends on three private helpers in `extraction.py`** — `_VERSION_PATTERN`,
    `_fenced_block`, and `_sdk_version`. Reuse beats duplication here, so the instinct is right, but
    the underscore prefix declares "private, may change freely" while a second module now relies on
    that promise not being kept. Nothing enforces the contract in either direction.
    **Safer:** promote the three to public names in `extraction.py`, or move them to a small shared
    module that both import from, so the dependency is visible in the name rather than only in an
    import line.
15. **A dry run does not exercise the two newest gates.** Dry runs skip Gates 6 and 7 entirely, so
    `rename_summary` is empty and no report is produced. The cheap, safe rehearsal mode therefore
    gives **no coverage at all of the riskiest and least proven parts of the pipeline** — the only
    way to test rename and report is to actually rename and actually write.
    **Safer:** give both gates a dry-run path that resolves and logs what it *would* do —
    computing each `build_new_name` result and rendering the report to GCS instead of the Doc —
    so a dry run can catch a bad filename or a missing prompt before anything is mutated.
16. **Nothing checks that a suggested filename is *meaningful*, only that it is *legal*.**
    *(Observed in this run.)* `IMG_3651.MOV` became
    `1p-9pppEYKrgVPVIlG-dSp9Df7u4EstOw_multiple_hallway_issues.MOV`, because L1 emitted a
    `suggested_filename` with the Drive ID as a prefix. `build_new_name` behaved correctly — it
    sanitized a legal name and preserved the extension. The gap is that **Gate 6 trusts L1's string
    for meaning as well as for safety**, and the L1 prompt does not forbid embedding the asset ID.
    A descriptive filename is the entire purpose of the rename, so a legal-but-useless name is a
    silent failure of the feature even though every component reported success.
    **Safer:** forbid it at both ends — add an explicit instruction to the L1 prompt, and have
    `build_new_name` reject or strip a stem that begins with something shaped like a Drive ID.
    This is also an argument for the dry-run coverage in risk 15: a rehearsal that printed proposed
    names would have caught this before the file was renamed.
17. **The one unvalidated output produced a wrong number on its first real run.**
    *(Observed in this run.)* The report says "16 clips were reviewed. Of these, 15 clips produced
    specific findings, while 2 clips require further human review" (15 + 2 = 17), then later "One
    clip could not be assessed," contradicting itself. True figures: 14 catalogued, 2 needs-review.
    The design choice from S5 — plain text, no `response_schema`, because a weak narrative is
    recoverable where a wrong structured record is not — still looks correct, and the catalogue
    numbers are right. But the report is the artifact a human actually reads, and it currently
    **cannot be forwarded without someone checking its figures against the Sheet.**
    **Safer:** stop asking the model for arithmetic it can get wrong. Compute the counts in code
    from the catalogue records and pass them into the prompt as given facts, or post-check the
    rendered text against the known `status_counts` before writing to the Doc. First item for the
    real (non-placeholder) report prompt.

## How to update this later

- This file is append-and-amend only. Do not delete a section because a step was redone — add what
  changed and why, in place, under the relevant `## Sx` heading.
- One `## Sx — <name>` section per step. Each section must answer four questions in prose: what the
  step did, **exactly where its artifact lives** (Drive ID, GCS URI, absolute file path, Sheet ID —
  concrete identifiers, never "the Sheet"), what the next step needs from it, and what broke at the
  seam.
- When a step reveals a new implicit coupling, add it to **Seam risks** with a concrete "safer"
  remedy. That list is the point of the document.
- Keep the **Step map** table in sync with reality. If a step turned out to produce something
  different from the plan, correct the table and say so in the step's own section.
- Never claim something was verified unless verification actually happened and is described.
  An admitted gap beats a silent one (LD-7).

---

## Where to start, if you are new to this

Read `RESULT.md` first for what this run produced, then come back to this file and read it
straight through — the `## Sx` sections are in execution order and the seams only make sense in
sequence. Read **Seam risks** before you change any code, because most of what is fragile here is
fragile in a way the source does not show: an ordering that only call order enforces, a prompt the
image has to remember to ship, an output ID that is now produced by the run rather than given to
it. Then go to the source itself — `cli.py` for the gate structure, `rename.py` and `report.py` for
the two newest and least proven gates. If you only take two things from this document, take the two
findings above.
