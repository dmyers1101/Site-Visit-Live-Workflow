# Live Site Visit Workflow

This is the active live-build workspace for the Site Visit App.

It is intentionally separate from `pilot/` and from the frozen `_design/` record. `pilot/` remains a reference sandbox only; the live workflow is the operational path for current work.

## Purpose

This workspace coordinates:
- GitHub as the live source of truth across devices
- Google Cloud as the processing platform for transcription and downstream output
- human review checkpoints before publishing generated work

## The cloud-native model (current)

The workflow runs as a **Cloud Run Job**, not on an operator workstation.

```text
Google Drive folder
  -> Cloud Run Job container (ephemeral /tmp)
  -> Google Cloud Storage staging bucket
  -> Speech-to-Text v2 (Chirp 3) -> Vertex AI (Gemini) -> Google Sheets catalog
```

- **Media never touches an operator workstation.** Bytes go Drive -> container -> GCS.
  A laptop is used only to *build and deploy* the image and to *read* the results.
- **Runtime identity:** `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com`,
  attached directly to the job, using ambient ADC from the metadata server.
  No key file, no impersonation, no personal Drive OAuth. Zero user-managed keys exist.
- **The deployer is not the runtime.** The human who runs `gcloud builds submit` and
  `gcloud run jobs deploy` is never the identity that reads Drive. See `docs/AUTH.md`.

| Resource | Value |
| --- | --- |
| Project | `shir-sitevisit` |
| Region (Cloud Run) | `us-central1` |
| Cloud Run Job | `site-visit-workflow` |
| Runtime service account | `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` |
| Staging bucket | `gs://shir-sitevisit-staging` (US, uniform access, **no delete permission**) |
| Drive source folder | `1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF` — "2026-08 Executive - Parth Vaidya" |
| Catalog Sheet | `158eA2K5FgGc4dQ43xHxdTuri-KOwPSuNn8qQqsasBy0` — "Site Visit Catalog — Live Workflow", tab `Catalog` |
| Speech | model `chirp_3`, `SPEECH_LOCATION=us` (the `us` **multi-region**, not `us-central1`) |
| Extraction | `google-genai` SDK, `gemini-2.5-flash`, `VERTEX_LOCATION=us-central1` |
| Container | Python 3.11.16 + ffmpeg 7.1.5 / ffprobe |
| GitHub | `dmyers1101/Site-Visit-Live-Workflow`, working branch `agents/pasted-text-processing` |

## Quickstart on a new machine

You need the Google Cloud CLI, Docker is **not** required (Cloud Build does the build),
Git, and a Google account with deploy rights on `shir-sitevisit`.

```powershell
# 1. Clone
git clone https://github.com/dmyers1101/Site-Visit-Live-Workflow.git
cd Site-Visit-Live-Workflow
git checkout agents/pasted-text-processing

# 2. Authenticate the DEPLOYER only. This identity never reads Drive media.
gcloud auth login
gcloud config set project shir-sitevisit

# 3. Build the image with Cloud Build
gcloud builds submit --config=infra/cloudbuild.yaml `
  --substitutions=_IMAGE=us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:latest .

# 4. Deploy / update the job (full command with sizing: docs/DEPLOYMENT.md)
gcloud run jobs deploy site-visit-workflow `
  --image=us-central1-docker.pkg.dev/shir-sitevisit/site-visit-workflow/site-visit:latest `
  --region=us-central1 `
  --service-account=site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com `
  --memory=8Gi --cpu=2 --task-timeout=3600s --max-retries=0 --tasks=1 --parallelism=1

# 5. Prove authorization before processing anything
gcloud run jobs execute site-visit-workflow --region=us-central1 --wait `
  --args=auth-preflight

# 6. Process one asset end to end, then the folder
gcloud run jobs execute site-visit-workflow --region=us-central1 --wait `
  --args=process-folder,--limit,1
```

No `.env` file is needed for the deployed path — the job carries its own environment
variables. A local `.env` is only for offline work (`config-check`, tests). Never set
`GOOGLE_APPLICATION_CREDENTIALS`.

Full detail: `docs/SETUP.md` (from zero), `docs/DEPLOYMENT.md` (exact commands),
`docs/RUNBOOKS/full-pipeline.md` (an end-to-end run).

## Python CLI

Install locally with `python -m pip install -e ".[test]"` (or install the
listed runtime dependencies and `pytest` separately), copy `.env.example` to
an untracked `.env`, then use `site-visit --help` (equivalently
`python -m site_visit_workflow.cli --help`).
Importing the package and `site-visit config-check`
do not contact Google.

### Command list

Read-only / offline:

| Command | What it does | Contacts Google |
| --- | --- | --- |
| `config-check` | Print resolved settings | No |
| `auth-preflight` | Read-only identity, Drive, GCS, Sheets and runtime report as one JSON record | Yes (read-only) |
| `list-folder-children` | List every immediate child of `DRIVE_SHARED_FOLDER_ID` | Yes (read-only) |
| `list-visits` | List only immediate *subfolders* of the configured folder | Yes (read-only) |

End-to-end (the current production path):

```text
site-visit process-folder [--limit N] [--asset-id ID] [--dry-run] [--run-id ID]
                          [--sheet-name NAME] [--prompts-dir DIR] [--work-dir DIR]
                          [--poll-timeout-seconds N] [--output PATH]
```

`process-folder` runs five gates sequentially, one asset at a time, and continues past a
single asset's failure:

1. **Gate 1** — discovery: classify direct children, write `manifest.json` to GCS.
2. **Gate 2** — stage from Drive, `ffprobe`, extract mono 16 kHz PCM WAV, upload to GCS.
3. **Gate 3** — Chirp `BatchRecognize`, poll, apply the one-retry empty-transcript policy.
4. **Gate 4** — L1 -> L2 -> L3 extraction on Vertex, each layer gated on the previous.
5. **Gate 5** — upsert one catalog row per asset keyed by the immutable Drive asset ID.

Single-step commands (still supported; used for narrow re-runs and diagnosis):
`intake`, `stage-video`, `prepare-media`, `transcribe`, `evaluate-transcript`,
`create-l1-request`, `accept-l1-result`, `draft-catalog`, `rename-drive`,
`publish-catalog`.

## Safety boundaries

- **Nothing is ever deleted.** Not a Drive file, not a GCS object, not a Sheets row or tab.
  The runtime service account holds no `storage.objects.delete` and Drive reports
  `canDelete: false`. Artifacts accumulate on purpose; cleanup is a separate,
  human-authorized action.
- **Drive media is immutable evidence.** `process-folder` never renames a Drive file.
  `suggested_filename` is a proposal recorded in the catalog
  (`drive_rename_decision = PROPOSED_ONLY_AWAITING_HUMAN_APPROVAL`).
  Renaming requires the separate `rename-drive` command plus an approval record.
- **GCS writes are guarded.** Every object write uses `if_generation_match=0`, so a
  collision fails loudly instead of overwriting.
- **The default `Sheet1` tab is never touched.** The code creates the `Catalog` tab if
  absent and upserts rows into it.
- **Processing boundary is direct media children.** Subfolders are recorded as excluded
  items with a reason, never traversed.
- **Sequential by design.** One task, parallelism one, one asset at a time.
- **No fabrication.** An empty transcript is retried exactly once; a second empty result
  is `NEEDS_REVIEW` with no extraction and no invented finding.

## Working boundaries

- `pilot/` is not the active build path
- `prompts/` holds prompt templates, not runtime code (they are read at runtime by
  `--prompts-dir`)
- `docs/` is the canonical operating record
- each service/app should include a README and a short update note

## Phase plan

1. Foundation / setup / authorization
2. One Drive folder test visit: manifest, media, transcript, catalog, review
3. Auto report generation
4. Hardening / handoff

### First live milestone (historical wording, superseded)

> Phase 2 starts with one configured Google Drive Shared Folder test visit. It
> discovers only immediate visit subfolders, selects exactly one, creates a
> manifest before one video is processed, and stops at human review. It never
> renames Drive media or publishes a catalog row without an explicit approval
> record.

**Superseded:** the confirmed Phase 2 boundary is the *direct media children* of one
configured folder — folder `1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF` holds 19 direct media
children and **zero** subfolders, so there is no subfolder to select. The
never-rename-without-approval rule still stands. The historical wording above is kept
because the `list-visits`/`intake` subfolder path still exists in the CLI.

For Phase 2, the intake library is a Google Drive Shared Folder, not a local folder. The first validation folder is:
- https://drive.google.com/drive/folders/1VnKg4XG_sxp9PhA76OgatkAYGhR1sjmy?usp=drive_link

> **Folder ID clarification (2026-09-17).** Two Drive folder IDs appear in this
> repository. `1VnKg4XG_sxp9PhA76OgatkAYGhR1sjmy` was the original first-pass
> validation folder named in the earlier planning notes above. The folder the
> Phase 2 pipeline is actually built and deployed against is
> **`1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF`** ("2026-08 Executive - Parth Vaidya"),
> the shared folder hosting the test video files. That is the value set in
> `DRIVE_SHARED_FOLDER_ID` on the deployed Cloud Run Job. The earlier ID is kept
> here as history, not as configuration.


See:
- `docs/ARCHITECTURE.md`
- `docs/SETUP.md`
- `docs/AUTH.md`
- `docs/OPERATIONS.md`
- `docs/PHASE2_PART1_MINIMAL_IMPLEMENTATION_PLAN.md`
- `docs/DEPLOYMENT.md`
- `docs/RUNBOOKS/full-pipeline.md`

## How to update this later

Keep the CLI command list, safety boundaries, and phase wording synchronized
with `docs/ARCHITECTURE.md`, the runbooks, and prompt versions. When a resource ID,
region, model, or image version changes, update the resource table above, `docs/SETUP.md`,
and `docs/DEPLOYMENT.md` in the same change, and record it in `CHANGELOG.md`.
