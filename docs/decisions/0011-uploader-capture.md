# ADR 0011 — Uploader is the Drive account that uploaded the clip

## Status
Accepted (2026-09-29).

## Context
Operator chose the Drive uploader (not the name in the visit folder title) for
the report tab title. In a Shared Drive files have no `owners`, and a Gate 6
rename makes the service account the file's `lastModifyingUser`.

## Decision
- Uploader = `lastModifyingUser` at discovery, **unless** that is the runtime
  service account, in which case the file's **first revision** user is used
  (`portfolio.resolve_uploader`, `DriveGateway.first_revision_user`).
- Captured before Gate 6 and written to `uploader_email` / `uploader_name`.
- Unknown stays blank and the tab says "Unknown uploader" — never guessed.

## Consequences
- Drive reports the account's display name, which may be a shared login (e.g.
  `paregional`) rather than a person's full name. If a human name is wanted,
  add a lookup table (email → name) in a new ADR.
- If a human edits/renames a clip before discovery, they become the uploader.
