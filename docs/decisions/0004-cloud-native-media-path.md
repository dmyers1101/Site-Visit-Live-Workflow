# ADR 0004: cloud-native media path — Drive to Cloud Run to GCS, never to a workstation

## Status

Accepted

## Context

Site-visit media lives in Google Drive. Speech-to-Text v2 will not read from
Drive: `BatchRecognize` accepts a `gs://` URI and nothing else [VERIFIED —
`docs/research/gcp/speech-to-text-v2.md`, retrieved 2026-09-17]. A cloud-side
hop between Drive and Cloud Storage is therefore mandatory, not a convenience.

The alternative — an operator downloading clips to a laptop, transcoding
locally, and uploading the result — recreates exactly the laptop prototype this
project exists to replace. It also puts unreviewed evidence on personal storage
and makes the pipeline unrunnable when that machine is off.

The Phase 2 preflight confirmed the access this path needs. The service account
holds `canDownload: true` and `canDelete: false` on the 16 `video/quicktime`
files in `1Q_VVIbFKSZQCNVsaNW8pxxAMAwbIAoMF` [VERIFIED — preflight run
`20260917T055321Z-phase2-auth-preflight`, execution `lhplp`]. `canDownload`
exists so the **cloud job** can read bytes, not so a person can.

## Decision

Media is never downloaded to an operator workstation. Bytes flow

    Google Drive → Cloud Run container (ephemeral) → gs://shir-sitevisit-staging

and nowhere else. The only copy that leaves Drive lives inside the Cloud Run
Job container for the duration of one execution, is transcoded to WAV there,
and is written to the staging bucket for Speech-to-Text to read. The container
filesystem is discarded when the execution ends. Drive `canDownload` is granted
to the runtime service account for this purpose alone.

## Consequences

Cloud Run `/tmp` is an in-memory tmpfs and counts against the container memory
limit; it is not free disk. The job must therefore be sized for the largest
single video it will handle, or stream Drive → ffmpeg → GCS without buffering
whole files. The preflight configuration of 1Gi / 600s is too small for
site-visit video and is recorded as blocker 7 in
`docs/evidence/20260917T055321Z-phase2-auth-preflight/go-no-go.md`
[VERIFIED]. Raise memory to 4–8Gi and the task timeout accordingly, or adopt
streaming, before the first end-to-end asset.

Two further consequences follow. There is no local artifact to inspect when a
transcode fails, so container logs and the staged WAV in GCS are the only
forensic evidence — both must be retained. And egress and transcode cost move
from a laptop to the project's billing account, which is the intended trade:
the pipeline runs without a person present.

[OPEN] Whether the job buffers or streams is not settled here; ADR 0004 fixes
the path, not the buffering strategy.

## How to update this later

Supersede this ADR only if Speech-to-Text gains a Drive-native source, or if a
measured run shows streaming and buffering are both unworkable at the required
video size. Any change must keep the invariant that media never lands on an
operator workstation. Re-pull `docs/research/gcp/speech-to-text-v2.md` first.
