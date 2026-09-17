# Source map — Phase 2 authorization preflight

**Run ID:** `20260917T055321Z-phase2-auth-preflight`

## Governing prompt

- `prompts/claude-overnight-phase2-trial.md` (v1.1) — read in full first.
  **Note:** the prompt directs work to `apps/live-workflow`, but the file itself
  and all Phase 2 code/docs exist only in the worktree
  `apps/live-workflow.worktrees/pasted-text-processing` (branch
  `agents/pasted-text-processing`). Same repo, same remote. Work was done there.
  The file is currently **untracked** in git.

## Live documents read

| Path | Present | Note |
| --- | --- | --- |
| `README.md` | yes | |
| `docs/ARCHITECTURE.md` | yes | |
| `docs/SETUP.md` | yes | |
| `docs/AUTH.md` | yes | |
| `docs/OPERATIONS.md` | yes | |
| `docs/DEPLOYMENT.md` | yes | Contains the deploy command template with `BUCKET`/`SHEET_ID` placeholders |
| `docs/RUNBOOKS/drive-intake.md` | yes | |
| `docs/RUNBOOKS/transcription.md` | yes | |
| `docs/RUNBOOKS/catalog.md` | yes | |
| `docs/RUNBOOKS/service-account-onboarding.md` | yes | |
| `docs/RUNBOOKS/drive-access-recovery.md` | yes | |
| `docs/research/gcp/` | yes | `README.md`, `api-research.md`, `speech-to-text-v2.md`, `drive-api-v3.md` |
| `docs/evidence/` | yes | `direct-service-account-drive-read-2026-09-16.md` + this run |
| `prompts/` | partial | `l2-enrichment.md` and `l3-refinement.md` **absent** |

## Prompt inventory

| File | Present |
| --- | --- |
| `drive-intake.md` | yes |
| `l1-extraction.md` | yes |
| `l2-enrichment.md` | **NO** |
| `l3-refinement.md` | **NO** |
| `catalog-row.md` | yes |
| `prompt-governance.md` | yes |

## Pilot reference (read-only, not treated as current fact)

`pilot/` was **not** modified. Pilot model IDs, library versions, and API
behavior were explicitly revalidated against current official documentation
rather than reused:

- Chirp model id and region — revalidated 2026-09-17 against
  `docs.cloud.google.com/speech-to-text/v2/docs/chirp_3-model`.
- Vertex model IDs — revalidated 2026-09-17; `gemini-2.5-flash` currently
  available. Pilot's model ID was not assumed valid.

## Files created by this preflight

- `docs/evidence/20260917T055321Z-phase2-auth-preflight/` (this directory)
- `src/site_visit_workflow/preflight.py` (new, read-only checks)
- `src/site_visit_workflow/cli.py` (added `auth-preflight` command)
- `pyproject.toml` (added `google-genai`)

## Files NOT changed

`pilot/`, `_design/`, and every Drive source video. Nothing was deleted.

## How to update this later

Create a new dated directory per preflight run; never overwrite this one.
