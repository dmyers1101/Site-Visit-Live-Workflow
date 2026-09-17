"""ffprobe/ffmpeg media preparation inside the container.

Boundary: every function here reads a staged copy and writes a NEW file. The
Drive source is never touched, and an existing WAV is never overwritten - a
collision is a hard stop, not a silent replacement.

How to update this later
------------------------
Chirp is fed mono 16 kHz PCM s16le; `WAV_CHANNELS`, `WAV_SAMPLE_RATE`, and
`WAV_CODEC` are the single source of that contract and `verify_wav` asserts
the produced file actually matches. Changing the audio contract means changing
those constants, the ffmpeg arguments, and the transcription runbook together.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .errors import ExternalServiceError, ValidationError

WAV_CHANNELS = 1
WAV_SAMPLE_RATE = 16000
WAV_CODEC = "pcm_s16le"


def prepare_wav(video_path: Path, wav_path: Path) -> dict[str, Any]:
    """Probe a staged source and extract a mono, 16 kHz WAV without changing the source."""
    if not video_path.is_file():
        raise ValidationError(f"Staged video does not exist: {video_path}")
    if wav_path.exists():
        raise ValidationError(f"Refusing to overwrite WAV: {wav_path}")
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(video_path)],
            capture_output=True,
            check=True,
            text=True,
        )
        probe_data = json.loads(probe.stdout)
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", str(wav_path),
            ],
            capture_output=True,
            check=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise ExternalServiceError("ffprobe and ffmpeg must be available on PATH.") from error
    except subprocess.CalledProcessError as error:
        raise ExternalServiceError(f"Media preparation failed: {error.stderr.strip()}") from error
    except json.JSONDecodeError as error:
        raise ExternalServiceError("ffprobe produced invalid JSON.") from error
    if not wav_path.is_file() or wav_path.stat().st_size == 0:
        raise ExternalServiceError("ffmpeg completed without a non-empty WAV output.")
    return probe_data


def probe(path: Path) -> dict[str, Any]:
    """Read-only ffprobe metadata capture for one staged file."""
    if not path.is_file():
        raise ValidationError(f"Cannot probe a file that does not exist: {path}")
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True,
            check=True,
            text=True,
        )
        return json.loads(result.stdout)
    except FileNotFoundError as error:
        raise ExternalServiceError("ffprobe must be available on PATH.") from error
    except subprocess.CalledProcessError as error:
        raise ExternalServiceError(f"ffprobe failed for {path}: {error.stderr.strip()}") from error
    except json.JSONDecodeError as error:
        raise ExternalServiceError("ffprobe produced invalid JSON.") from error


def probe_summary(probe_data: dict[str, Any]) -> dict[str, Any]:
    """Reduce a raw ffprobe document to the few facts the evidence record needs."""
    streams = probe_data.get("streams") or []
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    fmt = probe_data.get("format") or {}
    return {
        "duration_seconds": fmt.get("duration"),
        "format_name": fmt.get("format_name"),
        "size_bytes": fmt.get("size"),
        "stream_count": len(streams),
        "has_audio_stream": bool(audio),
        "audio_codec": audio.get("codec_name"),
        "audio_channels": audio.get("channels"),
        "audio_sample_rate": audio.get("sample_rate"),
        "video_codec": video.get("codec_name") or None,
        "video_width": video.get("width"),
        "video_height": video.get("height"),
    }


def verify_wav(wav_path: Path) -> dict[str, Any]:
    """Confirm the produced WAV really is mono 16 kHz PCM s16le before Chirp sees it."""
    summary = probe_summary(probe(wav_path))
    problems: list[str] = []
    if summary.get("audio_codec") != WAV_CODEC:
        problems.append(f"codec is {summary.get('audio_codec')}, expected {WAV_CODEC}")
    if summary.get("audio_channels") != WAV_CHANNELS:
        problems.append(f"channels is {summary.get('audio_channels')}, expected {WAV_CHANNELS}")
    if str(summary.get("audio_sample_rate")) != str(WAV_SAMPLE_RATE):
        problems.append(
            f"sample rate is {summary.get('audio_sample_rate')}, expected {WAV_SAMPLE_RATE}"
        )
    if problems:
        raise ExternalServiceError(
            "Prepared WAV does not meet the Chirp audio contract: " + "; ".join(problems)
        )
    return summary


def file_sha256(path: Path) -> str:
    """Checksum a staged artifact so the evidence record can prove what was sent."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_for_transcription(video_path: Path, wav_path: Path) -> dict[str, Any]:
    """Gate 2 for one asset: probe the source, extract the WAV, verify and checksum it.

    `prepare_wav` keeps its existing no-overwrite behavior; this wrapper adds
    the evidence capture the trial record requires.
    """
    source_probe = prepare_wav(video_path, wav_path)
    return {
        "source_path": str(video_path),
        "source_probe": source_probe,
        "source_summary": probe_summary(source_probe),
        "source_sha256": file_sha256(video_path),
        "wav_path": str(wav_path),
        "wav_summary": verify_wav(wav_path),
        "wav_sha256": file_sha256(wav_path),
        "wav_size_bytes": wav_path.stat().st_size,
        "audio_contract": {
            "channels": WAV_CHANNELS,
            "sample_rate": WAV_SAMPLE_RATE,
            "codec": WAV_CODEC,
        },
    }
