# Live workflow architecture

## Goal

The live workflow is a simple processing chain:

1. a site visit video is uploaded to the live library
2. the video is transcribed
3. the file is renamed descriptively
4. the result is cataloged in Google Sheets
5. the visit is synthesized into a draft report

## Source of truth

- GitHub holds the versioned repo, docs, prompts, and operational notes.
- Google Cloud handles the processing layer.
- `pilot/` remains read-only reference material, not active implementation.

## Service split

### apps/
- review and reporting surfaces
- kept thin and easy to understand

### services/
- ingestion
- transcription
- rename / extraction
- catalog export
- synthesis
- reporting
- shared helpers

### libs/
- reusable config, helpers, cloud wrapping, and model definitions

### infra/
- deployment and environment bootstrap notes

## Update model

Any new component should document its purpose, trigger, inputs, outputs, env vars, and a short “how to update this later” note.
