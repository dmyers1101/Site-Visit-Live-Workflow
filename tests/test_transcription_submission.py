"""The Chirp submission path must not re-upload an already-staged WAV.

A live trial run failed with `403 ... does not have storage.objects.delete
access` because the WAV was written twice: once by Gate 3's staging step and
again inside `submit_transcription`. The second write is an overwrite, and an
overwrite requires delete permission the runtime identity deliberately does
not hold (ADR 0005). These tests pin that fix.

No Google API is contacted: the Storage and Speech clients are replaced with
recorders, so an attempted upload shows up as a recorded call, not a request.
"""

from pathlib import Path

import pytest

from site_visit_workflow import google as sv_google
from site_visit_workflow.config import Settings
from site_visit_workflow.errors import ValidationError

ASSET = "1AbCdEfGhIjK"
BUCKET = "shir-sitevisit-staging"
OBJECT = f"site-visit-staging/20260917T060000Z/{ASSET}/audio/attempt-0/{ASSET}.wav"
STAGED_URI = f"gs://{BUCKET}/{OBJECT}"


class RecordingBlob:
    def __init__(self, calls: list[dict]) -> None:
        self._calls = calls

    def upload_from_filename(self, filename: str, **kwargs: object) -> None:
        self._calls.append({"filename": filename, **kwargs})


class RecordingBucket:
    def __init__(self, calls: list[dict]) -> None:
        self._calls = calls

    def blob(self, name: str) -> RecordingBlob:
        return RecordingBlob(self._calls)


class RecordingStorageClient:
    """Instantiating this at all means an upload path was entered."""

    def __init__(self, calls: list[dict], **_: object) -> None:
        self._calls = calls
        calls.append({"event": "storage_client_constructed"})

    def bucket(self, name: str) -> RecordingBucket:
        return RecordingBucket(self._calls)


class FakeOperation:
    def __init__(self) -> None:
        self.operation = type("Op", (), {"name": "projects/p/locations/us/operations/123"})()


class FakeSpeechClient:
    def __init__(self, **_: object) -> None:
        pass

    def batch_recognize(self, request: object) -> FakeOperation:
        return FakeOperation()


@pytest.fixture()
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "shir-sitevisit")
    monkeypatch.setenv("DRIVE_SHARED_FOLDER_ID", "folder")
    monkeypatch.setenv("GCS_STAGING_BUCKET", BUCKET)
    monkeypatch.setenv("GCS_STAGING_PREFIX", "site-visit-staging")
    monkeypatch.setenv("RUN_ID", "20260917T060000Z")
    return Settings.from_environment(
        required=("GOOGLE_CLOUD_PROJECT", "DRIVE_SHARED_FOLDER_ID", "GCS_STAGING_BUCKET")
    )


@pytest.fixture()
def storage_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    from google.cloud import speech_v2, storage

    calls: list[dict] = []
    monkeypatch.setattr(sv_google, "runtime_credentials", lambda _settings: object())
    monkeypatch.setattr(storage, "Client", lambda **kw: RecordingStorageClient(calls, **kw))
    monkeypatch.setattr(speech_v2, "SpeechClient", FakeSpeechClient)
    return calls


def test_a_staged_uri_means_no_upload_at_all(
    settings: Settings, storage_calls: list[dict]
) -> None:
    record = sv_google.submit_transcription(
        settings, None, ASSET, 0, OBJECT, staged_wav_uri=STAGED_URI
    )

    assert storage_calls == [], "submit_transcription must not touch GCS when the WAV is staged"
    assert record.wav_gcs_uri == STAGED_URI
    assert record.operation_name == "projects/p/locations/us/operations/123"


def test_the_request_uses_exactly_the_staged_object_with_no_second_path(
    settings: Settings, storage_calls: list[dict]
) -> None:
    record = sv_google.submit_transcription(
        settings, None, ASSET, 0, OBJECT, staged_wav_uri=STAGED_URI
    )

    assert record.wav_gcs_uri == sv_google.gcs_uri(BUCKET, sv_google.wav_object_name(settings, ASSET, 0))
    assert record.output_gcs_uri.startswith(f"gs://{BUCKET}/site-visit-staging/20260917T060000Z/{ASSET}/")


def test_a_staged_uri_that_disagrees_with_the_object_name_is_rejected(
    settings: Settings, storage_calls: list[dict]
) -> None:
    with pytest.raises(ValidationError, match="does not match the computed object path"):
        sv_google.submit_transcription(
            settings, None, ASSET, 0, OBJECT, staged_wav_uri=f"gs://{BUCKET}/somewhere/else.wav"
        )
    assert storage_calls == []


def test_the_compatibility_upload_path_guards_against_overwriting(
    settings: Settings, storage_calls: list[dict], tmp_path: Path
) -> None:
    """The standalone `transcribe` command may still upload - but never blindly."""
    wav = tmp_path / f"{ASSET}.wav"
    wav.write_bytes(b"RIFF....WAVE")

    sv_google.submit_transcription(settings, wav, ASSET, 0, OBJECT)

    uploads = [call for call in storage_calls if "filename" in call]
    assert len(uploads) == 1, "the fallback path uploads exactly once"
    assert uploads[0]["if_generation_match"] == 0
    assert uploads[0]["content_type"] == "audio/wav"


def test_a_missing_local_wav_is_still_caught_when_nothing_is_staged(
    settings: Settings, storage_calls: list[dict], tmp_path: Path
) -> None:
    with pytest.raises(ValidationError, match="WAV input does not exist"):
        sv_google.submit_transcription(settings, tmp_path / "absent.wav", ASSET, 0, OBJECT)
    with pytest.raises(ValidationError, match="WAV input does not exist"):
        sv_google.submit_transcription(settings, None, ASSET, 0, OBJECT)
    assert storage_calls == []


def test_the_object_name_contract_is_unchanged(settings: Settings, storage_calls: list[dict]) -> None:
    with pytest.raises(ValidationError, match="clearly named .wav path"):
        sv_google.submit_transcription(
            settings, None, ASSET, 0, "site-visit-staging/run/asset/audio.mp3",
            staged_wav_uri=STAGED_URI,
        )
    with pytest.raises(ValidationError, match="attempts 0 and 1"):
        sv_google.submit_transcription(settings, None, ASSET, 2, OBJECT, staged_wav_uri=STAGED_URI)
    assert storage_calls == []


def test_each_attempt_targets_a_distinct_object_so_nothing_is_ever_overwritten(
    settings: Settings,
) -> None:
    first = sv_google.wav_object_name(settings, ASSET, 0)
    retry = sv_google.wav_object_name(settings, ASSET, 1)

    assert first != retry
    assert "attempt-0" in first and "attempt-1" in retry
    assert sv_google.speech_output_prefix(settings, ASSET, 0) != sv_google.speech_output_prefix(
        settings, ASSET, 1
    )
