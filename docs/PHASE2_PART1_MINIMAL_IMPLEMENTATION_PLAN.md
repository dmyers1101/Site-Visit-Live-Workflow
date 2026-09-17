# Phase 2 Part 1 — minimal implementation plan

## Goal

Establish a safe, minimal working path for one site visit video subfolder before expanding to broader automation.

This is intentionally small: we are not trying to automate every folder in the library on day one. We are trying to prove the workflow on one real source folder and then scale from that pattern.

## Scope

Focus on one Google Drive Shared Folder only.

We will:
1. identify a single source folder in the shared Drive library
2. confirm the relevant media files inside it
3. connect that folder to the live workflow
4. run the verified processing path on one clip or one folder payload
5. keep the output documented and easy to extend

For this first pass, the source folder is:
- https://drive.google.com/drive/folders/1VnKg4XG_sxp9PhA76OgatkAYGhR1sjmy?usp=drive_link

## What is in scope

- choosing one source folder from the Drive library
- verifying the file types and structure inside it
- creating a minimal file-handling and processing flow for that folder
- using the proven pilot pipeline:
  - extract audio before transcription
  - upload audio to Google Cloud storage
  - transcribe with Chirp
  - convert transcript output into structured data
  - generate a descriptive rename
  - write a catalog row or simple structured output
- documenting the exact steps so a beginner can follow them later

## What is out of scope for this first pass

- automating all site visit folders at once
- full report generation
- Asana automation
- broad cleanup or refactoring
- adding new advanced integrations before the one-folder path works

## The working pattern

Use a single folder as the source of truth for this phase.

Example structure:

```text
library/
└── visit-2026-09-15/
    ├── clip-001.MOV
    ├── clip-002.MOV
    └── ...
```

The live workflow should do the following:

1. choose the source folder
2. inspect its files
3. process one chosen file or one whole folder payload
4. save transcript output
5. save rename suggestion output
6. save catalog entry output
7. record what succeeded and what failed

## Minimal deliverables

By the end of part 1, the live repo should have:

- a documented source folder selection step
- a minimal processing plan for one folder
- a local folder or script path for staging the selected videos
- a transcript output for at least one processed video
- a rename suggestion output
- a simple catalog record or output table
- a short note describing how to extend the workflow to other folders later

## Acceptance criteria

The minimal implementation is successful when:

- exactly one source folder is chosen as the initial working folder
- the workflow can read the files in that folder
- a real video is processed without using the old pilot path as the active working area
- a transcript exists for the processed video
- a descriptive rename is produced
- a structured catalog row exists
- the process is documented enough that a new person can continue later

## Documentation requirements

Update or create the following docs in the live repo:

- `README.md` — note that Phase 2 is starting with a single folder
- `docs/ARCHITECTURE.md` — note the source folder flow
- `docs/SETUP.md` — add the folder selection and staging instructions
- `docs/OPERATIONS.md` — add the basic one-folder operational runbook
- `prompts/phase2-agent-system-prompt.md` — the stricter prompt for the next session

## How to update this later

When the workflow is ready for more folders:

- add a folder-picker and validation step
- add a queue or manifest for all source folders
- move from single-file processing to per-folder batch processing
- add observability and retry logic

Do not broaden the scope before the first folder path is proven stable.
