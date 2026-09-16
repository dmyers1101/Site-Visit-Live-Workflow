# ADR 0001: establish the live build foundation

## Status
Accepted

## Context
The project needs a clean, active workspace separate from the exploratory `pilot/` work. The live build needs to be durable, beginner-friendly, and usable across devices.

## Decision
We will use `apps/live-workflow` as the active live workspace, with GitHub as the source of truth and Google Cloud as the processing engine. The repo will include setup, auth, architecture, and operations docs.

## Consequences
- the active workflow is separate from pilot experimentation
- the architecture can be resumed without re-deriving the system
- future changes have a clear documentation and update path
