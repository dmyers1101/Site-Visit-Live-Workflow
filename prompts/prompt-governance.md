# Prompt governance

**Semantic version:** 1.0.0

## Purpose

Govern prompt changes and approved external L1 execution without permitting
automatic model calls or bypassing the Drive/Sheets review boundary.

## Expected input JSON/text

```json
{"prompt_path":"string","semantic_version":"string","change_reason":"string","reviewer":"string","test_evidence":"string"}
```

## Exact prompt text

```text
Approve only a versioned prompt whose purpose, input, exact text, output
schema, validation rules, tests, and rollback plan are documented. External
execution is allowed only after this record names a reviewer and a specific
approved result is returned for local validation. No approval authorizes Drive
rename or catalog publication; each needs its own approval record.
```

## Output schema

```json
{"prompt_path":"string","semantic_version":"string","approved_by":"string","approved_at":"RFC3339","approval_record_id":"string","decision":"APPROVED|REJECTED","notes":"string"}
```

## Validation rules

- Reject unversioned prompts, schema/key changes without tests, or missing
  reviewer/record ID.
- Treat an approved model result as input only; validate it locally before use.
- Require separate `RENAME_DRIVE` and `PUBLISH_CATALOG` approval records.

## Safe update and Git rollback

Use a reviewed commit, update prompt version and tests together, and record
the decision. Roll back with `git revert <commit>` and select the prior
version explicitly; never overwrite audit payloads.

## How to update this later

Review this governance policy with every new external model, output field, or
automation boundary.
