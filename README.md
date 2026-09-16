# Live Site Visit Workflow

This is the active live-build workspace for the Site Visit App.

It is intentionally separate from `pilot/` and from the frozen `_design/` record. `pilot/` remains a reference sandbox only; the live workflow is the operational path for current work.

## Purpose

This workspace coordinates:
- GitHub as the live source of truth across devices
- Google Cloud as the processing platform for transcription and downstream output
- human review checkpoints before publishing generated work

## Phase plan

1. Foundation / setup / authorization
2. Live transcription + rename + catalog pipeline
3. Auto report generation
4. Hardening / handoff

## Working boundaries

- `pilot/` is not the active build path
- `prompts/` holds prompt templates, not runtime code
- `docs/` is the canonical operating record
- each service/app should include a README and a short update note

## First milestone

The first milestone is the foundation: secure setup, auth, and a clear handoff path before executing a live pipeline.

See:
- `docs/ARCHITECTURE.md`
- `docs/SETUP.md`
- `docs/AUTH.md`
- `docs/OPERATIONS.md`
