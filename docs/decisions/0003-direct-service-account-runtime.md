# ADR 0003: direct service-account runtime and explicit boundaries

## Status

Accepted

## Context

The first live workflow needs a deployable identity without distributing JSON
keys and must not accidentally contact Google or mutate sources while testing.

## Decision

Cloud Run Jobs attach
`site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` directly and use
ambient ADC. The code uses only the directly attached runtime identity; it
does not accept a credential-file setting. Google interactions occur only in
named CLI commands. Manifest creation precedes staging, one asset is allowed,
and independent approval records gate Drive rename and Sheets publication.

## Consequences

The job needs resource-level sharing/IAM and cannot silently fall back to a
personal identity. Operators retain manifests, transcription records, prompt
payloads, and approvals as audit evidence. Cloud tests remain an operational
step, not a claim in source control.

## How to update this later

Supersede this ADR only with an identity-threat review, migration plan,
credential-factory tests, and matching deployment/runbook changes.
