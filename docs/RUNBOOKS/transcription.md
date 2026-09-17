# Runbook: transcription

## Purpose

Safely prepare and transcribe one approved video.

## Procedure

1. Stage a local copy without changing the Drive source.
2. Run `site-visit prepare-media` with the same manifest and selected asset ID
   to inspect it with `ffprobe`; retain duration, stream codec, and errors.
3. That command extracts mono 16 kHz WAV with `ffmpeg`; retain both staged
   media and WAV.
4. Explicitly run `site-visit transcribe` with a unique, clearly named GCS
   object path, attempt `0`, and one manifest asset ID.
5. It uploads the WAV and submits one Speech-to-Text v2 BatchRecognize
   `chirp_3` request; it does not wait for or invent a transcript.
6. Record request/operation identifiers, start/end timestamps, status, transcript GCS URI, and errors.

## Empty transcript policy

Use `site-visit evaluate-transcript` after retrieving an approved transcript
artifact. It returns `RETRY_ONCE` on attempt 0; submit the same retained
evidence at attempt 1. If that result is empty, it sets `NEEDS_REVIEW`; it is
not a valid maintenance finding.

## How to update this later

Record verified current model and SDK choices in the GCP research note before changing the request configuration.
