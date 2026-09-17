"""Pure Gate 5 logic: build one catalog row per asset, keyed by the Drive ID.

Boundary: nothing here contacts Sheets. It turns the records a run already
produced into an ordered row; `google.upsert_catalog_row` does the writing.
The row key is always the immutable Drive asset ID, which is what makes a
re-run update the same row instead of appending a duplicate.

The row is deliberately wider than `CatalogDraft`: Gate 5 requires the L1, L2
and L3 outputs, the transcript reference, and the run ID in the sheet, and
`CatalogDraft` is a frozen 15-field contract that other commands still use.
`FULL_CATALOG_HEADERS` starts with exactly the `CatalogDraft` headers so the
two stay readable side by side.

How to update this later
------------------------
Adding a column means appending to `FULL_CATALOG_HEADERS` (never inserting in
the middle, and never removing one - existing sheets already have the old
order), extending `build_catalog_row`, and adding a width test. A column
removal is a catalog migration and needs an ADR.
"""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .models import DriveMediaFile, L1Extraction, L2Enrichment, L3Refinement

CATALOG_SCHEMA_VERSION = "2.0"

FULL_CATALOG_HEADERS: tuple[str, ...] = (
    "row_key",
    "source_asset_identifier",
    "original_drive_name",
    "drive_link",
    "visit_drive_id",
    "location",
    "issue_description",
    "suggested_filename",
    "confidence_note",
    "transcription_status",
    "wav_gcs_uri",
    "transcript_output_gcs_uri",
    "transcription_started_at",
    "transcription_completed_at",
    "catalog_status",
    "catalog_schema_version",
    "run_id",
    "asset_status",
    "l1_status",
    "l2_status",
    "l2_trade",
    "l2_area_type",
    "l2_severity",
    "l2_recommended_action",
    "l2_enrichment_note",
    "l3_status",
    "l3_responsible_party",
    "l3_urgency_window",
    "l3_disputed_prior_fields",
    "l3_refinement_note",
    "transcript_gcs_uri",
    "evidence_gcs_prefix",
    "drive_rename_decision",
    "updated_at",
)

# Every suggested name is a proposal. This workflow never renames Drive media.
RENAME_DECISION = "PROPOSED_ONLY_AWAITING_HUMAN_APPROVAL"


def _blank(value: Any) -> Any:
    return "" if value is None else value


def build_catalog_row(
    asset: DriveMediaFile,
    visit_drive_id: str,
    run_id: str,
    asset_status: str,
    transcription: dict[str, Any],
    updated_at: str,
    evidence_gcs_prefix: str,
    l1: L1Extraction | None = None,
    l2: L2Enrichment | None = None,
    l3: L3Refinement | None = None,
) -> dict[str, Any]:
    """Build the full, ordered catalog record for one asset.

    Layers that did not run are recorded as NOT_RUN with blank values - never
    as an invented finding. A NEEDS_REVIEW transcript therefore produces a real
    row with no extraction content, which is the honest outcome.
    """
    if not asset.drive_id.strip():
        raise ValidationError("A catalog row requires the immutable Drive asset ID.")
    for layer, record in (("L1", l1), ("L2", l2), ("L3", l3)):
        if record is not None and record.source_asset_identifier != asset.drive_id:
            raise ValidationError(f"{layer} record does not belong to the selected source asset.")
    if l2 is not None and l1 is None:
        raise ValidationError("An L2 record cannot be catalogued without its validated L1 record.")
    if l3 is not None and l2 is None:
        raise ValidationError("An L3 record cannot be catalogued without its validated L2 record.")

    row = {
        "row_key": asset.drive_id,
        "source_asset_identifier": asset.drive_id,
        "original_drive_name": asset.original_name,
        "drive_link": _blank(asset.web_view_link),
        "visit_drive_id": visit_drive_id,
        "location": _blank(l1.location if l1 else None),
        "issue_description": _blank(l1.issue_description if l1 else None),
        "suggested_filename": _blank(l1.suggested_filename if l1 else None),
        "confidence_note": _blank(l1.confidence_note if l1 else None),
        "transcription_status": _blank(transcription.get("status")),
        "wav_gcs_uri": _blank(transcription.get("wav_gcs_uri")),
        "transcript_output_gcs_uri": _blank(transcription.get("output_gcs_uri")),
        "transcription_started_at": _blank(transcription.get("started_at")),
        "transcription_completed_at": _blank(transcription.get("completed_at")),
        "catalog_status": "DRAFT",
        "catalog_schema_version": CATALOG_SCHEMA_VERSION,
        "run_id": run_id,
        "asset_status": asset_status,
        "l1_status": "VALIDATED" if l1 else "NOT_RUN",
        "l2_status": l2.enrichment_status if l2 else "NOT_RUN",
        "l2_trade": _blank(l2.trade if l2 else None),
        "l2_area_type": _blank(l2.area_type if l2 else None),
        "l2_severity": _blank(l2.severity if l2 else None),
        "l2_recommended_action": _blank(l2.recommended_action if l2 else None),
        "l2_enrichment_note": _blank(l2.enrichment_note if l2 else None),
        "l3_status": l3.refinement_status if l3 else "NOT_RUN",
        "l3_responsible_party": _blank(l3.responsible_party if l3 else None),
        "l3_urgency_window": _blank(l3.urgency_window if l3 else None),
        "l3_disputed_prior_fields": ", ".join(l3.disputed_prior_fields) if l3 else "",
        "l3_refinement_note": _blank(l3.refinement_note if l3 else None),
        "transcript_gcs_uri": _blank(transcription.get("transcript_gcs_uri")),
        "evidence_gcs_prefix": evidence_gcs_prefix,
        "drive_rename_decision": RENAME_DECISION,
        "updated_at": updated_at,
    }
    if tuple(row) != FULL_CATALOG_HEADERS:
        raise ValidationError("Catalog row keys drifted from FULL_CATALOG_HEADERS.")
    return row


def row_values(row: dict[str, Any]) -> list[Any]:
    """Flatten a catalog row into the header-ordered value list Sheets receives."""
    missing = [name for name in FULL_CATALOG_HEADERS if name not in row]
    if missing:
        raise ValidationError("Catalog row is missing columns: " + ", ".join(missing))
    return [row[name] for name in FULL_CATALOG_HEADERS]
