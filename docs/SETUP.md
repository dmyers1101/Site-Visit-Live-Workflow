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

## First steps

1. verify this workspace is the active live path
2. copy `.env.example` to `.env` and fill in real values
3. confirm the Google Cloud project and service account
4. validate that the environment can authenticate before file processing begins

## Validation checklist

Before moving to Phase 2, ensure:
- this workspace is the active canonical path
- GitHub is the source of truth for code and docs
- the Google Cloud project and auth are validated
- the folder layout is stable and easy to extend

## Update path

When a new service is added, update this file with setup notes, env vars, and validation steps.
