# Drive intake prompt

**Semantic version:** 1.0.0

## Purpose

Constrain a human or approved tool to one configured Shared Folder, its
immediate visit subfolders, and the immediate video files of exactly one
selected visit. This prompt does not authorize download, rename, or deletion.

## Expected input JSON/text

```json
{"shared_folder_id":"string","selected_visit_id":"string","immediate_visits":[],"immediate_files":[]}
```

## Exact prompt text

```text
Use only shared_folder_id. Confirm selected_visit_id is one of its immediate
folder children. Inspect only immediate_files in that selected visit. Return
video files only, preserving each Drive ID and original name exactly. Do not
recurse, select another visit, download media, modify Drive, or infer values.
```

## Output schema

```json
{"visit":{"drive_id":"string","name":"string","web_view_link":"string|null"},"media_files":[{"drive_id":"string","original_name":"string","mime_type":"video/*","web_view_link":"string|null","size_bytes":"integer|null","modified_time":"RFC3339|null"}]}
```

## Validation rules

- Exactly one selected immediate visit; reject all other selections.
- Each file must be an immediate child and `mime_type` must start `video/`.
- Drive IDs and original names are immutable manifest evidence.

## Safe update and Git rollback

Make a reviewed, version-bumped change with matching contract tests and
runbook updates. Roll back with `git revert <commit>`; never edit a prior
manifest to simulate a new prompt version.

## How to update this later

Keep the one-folder, one-visit boundary unless an ADR and tests explicitly
approve a broader scope.
