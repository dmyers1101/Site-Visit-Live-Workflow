from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .errors import ExternalServiceError, ValidationError


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
