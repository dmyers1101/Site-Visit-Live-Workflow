"""Re-run L2 (and L3) for catalogued clips after an L2 prompt change (2026-10-08).

Boundary: transcripts and L1 are NEVER re-run or changed. For each row the
command reads the stored transcript and the stored, validated L1 record from
the run's GCS evidence, runs the CURRENT L2 prompt (then L3 when L2 is
ENRICHED), and rebuilds the row through `catalog.build_catalog_row` so the
column mapping has one implementation.

Invariants (pipeline-verify), checked before ANY write:
- only `REPROCESS_COLUMNS` may differ between the old and new row;
- the set of row keys written equals the set selected (no new rows);
- a row without a COMPLETED transcript or a VALIDATED L1 is skipped, never guessed.
All rows are recomputed in memory first; nothing is written if any check fails.
"""

from __future__ import annotations

from typing import Any

from .catalog import build_catalog_row
from .errors import ValidationError
from .models import DriveMediaFile

L2_L3_COLUMNS = (
    "l2_status", "l2_trade", "l2_area_type", "l2_severity", "l2_recommended_action",
    "l2_enrichment_note", "l3_status", "l3_responsible_party", "l3_urgency_window",
    "l3_disputed_prior_fields", "l3_refinement_note",
)
REPROCESS_COLUMNS = frozenset(L2_L3_COLUMNS + ("asset_status", "updated_at"))


def eligible(row: dict[str, Any]) -> tuple[bool, str]:
    """Only rows whose transcript completed and whose L1 validated are re-run."""
    if str(row.get("transcription_status") or "") != "COMPLETED":
        return False, "transcript not COMPLETED"
    if str(row.get("l1_status") or "") != "VALIDATED":
        return False, "L1 not VALIDATED"
    if not str(row.get("transcript_gcs_uri") or "").startswith("gs://"):
        return False, "no transcript_gcs_uri"
    if not str(row.get("evidence_gcs_prefix") or "").startswith("gs://"):
        return False, "no evidence_gcs_prefix"
    return True, ""


def object_name(uri: str, bucket: str) -> str:
    prefix = f"gs://{bucket}/"
    if not uri.startswith(prefix):
        raise ValidationError(f"{uri} is not in bucket {bucket}.")
    return uri[len(prefix):]


def rebuild_row(row: dict[str, Any], l1: Any, l2: Any, l3: Any, layer_errors: dict[str, Any],
                updated_at: str) -> dict[str, Any]:
    """The row as Gate 5 would build it with the new L2/L3; everything else carried over."""
    asset = DriveMediaFile(drive_id=str(row["row_key"]), original_name=str(row["original_drive_name"]),
                           mime_type="video/quicktime", web_view_link=row.get("drive_link") or None)
    transcription = {
        "status": row.get("transcription_status"), "wav_gcs_uri": row.get("wav_gcs_uri"),
        "output_gcs_uri": row.get("transcript_output_gcs_uri"),
        "started_at": row.get("transcription_started_at"),
        "completed_at": row.get("transcription_completed_at"),
        "transcript_gcs_uri": row.get("transcript_gcs_uri"),
    }
    from .catalog import PORTFOLIO_COLUMNS, WORK_ORDER_COLUMNS

    new = build_catalog_row(
        asset=asset, visit_drive_id=str(row.get("visit_drive_id") or ""), run_id=str(row.get("run_id") or ""),
        asset_status="NEEDS_REVIEW" if layer_errors else "CATALOGUED",
        transcription=transcription, updated_at=updated_at,
        evidence_gcs_prefix=str(row.get("evidence_gcs_prefix") or ""),
        l1=l1, l2=l2, l3=l3,
        drive_rename_decision=row.get("drive_rename_decision") or None,
        extras={name: row.get(name) for name in PORTFOLIO_COLUMNS},
        work_order={name: row.get(name) for name in WORK_ORDER_COLUMNS},
    )
    # Preserve the stored catalog_status / schema version exactly as they were.
    for name in ("catalog_status", "catalog_schema_version"):
        if row.get(name) not in (None, ""):
            new[name] = row[name]
    return new


def _cell(value: Any) -> str:
    return "" if value is None else str(value).strip()


def changed_columns(old: dict[str, Any], new: dict[str, Any]) -> set[str]:
    return {name for name in new if _cell(old.get(name)) != _cell(new.get(name))}


def assert_only_layer_columns_changed(old: dict[str, Any], new: dict[str, Any]) -> set[str]:
    changed = changed_columns(old, new)
    illegal = changed - REPROCESS_COLUMNS
    if illegal:
        detail = {n: (_cell(old.get(n)), _cell(new.get(n))) for n in sorted(illegal)}
        raise ValidationError(f"Reprocess would change non-L2/L3 columns for {old.get('row_key')}: {detail}")
    return changed
