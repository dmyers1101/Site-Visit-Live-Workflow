# Phase 2 new-session prompt

Use this prompt in a fresh session for the live transcription + rename + catalog pipeline.

## Objective

Continue the live-build workflow in `apps/live-workflow`, starting from the current documentation and the proven lessons from the reference sandbox `pilot/`.

Build Phase 2 only:
1. upload a clip into the live workflow
2. transcribe it using the verified Google Cloud path
3. rename it descriptively
4. catalog it in a structured output such as Google Sheets
5. record the result and any failures in a maintainable way

Do not move into Phase 3 or Phase 4 yet. The goal is to get the live pipeline working solidly before report generation.

## Required operating context

Read these first, in this order:
1. `apps/live-workflow/README.md`
2. `apps/live-workflow/docs/ARCHITECTURE.md`
3. `apps/live-workflow/docs/SETUP.md`
4. `apps/live-workflow/docs/AUTH.md`
5. `apps/live-workflow/docs/OPERATIONS.md`
6. `pilot/README.md`
7. `pilot/SETUP_LOG.md`
8. `pilot/GOTCHAS.md`

Use the pilot files as reference only, not as the active implementation path. The live build is the working repo. Do not write into `pilot/` unless you are intentionally copying a proven pattern into the live repo.

## Pilot prompts to use initially

Use the following pilot references as the starting prompt patterns for the live pipeline:
- `pilot/README.md` — objective, engine choices, and boundaries
- `pilot/SETUP_LOG.md` — verified environment, API setup, library versions, and exact working pipeline steps
- `pilot/GOTCHAS.md` — the known failure modes and fixes that prevent repeat mistakes
- `pilot/logs/..._L1_prompt.txt` — initial extraction prompt pattern for taking transcript text and returning structured output

Do not treat the step5 report prompts as the initial pipeline prompt. They are for report-generation patterns later, not for the upload/transcribe/catalog workflow.

## Working rules

- Work inside `apps/live-workflow` only.
- Keep prompts separate from code; store prompt wording in `apps/live-workflow/prompts/`.
- Preserve the source-of-truth model: GitHub for docs and code, Google Cloud for processing.
- Use the verified Google stack from the pilot: Chirp + Cloud Speech v2, Gemini Flash on Vertex AI, and the audio extraction step before transcription.
- Respect the hard lessons from the pilot:
  - extract audio before Chirp because `.MOV` files do not transcribe directly
  - upload to GCS before BatchRecognize
  - use a single-file or low-concurrency transcription approach to avoid quota errors
  - document environment and Python version issues explicitly
- Keep the implementation simple and beginner-friendly.
- Create/update documentation when you add a new workflow step, service, or config.

## Deliverables for this phase

Produce and document the following:
- a clear ingestion entry point for a video asset
- a transcription step using the verified Google Cloud environment
- a descriptive rename step based on transcript content
- a structured catalog output path
- a short README or runbook for the phase
- a clear “how to update this later” note for each new component

## Acceptance criteria

- A real uploaded video can be processed through the live pipeline
- Transcript generation works using the verified Google flow
- Rename output is descriptive and consistent
- Catalog output is created in a maintainable structured format
- The pipeline is documented so another contributor can resume without re-deriving the setup
- The work remains inside the live repo and not inside `pilot/`

## Final instruction

Start by creating the minimal Phase 2 implementation plan in the live repo, then build the first working end-to-end path. Keep the first pass focused on reliability over elegance. At the end, provide a short summary of what was implemented, what was copied forward from the pilot, and what was left behind.
