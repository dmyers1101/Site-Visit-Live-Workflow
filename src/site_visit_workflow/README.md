# Workflow package

`site-visit` is a Python 3.11 CLI. Imports and `config-check` do not call
Google. `intake`, `stage-video`, `transcribe`, `rename-drive`, and
`publish-catalog` are explicitly named external actions. All source selection
is constrained by a manifest created from one immediate visit folder.

The domain contracts in `models.py` preserve original Drive identifiers and
names, enforce the L1 allow-list, make catalog rows idempotent by Drive ID,
and require a matching approval record before mutation.

## How to update this later

Add a contract test before changing a model, status, or CLI argument. Preserve
the manifest schema and immutable Drive fields; version any incompatible
schema change and amend the appropriate prompt and runbook in the same change.
