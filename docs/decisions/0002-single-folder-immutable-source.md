# ADR 0002: single-folder intake and immutable-source policy

## Status

Accepted

## Context

The live workflow needs a safe first production-like test without treating exploratory pilot behavior as authoritative. Source Drive videos are evidence and automated descriptive names can be wrong.

## Decision

Process one explicitly selected visit subfolder and one approved video at a time. Create a manifest before processing. Preserve original Drive file ID and name in every downstream record. Treat extraction-derived descriptive names as proposals; human approval is required before a rename or catalog publication.

## Consequences

The first pass favors auditability over throughput. Multi-folder concurrency, automatic renames, reports, and task integrations are out of scope. Empty transcripts receive one retry and then `NEEDS_REVIEW`, never a successful finding.

## How to update this later

Supersede this ADR only after measured single-folder results show that a broader automation policy preserves traceability and review controls.
