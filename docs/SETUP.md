# Setup guide

## Objective

This file covers the first live setup step before the workflow can run.

## Prerequisites

- GitHub repo access
- Google Cloud project and billing enabled
- service account with required permissions
- Python or Node available locally
- working clone of this repo

## Repository structure

```text
apps/live-workflow/
├── README.md
├── .env.example
├── docs/
├── prompts/
├── apps/
├── services/
├── libs/
├── infra/
├── scripts/
├── data/
├── tests/
└── .gitignore
```

## Intake library setup

The live app intake library is a Google Drive Shared Folder, not a local folder.

For the first validation pass, use this shared folder:
- https://drive.google.com/drive/folders/1VnKg4XG_sxp9PhA76OgatkAYGhR1sjmy?usp=drive_link

This will be treated as the source-of-truth test library while the pipeline is being built.

## First steps

1. verify this workspace is the active live path
2. confirm access to the Google Drive shared folder above
3. copy `.env.example` to `.env` and fill in real values
4. confirm the Google Cloud project and service account
5. validate that the environment can authenticate before file processing begins

## Validation checklist

Before moving to Phase 2, ensure:
- this workspace is the active canonical path
- GitHub is the source of truth for code and docs
- the Google Cloud project and auth are validated
- the folder layout is stable and easy to extend

## Update path

When a new service is added, update this file with setup notes, env vars, and validation steps.
