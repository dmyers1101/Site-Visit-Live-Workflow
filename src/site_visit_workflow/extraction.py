"""Vertex AI L1 -> L2 -> L3 extraction over the versioned prompt files.

Boundary: this module is the ONLY place that calls a model. It reads its
instruction text from `prompts/*.md` at RUNTIME - the prompt files are the
versioned source of truth and are never inlined here, so a governed prompt
edit takes effect without a code change. It writes nothing to Drive, GCS, or
Sheets; it returns records that the CLI stores.

Layer gating is strict and one-directional:

* L1 runs only on a completed, non-empty transcript. An empty or near-empty
  transcript never reaches L1 - it goes straight to NEEDS_REVIEW, because the
  pilot dropped empties upstream and this path is otherwise unvalidated.
* L2 runs only on a validated L1 result.
* L3 runs only on a validated L2 result whose `enrichment_status` is ENRICHED.

Each layer preserves `source_asset_identifier` unchanged, and each downstream
layer must echo the prior layer's record ID. L3 never overwrites an L1 or L2
value: disagreement is reported in `disputed_prior_fields` only.

Known live gap (recorded, not silently fixed): the eight-value `trade`
vocabulary has real holes - pest control, painting, drywall, restoration. The
interim rule is nearest allowed value plus an explanation in
`enrichment_note`. Widening the list needs an ADR, a catalog migration, and
new negative tests.

How to update this later
------------------------
The schema lives in two places on purpose: the prompt file's `## Output
schema` block and the `*_RESPONSE_SCHEMA` constants here. `assert_prompt_schema_matches`
compares them on every run and fails loudly on drift, so update the prompt
file, the constant, the validator in `models.py`, and the tests in one
reviewed commit. Never add a lenient parser that strips code fences or
tolerates extra keys - both are recorded pilot failure modes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import ExternalServiceError, ValidationError
from .models import (
    L1_FIELDS,
    L2_FIELDS,
    L3_FIELDS,
    L1Extraction,
    L2Enrichment,
    L3Refinement,
    l3_is_permitted,
    parse_strict_json,
    utc_now,
)

PROMPT_FILES = {
    "L1": "l1-extraction.md",
    "L2": "l2-enrichment.md",
    "L3": "l3-refinement.md",
}
LAYER_FIELDS = {"L1": L1_FIELDS, "L2": L2_FIELDS, "L3": L3_FIELDS}

# Minimum characters of transcript before L1 is allowed to run at all.
MIN_TRANSCRIPT_CHARACTERS = 2

_VERSION_PATTERN = re.compile(r"\*\*Semantic version:\*\*\s*(\S+)")
_SECTION_PATTERN = "## {heading}\n\n```{language}\n"


def _string(nullable: bool = False, enum: tuple[str, ...] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "STRING"}
    if nullable:
        schema["nullable"] = True
    if enum:
        schema["enum"] = list(enum)
    return schema


# Conditional fields carry no `enum` in the wire schema on purpose: a nullable
# enum is inconsistently supported, and the validator in models.py is the hard
# gate for every vocabulary anyway.
L1_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "source_asset_identifier": _string(),
        # "string or null" per the L1 boundary: a location-less clip is a real
        # outcome, and null is preferred over an invented location.
        "location": _string(nullable=True),
        "issue_description": _string(nullable=True),
        "suggested_filename": _string(),
        "confidence_note": _string(),
    },
    "required": [
        "source_asset_identifier",
        "location",
        "issue_description",
        "suggested_filename",
        "confidence_note",
    ],
}

L2_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "source_asset_identifier": _string(),
        "prior_layer": _string(enum=("L1",)),
        "prior_layer_record_id": _string(),
        "enrichment_status": _string(enum=("ENRICHED", "NO_FINDING", "INSUFFICIENT_EVIDENCE")),
        "trade": _string(nullable=True),
        "area_type": _string(nullable=True),
        # Severity is the INTEGER 1-4 scale, typed as an integer on the wire so
        # the model cannot return "2" and have it look plausible.
        "severity": {"type": "INTEGER", "nullable": True},
        "recommended_action": _string(nullable=True),
        "enrichment_note": _string(),
    },
    "required": sorted(L2_FIELDS),
}

L3_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "source_asset_identifier": _string(),
        "prior_layer": _string(enum=("L2",)),
        "prior_layer_record_id": _string(),
        "refinement_status": _string(enum=("REFINED", "INSUFFICIENT_EVIDENCE")),
        "responsible_party": _string(nullable=True),
        "urgency_window": _string(nullable=True),
        "disputed_prior_fields": {"type": "ARRAY", "items": {"type": "STRING"}},
        "refinement_note": _string(),
    },
    "required": sorted(L3_FIELDS),
}

RESPONSE_SCHEMAS = {
    "L1": L1_RESPONSE_SCHEMA,
    "L2": L2_RESPONSE_SCHEMA,
    "L3": L3_RESPONSE_SCHEMA,
}


@dataclass(frozen=True)
class PromptFile:
    """One governed prompt file, as read from disk for this run."""

    layer: str
    path: str
    version: str
    instruction_text: str
    declared_schema_keys: tuple[str, ...]
    sha256: str

    def evidence(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "prompt_file": self.path,
            "prompt_version": self.version,
            "prompt_sha256": self.sha256,
            "declared_schema_keys": list(self.declared_schema_keys),
        }


def _fenced_block(text: str, heading: str, language: str) -> str | None:
    marker = _SECTION_PATTERN.format(heading=heading, language=language)
    start = text.find(marker)
    if start < 0:
        return None
    body_start = start + len(marker)
    end = text.find("\n```", body_start)
    if end < 0:
        return None
    return text[body_start:end]


def load_prompt_file(layer: str, prompts_dir: Path) -> PromptFile:
    """Read one governed prompt file at runtime; a missing file is a hard stop."""
    if layer not in PROMPT_FILES:
        raise ValidationError(f"Unknown extraction layer: {layer}")
    path = Path(prompts_dir) / PROMPT_FILES[layer]
    if not path.is_file():
        raise ValidationError(
            f"{layer} prompt file is missing at runtime: {path}. "
            "The versioned prompt file is required before any model call."
        )
    text = path.read_text(encoding="utf-8")
    version_match = _VERSION_PATTERN.search(text)
    if not version_match:
        raise ValidationError(f"{layer} prompt file does not declare a **Semantic version:**.")
    instruction = _fenced_block(text, "Exact prompt text", "text")
    if not instruction or not instruction.strip():
        raise ValidationError(f"{layer} prompt file has no `## Exact prompt text` block.")
    schema_block = _fenced_block(text, "Output schema", "json")
    if not schema_block:
        raise ValidationError(f"{layer} prompt file has no `## Output schema` block.")
    try:
        declared = json.loads(schema_block)
    except ValueError as error:
        raise ValidationError(f"{layer} prompt file output schema is not valid JSON.") from error
    if not isinstance(declared, dict):
        raise ValidationError(f"{layer} prompt file output schema must be a JSON object.")
    return PromptFile(
        layer=layer,
        path=str(path),
        version=version_match.group(1),
        instruction_text=instruction.strip(),
        declared_schema_keys=tuple(sorted(declared)),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def assert_prompt_schema_matches(prompt: PromptFile) -> None:
    """Fail loudly when a prompt file and this module's validator have drifted apart."""
    expected = LAYER_FIELDS[prompt.layer]
    if set(prompt.declared_schema_keys) != set(expected):
        raise ValidationError(
            f"{prompt.layer} prompt file schema keys have drifted from the validator. "
            f"Prompt file declares: {', '.join(prompt.declared_schema_keys)}. "
            f"Validator expects: {', '.join(sorted(expected))}."
        )


def transcript_is_processable(transcript: str) -> bool:
    """An empty or near-empty transcript never reaches L1; it becomes NEEDS_REVIEW."""
    return bool(transcript) and len(transcript.strip()) >= MIN_TRANSCRIPT_CHARACTERS


@dataclass(frozen=True)
class LayerResult:
    """The complete, auditable record of one layer call."""

    layer: str
    source_asset_identifier: str
    record_id: str
    prompt_file: str
    prompt_version: str
    prompt_sha256: str
    model_id: str
    sdk_version: str
    request_payload: dict[str, Any]
    raw_response: str
    parsed_output: dict[str, Any]
    validated: bool
    started_at: str
    completed_at: str
    error: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def _sdk_version() -> str:
    try:
        from importlib.metadata import version

        return version("google-genai")
    except Exception:  # noqa: BLE001 - the version is evidence, never a blocker
        return "UNKNOWN"


def build_client(settings: Settings) -> Any:
    """One Vertex-backed google-genai client on ambient ADC. No key file, ever."""
    try:
        from google import genai
    except ImportError as error:
        raise ExternalServiceError("google-genai is not installed.") from error
    try:
        return genai.Client(
            vertexai=True, project=settings.project_id, location=settings.vertex_location
        )
    except Exception as error:  # noqa: BLE001 - surfaced as a workflow error
        raise ExternalServiceError(f"Vertex client construction failed: {error}") from error


def _generate(client: Any, settings: Settings, layer: str, prompt_text: str) -> tuple[str, dict[str, Any]]:
    try:
        from google.genai import types
    except ImportError as error:
        raise ExternalServiceError("google-genai is not installed.") from error
    try:
        response = client.models.generate_content(
            model=settings.vertex_model,
            contents=prompt_text,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMAS[layer],
            ),
        )
    except Exception as error:  # noqa: BLE001 - one boundary, one error type
        raise ExternalServiceError(f"{layer} Vertex request failed: {error}") from error
    usage: dict[str, Any] = {}
    metadata = getattr(response, "usage_metadata", None)
    if metadata is not None:
        for name in ("prompt_token_count", "candidates_token_count", "total_token_count"):
            usage[name] = getattr(metadata, name, None)
    return (response.text or ""), usage


def _compose(prompt: PromptFile, payload: dict[str, Any]) -> str:
    """The governed instruction text, then the input document. Nothing else."""
    return prompt.instruction_text + "\n\nINPUT:\n" + json.dumps(payload, sort_keys=True)


def _record_id(layer: str, asset_id: str, started_at: str) -> str:
    digest = hashlib.sha256(f"{layer}|{asset_id}|{started_at}".encode("utf-8")).hexdigest()[:16]
    return f"{layer}-{asset_id}-{digest}"


def run_l1(
    client: Any,
    settings: Settings,
    prompts_dir: Path,
    asset_id: str,
    original_drive_name: str,
    transcript: str,
) -> tuple[LayerResult, L1Extraction]:
    """Gate 4 step 2: extract the factual L1 record from a non-empty transcript."""
    if not transcript_is_processable(transcript):
        raise ValidationError(
            "Refusing to run L1 on an empty or near-empty transcript; the asset is NEEDS_REVIEW."
        )
    prompt = load_prompt_file("L1", prompts_dir)
    assert_prompt_schema_matches(prompt)
    payload = {
        "source_asset_identifier": asset_id,
        "original_drive_name": original_drive_name,
        "transcript_text": transcript,
    }
    started_at = utc_now()
    raw, usage = _generate(client, settings, "L1", _compose(prompt, payload))
    parsed = parse_strict_json(raw, "L1")
    extraction = L1Extraction.from_external_result(parsed, asset_id)
    from dataclasses import asdict

    return (
        LayerResult(
            layer="L1",
            source_asset_identifier=asset_id,
            record_id=_record_id("L1", asset_id, started_at),
            prompt_file=prompt.path,
            prompt_version=prompt.version,
            prompt_sha256=prompt.sha256,
            model_id=settings.vertex_model,
            sdk_version=_sdk_version(),
            request_payload=payload,
            raw_response=raw,
            parsed_output=asdict(extraction),
            validated=True,
            started_at=started_at,
            completed_at=utc_now(),
            usage=usage,
        ),
        extraction,
    )


def run_l2(
    client: Any,
    settings: Settings,
    prompts_dir: Path,
    asset_id: str,
    l1_result: LayerResult,
    l1: L1Extraction,
    transcript: str,
) -> tuple[LayerResult, L2Enrichment]:
    """Gate 4 step 3: enrich a VALIDATED L1 record only."""
    if not l1_result.validated or l1_result.layer != "L1":
        raise ValidationError("L2 requires a validated L1 record.")
    prompt = load_prompt_file("L2", prompts_dir)
    assert_prompt_schema_matches(prompt)
    from dataclasses import asdict

    payload = {
        "source_asset_identifier": asset_id,
        "l1_record_id": l1_result.record_id,
        "l1": asdict(l1),
        "transcript_text": transcript,
    }
    started_at = utc_now()
    raw, usage = _generate(client, settings, "L2", _compose(prompt, payload))
    parsed = parse_strict_json(raw, "L2")
    enrichment = L2Enrichment.from_external_result(
        parsed,
        asset_id,
        l1_result.record_id,
        evidence_supports_finding=transcript_is_processable(transcript)
        and bool((l1.issue_description or "").strip()),
    )
    return (
        LayerResult(
            layer="L2",
            source_asset_identifier=asset_id,
            record_id=_record_id("L2", asset_id, started_at),
            prompt_file=prompt.path,
            prompt_version=prompt.version,
            prompt_sha256=prompt.sha256,
            model_id=settings.vertex_model,
            sdk_version=_sdk_version(),
            request_payload=payload,
            raw_response=raw,
            parsed_output=asdict(enrichment),
            validated=True,
            started_at=started_at,
            completed_at=utc_now(),
            usage=usage,
        ),
        enrichment,
    )


def run_l3(
    client: Any,
    settings: Settings,
    prompts_dir: Path,
    asset_id: str,
    l2_result: LayerResult,
    l2: L2Enrichment,
    l1: L1Extraction,
    transcript: str,
) -> tuple[LayerResult, L3Refinement]:
    """Gate 4 step 4: refine a VALIDATED, ENRICHED L2 record only."""
    if not l2_result.validated or l2_result.layer != "L2":
        raise ValidationError("L3 requires a validated L2 record.")
    if not l3_is_permitted(l2):
        raise ValidationError(
            "L3 runs only on an ENRICHED L2 record; NO_FINDING and INSUFFICIENT_EVIDENCE stop here."
        )
    prompt = load_prompt_file("L3", prompts_dir)
    assert_prompt_schema_matches(prompt)
    from dataclasses import asdict

    payload = {
        "source_asset_identifier": asset_id,
        "l2_record_id": l2_result.record_id,
        "l2": asdict(l2),
        "l1": {
            "location": l1.location,
            "issue_description": l1.issue_description,
            "suggested_filename": l1.suggested_filename,
            "confidence_note": l1.confidence_note,
        },
        "transcript_text": transcript,
    }
    started_at = utc_now()
    raw, usage = _generate(client, settings, "L3", _compose(prompt, payload))
    parsed = parse_strict_json(raw, "L3")
    refinement = L3Refinement.from_external_result(parsed, asset_id, l2_result.record_id)
    return (
        LayerResult(
            layer="L3",
            source_asset_identifier=asset_id,
            record_id=_record_id("L3", asset_id, started_at),
            prompt_file=prompt.path,
            prompt_version=prompt.version,
            prompt_sha256=prompt.sha256,
            model_id=settings.vertex_model,
            sdk_version=_sdk_version(),
            request_payload=payload,
            raw_response=raw,
            parsed_output=asdict(refinement),
            validated=True,
            started_at=started_at,
            completed_at=utc_now(),
            usage=usage,
        ),
        refinement,
    )
