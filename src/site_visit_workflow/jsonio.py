from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, TypeVar

from .errors import ValidationError
from .models import (
    DriveMediaFile,
    ReviewAction,
    ReviewApproval,
    TranscriptStatus,
    TranscriptionRecord,
    VisitFolder,
    VisitManifest,
)

T = TypeVar("T")


def read_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError as error:
        raise ValidationError(f"Input file does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise ValidationError(f"Invalid JSON in {path}: {error.msg}") from error


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(value) if is_dataclass(value) else value
    with path.open("x", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, sort_keys=True)
        file.write("\n")


def _media(data: dict[str, Any]) -> DriveMediaFile:
    return DriveMediaFile(**data)


def manifest_from_dict(data: dict[str, Any]) -> VisitManifest:
    try:
        return VisitManifest(
            schema_version=data["schema_version"],
            shared_folder_id=data["shared_folder_id"],
            visit=VisitFolder(**data["visit"]),
            media_files=tuple(_media(item) for item in data["media_files"]),
            created_at=data["created_at"],
        )
    except (KeyError, TypeError) as error:
        raise ValidationError("Invalid manifest JSON shape.") from error


def transcription_from_dict(data: dict[str, Any]) -> TranscriptionRecord:
    try:
        data = dict(data)
        data["status"] = TranscriptStatus(data["status"])
        return TranscriptionRecord(**data)
    except (KeyError, TypeError, ValueError) as error:
        raise ValidationError("Invalid transcription record JSON shape.") from error


def approval_from_dict(data: dict[str, Any]) -> ReviewApproval:
    try:
        data = dict(data)
        data["action"] = ReviewAction(data["action"])
        return ReviewApproval(**data)
    except (KeyError, TypeError, ValueError) as error:
        raise ValidationError("Invalid approval JSON shape.") from error
