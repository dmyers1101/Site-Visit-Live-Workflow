# ADR 0005: dedicated GCS staging bucket the workflow cannot delete from

## Status

Accepted

## Context

ADR 0004 puts a staging bucket in the middle of the media path. That bucket
holds the only cloud-side copy of transcoded audio and the workflow artifacts
derived from it, so it is evidence. The immutable-source policy of ADR 0002
protects the Drive originals; nothing yet protected the staged derivatives.

Cloud Storage offers `roles/storage.objectUser` as the convenient "read and
write objects" role. It also carries `storage.objects.delete`. Granting it
would mean a bug, a bad retry, or a prompt-injected instruction could erase
staged evidence with no human in the loop.

Before this run the project had only `shir-sitevisit-pilot` and
`shir-sitevisit_cloudbuild`; there was no staging bucket [VERIFIED — preflight
`raw/buckets.txt`].

## Decision

Create and use a dedicated staging bucket `gs://shir-sitevisit-staging`,
US multi-region, with uniform bucket-level access enabled. The runtime service
account `site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com` holds
exactly three roles on it:

| Role | Why |
| --- | --- |
| `roles/storage.objectCreator` | write the staged WAV and workflow artifacts |
| `roles/storage.objectViewer` | read them back, and let Speech-to-Text-adjacent code verify them |
| `roles/storage.legacyBucketReader` | `storage.buckets.get`; without it bucket metadata reads return 403 |

`roles/storage.objectUser` is deliberately **not** granted. It was briefly
granted at 06:20 UTC on 2026-09-17 while standing the bucket up, then removed
at 06:21 UTC and replaced with the creator/viewer pair [VERIFIED — preflight
`commands.md`; `change-log.md`]. That removal withdrew a permission; no data
was deleted. `legacyBucketReader` was added at 06:28 UTC to resolve an observed
`storage.buckets.get` 403.

## Consequences

No role held by the workflow carries `storage.objects.delete`, so the workflow
**physically cannot** delete a staged artifact. Cleanup of the staging bucket
is a separate, human-authorized operation performed by the deployer identity,
not something the pipeline does as a housekeeping step.

The staging bucket therefore grows monotonically until a human prunes it.
[OPEN] No lifecycle policy is set. A lifecycle rule is the natural answer, but
it is an automated deletion mechanism and deserves its own decision — it is not
smuggled in here. Until one exists, treat storage growth as a cost item to
watch.

Because objects cannot be overwritten away either, object naming must be
collision-free by construction: stage under a run-scoped prefix keyed to the
immutable Drive file ID, so a re-run writes a new object rather than fighting
an existing one.

Uniform bucket-level access means no per-object ACLs. All access decisions are
IAM decisions and are visible in one bucket policy — which is what makes the
absence of delete auditable at a glance.

## How to update this later

Do not grant `roles/storage.objectUser`, `roles/storage.admin`, or any custom
role containing `storage.objects.delete` to the runtime service account. If a
retention or lifecycle policy becomes necessary, write a new ADR that states
what may be deleted, after how long, and who authorized it; supersede this one
rather than quietly widening the role set. Re-verify the bucket IAM in each
future dated preflight.
