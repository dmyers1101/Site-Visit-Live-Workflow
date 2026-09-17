from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from .config import Settings, gcs_uri
from .errors import ExternalServiceError, ValidationError, WorkflowError
from .google import (
    DriveGateway,
    StorageGateway,
    asset_prefix,
    await_transcription,
    ensure_sheet_tab,
    read_batch_transcript,
    run_prefix,
    runtime_credentials,
    sheets_service,
    speech_output_prefix,
    submit_transcription,
    upsert_catalog_row,
    wav_object_name,
)
from .jsonio import approval_from_dict, manifest_from_dict, read_json, transcription_from_dict, write_json
from .media import prepare_wav
from .models import (
    CatalogDraft,
    DriveMediaFile,
    L1Extraction,
    ReviewAction,
    TranscriptStatus,
    TranscriptionRecord,
    utc_now,
    VisitManifest,
    evaluate_transcript,
    require_approval,
)


def _path(value: str) -> Path:
    return Path(value)


def _read_manifest(path: Path) -> VisitManifest:
    return manifest_from_dict(read_json(path))


def _load_l1(path: Path, asset_id: str) -> L1Extraction:
    return L1Extraction.from_external_result(read_json(path), asset_id)


def cmd_config_check(_: argparse.Namespace) -> None:
    settings = Settings.from_environment()
    print(
        json.dumps(
            {
                "project_id": settings.project_id,
                "environment": settings.environment,
                "runtime_service_account": settings.runtime_service_account,
                "drive_shared_folder_id_configured": bool(settings.drive_shared_folder_id),
                "credentials": "not contacted",
            },
            indent=2,
        )
    )


def cmd_list_visits(_: argparse.Namespace) -> None:
    settings = Settings.from_environment(
        required=("GOOGLE_CLOUD_PROJECT", "DRIVE_SHARED_FOLDER_ID")
    )
    visits = DriveGateway.from_settings(settings).list_visit_folders()
    print(
        json.dumps(
            [
                {
                    "drive_id": visit.drive_id,
                    "name": visit.name,
                    "web_view_link": visit.web_view_link,
                }
                for visit in visits
            ],
            indent=2,
        )
    )


def cmd_auth_preflight(_: argparse.Namespace) -> None:
    """Read-only: report every authorization prerequisite as one JSON record."""
    from .preflight import emit

    emit(Settings.from_environment(required=("GOOGLE_CLOUD_PROJECT", "DRIVE_SHARED_FOLDER_ID")))


def cmd_list_folder_children(_: argparse.Namespace) -> None:
    """Read-only: list every immediate child of the configured Drive folder."""
    settings = Settings.from_environment(
        required=("GOOGLE_CLOUD_PROJECT", "DRIVE_SHARED_FOLDER_ID")
    )
    children = DriveGateway.from_settings(settings).list_immediate_children()
    print(
        json.dumps(
            {
                "folder_id": settings.drive_shared_folder_id,
                "runtime_service_account": settings.runtime_service_account,
                "immediate_child_count": len(children),
                "immediate_children": children,
            },
            indent=2,
        )
    )


def cmd_intake(args: argparse.Namespace) -> None:
    settings = Settings.from_environment(
        required=("GOOGLE_CLOUD_PROJECT", "DRIVE_SHARED_FOLDER_ID")
    )
    drive = DriveGateway.from_settings(settings)
    visits = {visit.drive_id: visit for visit in drive.list_visit_folders()}
    if args.visit_id not in visits:
        raise ValidationError("Provided visit ID is not an immediate child of the configured Shared Folder.")
    manifest = VisitManifest(
        schema_version="1.0",
        shared_folder_id=settings.drive_shared_folder_id,
        visit=visits[args.visit_id],
        media_files=tuple(drive.list_immediate_videos(args.visit_id)),
    )
    write_json(args.output, manifest)
    print(f"Created manifest for one visit: {args.output}")


def cmd_stage_video(args: argparse.Namespace) -> None:
    manifest = _read_manifest(args.manifest)
    manifest.asset(args.asset_id)
    settings = Settings.from_environment(
        required=("GOOGLE_CLOUD_PROJECT", "DRIVE_SHARED_FOLDER_ID")
    )
    DriveGateway.from_settings(settings).download(args.asset_id, args.output)
    print(f"Staged selected source asset at {args.output}")


def cmd_prepare_media(args: argparse.Namespace) -> None:
    manifest = _read_manifest(args.manifest)
    manifest.asset(args.asset_id)
    probe = prepare_wav(args.staged_video, args.wav_output)
    write_json(args.probe_output, probe)
    print(f"Wrote mono 16 kHz WAV and probe record: {args.wav_output}")


def cmd_transcribe(args: argparse.Namespace) -> None:
    manifest = _read_manifest(args.manifest)
    manifest.asset(args.asset_id)
    settings = Settings.from_environment(
        required=("GOOGLE_CLOUD_PROJECT", "GCS_STAGING_BUCKET")
    )
    try:
        record = submit_transcription(
            settings,
            args.wav,
            args.asset_id,
            args.attempt,
            args.gcs_object,
            staged_wav_uri=getattr(args, "staged_wav_uri", None),
        )
    except ExternalServiceError as error:
        failed = TranscriptionRecord(
            source_asset_identifier=args.asset_id,
            wav_gcs_uri=gcs_uri(settings.gcs_staging_bucket, args.gcs_object),
            output_gcs_uri=gcs_uri(
                settings.gcs_staging_bucket,
                f"{settings.gcs_staging_prefix}/speech-output/{args.asset_id}/attempt-{args.attempt}/",
            ),
            attempt=args.attempt,
            status=TranscriptStatus.FAILED,
            started_at=utc_now(),
            completed_at=utc_now(),
            error=str(error),
        )
        write_json(args.output, failed)
        raise
    write_json(args.output, record)
    print(f"Submitted one Chirp BatchRecognize operation: {record.operation_name}")


def cmd_evaluate_transcript(args: argparse.Namespace) -> None:
    record = transcription_from_dict(read_json(args.record))
    text = args.transcript.read_text(encoding="utf-8")
    decision = evaluate_transcript(text, record.attempt)
    if decision.value == "COMPLETE":
        updated = replace(record, status=TranscriptStatus.COMPLETED, completed_at=utc_now())
    elif decision.value == "RETRY_ONCE":
        updated = replace(record, status=TranscriptStatus.RETRY_PENDING, completed_at=utc_now())
    else:
        updated = replace(record, status=TranscriptStatus.NEEDS_REVIEW, completed_at=utc_now())
    write_json(
        args.output,
        {"decision": decision.value, "record": asdict(updated), "transcript_characters": len(text)},
    )
    print(f"Transcript decision: {decision.value}")


def cmd_create_l1_request(args: argparse.Namespace) -> None:
    manifest = _read_manifest(args.manifest)
    asset = manifest.asset(args.asset_id)
    transcript = args.transcript.read_text(encoding="utf-8")
    if not transcript.strip():
        raise ValidationError("Cannot create an L1 request from an empty transcript.")
    write_json(
        args.output,
        {
            "prompt_version": "1.0.0",
            "source_asset_identifier": asset.drive_id,
            "original_drive_name": asset.original_name,
            "transcript_text": transcript,
            "external_execution": "NOT_EXECUTED; submit only through an approved external process.",
        },
    )
    print("Created L1 prompt payload; no Vertex or Gemini request was made.")


def cmd_accept_l1_result(args: argparse.Namespace) -> None:
    manifest = _read_manifest(args.manifest)
    manifest.asset(args.asset_id)
    extraction = _load_l1(args.external_result, args.asset_id)
    write_json(args.output, extraction)
    print("Validated explicit external L1 result.")


def cmd_draft_catalog(args: argparse.Namespace) -> None:
    manifest = _read_manifest(args.manifest)
    extraction = _load_l1(args.l1_result, args.asset_id)
    record = transcription_from_dict(read_json(args.transcription_record))
    draft = CatalogDraft.from_records(manifest, args.asset_id, extraction, record)
    write_json(args.output, draft)
    print(f"Created idempotent draft catalog row with Drive ID key: {draft.row_key}")


def _approval(args: argparse.Namespace, asset_id: str, action: ReviewAction) -> None:
    approval = approval_from_dict(read_json(args.approval))
    require_approval(approval, asset_id, action)


def cmd_rename_drive(args: argparse.Namespace) -> None:
    manifest = _read_manifest(args.manifest)
    manifest.asset(args.asset_id)
    _approval(args, args.asset_id, ReviewAction.RENAME_DRIVE)
    settings = Settings.from_environment(
        required=("GOOGLE_CLOUD_PROJECT", "DRIVE_SHARED_FOLDER_ID")
    )
    DriveGateway.from_settings(settings).rename(args.asset_id, args.new_name)
    print("Renamed Drive file after explicit approval.")


CATALOG_HEADERS = (
    "row_key", "source_asset_identifier", "original_drive_name", "drive_link", "visit_drive_id",
    "location", "issue_description", "suggested_filename", "confidence_note", "transcription_status",
    "wav_gcs_uri", "transcript_output_gcs_uri", "transcription_started_at",
    "transcription_completed_at", "catalog_status",
)


def cmd_publish_catalog(args: argparse.Namespace) -> None:
    draft_data = read_json(args.draft)
    try:
        draft = CatalogDraft(**draft_data)
    except TypeError as error:
        raise ValidationError("Invalid catalog draft JSON shape.") from error
    _approval(args, draft.source_asset_identifier, ReviewAction.PUBLISH_CATALOG)
    try:
        from googleapiclient.errors import HttpError
        from googleapiclient.discovery import build
    except ImportError as error:
        raise ExternalServiceError("Google Sheets dependency is not installed.") from error
    settings = Settings.from_environment(
        required=("GOOGLE_CLOUD_PROJECT", "CATALOG_SHEET_ID")
    )
    tab_name = args.sheet_name or settings.catalog_tab_name
    service = build("sheets", "v4", credentials=runtime_credentials(settings), cache_discovery=False)
    values = [getattr(draft, header) for header in CATALOG_HEADERS]
    ensure_sheet_tab(service, settings.catalog_sheet_id, tab_name)
    outcome = upsert_catalog_row(
        service, settings.catalog_sheet_id, tab_name, CATALOG_HEADERS, values, draft.row_key
    )
    print(
        f"Published approved catalog row using idempotent key: {draft.row_key} "
        f"({outcome['outcome']} in tab {tab_name})"
    )


# ---------------------------------------------------------------------------
# process-folder: the cloud-native, end-to-end Gate 1..5 run.
#
# Boundary: media bytes flow Drive -> this container's ephemeral filesystem ->
# GCS. No operator workstation is involved at any point. The command creates
# Drive nothing, renames Drive nothing, and deletes nothing anywhere - not a
# Drive file, not a GCS object, not a Sheets row or tab. Suggested filenames
# are proposals recorded in the catalog for human review.
#
# How to update this later: each gate is one private helper below. Add a gate
# by adding a helper and one entry in the per-asset record; do not inline
# Google calls into the loop, and keep the loop sequential - conservative
# concurrency is a documented requirement, not an oversight.
# ---------------------------------------------------------------------------

ASSET_STATUS_CATALOGUED = "CATALOGUED"
ASSET_STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
ASSET_STATUS_FAILED = "FAILED"
ASSET_STATUS_DRY_RUN = "DRY_RUN"


def _sanitized(error: Exception) -> dict[str, Any]:
    """Reduce an exception to a non-secret record; one asset's failure is not fatal."""
    return {"error_type": type(error).__name__, "message": str(error)[:600]}


def _emit(record: dict[str, Any]) -> None:
    """One JSON line per step so the Cloud Run Job log is the running evidence."""
    print(json.dumps(record, default=str), flush=True)


def _gate1_manifest(settings: Settings, drive: DriveGateway) -> tuple[VisitManifest, dict[str, Any]]:
    from .discovery import build_manifest, classify_children, manifest_document

    children = drive.list_immediate_children_detailed()
    classification = classify_children(children)
    folder = drive.folder_metadata()
    manifest = build_manifest(
        shared_folder_id=settings.drive_shared_folder_id,
        folder_name=folder.get("name") or settings.drive_shared_folder_id,
        classification=classification,
        folder_web_view_link=folder.get("webViewLink"),
    )
    return manifest, manifest_document(settings.run_id, manifest, classification)


def _gate2_media(
    drive: DriveGateway, asset: DriveMediaFile, work_dir: Path
) -> tuple[Path, dict[str, Any]]:
    from .media import prepare_for_transcription

    staged_dir = work_dir / asset.drive_id
    source_path = staged_dir / f"source-{asset.drive_id}"
    wav_path = staged_dir / f"{asset.drive_id}.wav"
    drive.stage_asset(asset.drive_id, source_path)
    return wav_path, prepare_for_transcription(source_path, wav_path)


def _gate3_transcribe(
    settings: Settings,
    storage: StorageGateway,
    asset: DriveMediaFile,
    wav_path: Path,
    poll_timeout: int,
    staged_wav_uri: str,
) -> dict[str, Any]:
    """Submit one BatchRecognize per WAV, poll it, and apply the empty-transcript policy.

    An empty transcript is retried exactly once. A second empty result is
    NEEDS_REVIEW: the extraction path stops and no finding is fabricated.

    Boundary: each attempt's WAV object is written EXACTLY ONCE. Attempt 0
    reuses the object the caller already staged; the retry stages its own
    distinct attempt-1 object. `submit_transcription` is always given the
    staged URI so it never re-uploads - a re-upload is an overwrite, and the
    identity has no GCS delete permission by design.
    """
    attempts: list[dict[str, Any]] = []
    for attempt in (0, 1):
        object_name = wav_object_name(settings, asset.drive_id, attempt)
        attempt_uri = (
            staged_wav_uri
            if attempt == 0
            else storage.upload_file(wav_path, object_name, "audio/wav")
        )
        record = submit_transcription(
            settings, None, asset.drive_id, attempt, object_name, staged_wav_uri=attempt_uri
        )
        operation = await_transcription(settings, record.operation_name, timeout_seconds=poll_timeout)
        entry: dict[str, Any] = {
            "attempt": attempt,
            "operation_name": record.operation_name,
            "wav_gcs_uri": record.wav_gcs_uri,
            "output_gcs_uri": record.output_gcs_uri,
            "started_at": record.started_at,
            "completed_at": utc_now(),
            "operation": operation,
        }
        if not operation["done"] or operation["error"]:
            entry["status"] = TranscriptStatus.FAILED.value
            entry["transcript_text"] = ""
            attempts.append(entry)
            return {"attempts": attempts, "final": entry, "transcript_text": ""}
        text, sources = read_batch_transcript(
            storage, speech_output_prefix(settings, asset.drive_id, attempt)
        )
        entry["output_objects"] = sources
        entry["transcript_characters"] = len(text)
        decision = evaluate_transcript(text, attempt)
        entry["decision"] = decision.value
        if decision.value == "COMPLETE":
            entry["status"] = TranscriptStatus.COMPLETED.value
            entry["transcript_text"] = text
            attempts.append(entry)
            return {"attempts": attempts, "final": entry, "transcript_text": text}
        entry["transcript_text"] = ""
        entry["status"] = (
            TranscriptStatus.RETRY_PENDING.value
            if decision.value == "RETRY_ONCE"
            else TranscriptStatus.NEEDS_REVIEW.value
        )
        attempts.append(entry)
    final = dict(attempts[-1])
    final["status"] = TranscriptStatus.NEEDS_REVIEW.value
    return {"attempts": attempts, "final": final, "transcript_text": ""}


def _gate4_extract(
    settings: Settings,
    client: Any,
    prompts_dir: Path,
    asset: DriveMediaFile,
    transcript: str,
) -> dict[str, Any]:
    """L1 -> L2 -> L3, each strictly gated on the previous layer validating."""
    from . import extraction as ex

    from .models import l3_is_permitted

    outcome: dict[str, Any] = {
        "l1": None, "l1_parsed": None,
        "l2": None, "l2_parsed": None,
        "l3": None, "l3_parsed": None,
        "l3_skipped_reason": None, "layer_errors": {},
    }
    # A downstream layer failing must not discard the validated upstream
    # evidence: each layer is recorded before the next one is attempted.
    l1_result, l1 = ex.run_l1(
        client, settings, prompts_dir, asset.drive_id, asset.original_name, transcript
    )
    outcome["l1"] = l1_result
    outcome["l1_parsed"] = l1
    try:
        l2_result, l2 = ex.run_l2(
            client, settings, prompts_dir, asset.drive_id, l1_result, l1, transcript
        )
    except WorkflowError as error:
        outcome["layer_errors"]["L2"] = _sanitized(error)
        return outcome
    outcome["l2"] = l2_result
    outcome["l2_parsed"] = l2
    if not l3_is_permitted(l2):
        outcome["l3_skipped_reason"] = (
            f"L2 enrichment_status is {l2.enrichment_status}; only ENRICHED records reach L3."
        )
        return outcome
    try:
        l3_result, l3 = ex.run_l3(
            client, settings, prompts_dir, asset.drive_id, l2_result, l2, l1, transcript
        )
    except WorkflowError as error:
        outcome["layer_errors"]["L3"] = _sanitized(error)
        return outcome
    outcome["l3"] = l3_result
    outcome["l3_parsed"] = l3
    return outcome


def cmd_process_folder(args: argparse.Namespace) -> None:
    """Run Gates 1 to 5 over the configured Drive folder, one asset at a time."""
    import tempfile

    from .catalog import FULL_CATALOG_HEADERS, build_catalog_row, row_values
    from .discovery import select_assets

    dry_run = bool(args.dry_run)
    required = ("GOOGLE_CLOUD_PROJECT", "DRIVE_SHARED_FOLDER_ID", "GCS_STAGING_BUCKET")
    if not dry_run:
        required = required + ("CATALOG_SHEET_ID",)
    settings = Settings.from_environment(required=required)
    if args.run_id:
        settings = replace(settings, run_id=args.run_id.strip())
    tab_name = args.sheet_name or settings.catalog_tab_name
    prompts_dir = args.prompts_dir

    # The work directory is intentionally never cleaned up: this workflow
    # deletes nothing. The container filesystem is ephemeral and disappears
    # with the job execution on its own.
    work_dir = args.work_dir or Path(tempfile.mkdtemp(prefix=f"site-visit-{settings.run_id}-"))
    work_dir.mkdir(parents=True, exist_ok=True)

    drive = DriveGateway.from_settings(settings)
    storage = StorageGateway.from_settings(settings)
    prefix = run_prefix(settings)

    manifest, manifest_doc = _gate1_manifest(settings, drive)
    manifest_uri = storage.write_json(f"{prefix}/manifest.json", manifest_doc)
    _emit({
        "gate": 1,
        "run_id": settings.run_id,
        "manifest_gcs_uri": manifest_uri,
        "supported_count": manifest_doc["supported_count"],
        "excluded_count": manifest_doc["excluded_count"],
        "excluded_items": manifest_doc["excluded_items"],
        "work_dir": str(work_dir),
        "dry_run": dry_run,
    })

    assets = select_assets(manifest, asset_id=args.asset_id, limit=args.limit)
    client = None
    sheets = None
    if not dry_run:
        from .extraction import build_client

        client = build_client(settings)
        sheets = sheets_service(settings)
        ensure_sheet_tab(sheets, settings.catalog_sheet_id, tab_name)

    summaries: list[dict[str, Any]] = []
    for index, asset in enumerate(assets, start=1):
        # Sequential by design: conservative, documented concurrency of one.
        evidence_prefix = asset_prefix(settings, asset.drive_id)
        summary: dict[str, Any] = {
            "index": index,
            "of": len(assets),
            "source_asset_identifier": asset.drive_id,
            "original_drive_name": asset.original_name,
            "evidence_gcs_prefix": gcs_uri(storage.bucket_name, evidence_prefix),
            "drive_rename": "NOT_ATTEMPTED; suggested names are proposals only.",
        }
        try:
            wav_path, media_record = _gate2_media(drive, asset, work_dir)
            wav_uri = storage.upload_file(
                wav_path, wav_object_name(settings, asset.drive_id, 0), "audio/wav"
            )
            media_record["wav_gcs_uri"] = wav_uri
            summary["gate2"] = storage.write_json(f"{evidence_prefix}/media-preparation.json", media_record)
            summary["wav_gcs_uri"] = wav_uri

            if dry_run:
                summary["asset_status"] = ASSET_STATUS_DRY_RUN
                summary["note"] = "Dry run: Chirp, Vertex, and Sheets were not contacted."
                summaries.append(summary)
                _emit(summary)
                continue

            # The attempt-0 WAV was staged above and is reused as-is; Gate 3
            # must not write that object a second time.
            transcription = _gate3_transcribe(
                settings, storage, asset, wav_path, args.poll_timeout_seconds, wav_uri
            )
            transcript = transcription["transcript_text"]
            final = transcription["final"]
            transcript_uri = storage.write_text(
                f"{evidence_prefix}/transcript.txt", transcript or ""
            )
            summary["gate3"] = storage.write_json(
                f"{evidence_prefix}/transcription-record.json", transcription
            )
            summary["transcription_status"] = final["status"]
            transcription_row = {
                "status": final["status"],
                "wav_gcs_uri": final.get("wav_gcs_uri"),
                "output_gcs_uri": final.get("output_gcs_uri"),
                "started_at": final.get("started_at"),
                "completed_at": final.get("completed_at"),
                "transcript_gcs_uri": transcript_uri,
            }

            layers: dict[str, Any] = {}
            if final["status"] == TranscriptStatus.COMPLETED.value and transcript.strip():
                layers = _gate4_extract(settings, client, prompts_dir, asset, transcript)
                for name in ("l1", "l2", "l3"):
                    result = layers.get(name)
                    if result is not None:
                        storage.write_json(
                            f"{evidence_prefix}/prompt-execution/{name}.json", result.to_dict()
                        )
                summary["l3_skipped_reason"] = layers.get("l3_skipped_reason")
                summary["layer_errors"] = layers.get("layer_errors") or {}
                asset_status = (
                    ASSET_STATUS_NEEDS_REVIEW if summary["layer_errors"] else ASSET_STATUS_CATALOGUED
                )
            else:
                # No transcript means no extraction. Nothing is inferred.
                asset_status = ASSET_STATUS_NEEDS_REVIEW
                summary["note"] = (
                    "Transcript was empty after one retry; extraction stopped and the row "
                    "is recorded as NEEDS_REVIEW with no findings."
                )

            row = build_catalog_row(
                asset=asset,
                visit_drive_id=manifest.visit.drive_id,
                run_id=settings.run_id,
                asset_status=asset_status,
                transcription=transcription_row,
                updated_at=utc_now(),
                evidence_gcs_prefix=gcs_uri(storage.bucket_name, evidence_prefix),
                l1=layers.get("l1_parsed"),
                l2=layers.get("l2_parsed"),
                l3=layers.get("l3_parsed"),
            )
            storage.write_json(f"{evidence_prefix}/catalog-row.json", row)
            upsert = upsert_catalog_row(
                sheets,
                settings.catalog_sheet_id,
                tab_name,
                FULL_CATALOG_HEADERS,
                row_values(row),
                row["row_key"],
            )
            storage.write_json(f"{evidence_prefix}/catalog-upsert-record.json", upsert)
            summary["catalog_upsert"] = upsert
            summary["asset_status"] = asset_status
        except WorkflowError as error:
            summary["asset_status"] = ASSET_STATUS_FAILED
            summary["error"] = _sanitized(error)
        except Exception as error:  # noqa: BLE001 - one asset must not end the run
            summary["asset_status"] = ASSET_STATUS_FAILED
            summary["error"] = _sanitized(error)
        summaries.append(summary)
        _emit(summary)

    counts: dict[str, int] = {}
    for item in summaries:
        status = item.get("asset_status", ASSET_STATUS_FAILED)
        counts[status] = counts.get(status, 0) + 1
    run_summary = {
        "gate": "run-summary",
        "run_id": settings.run_id,
        "dry_run": dry_run,
        "drive_folder_id": settings.drive_shared_folder_id,
        "processing_boundary": "DIRECT_MEDIA_CHILDREN",
        "manifest_gcs_uri": manifest_uri,
        "evidence_gcs_prefix": gcs_uri(storage.bucket_name, prefix),
        "catalog_sheet_id": settings.catalog_sheet_id or None,
        "catalog_tab_name": tab_name if not dry_run else None,
        "speech_location": settings.speech_location,
        "vertex_location": settings.vertex_location,
        "vertex_model": settings.vertex_model,
        "runtime_service_account": settings.runtime_service_account,
        "selected_asset_count": len(assets),
        "excluded_items": manifest_doc["excluded_items"],
        "status_counts": counts,
        "assets": summaries,
    }
    try:
        run_summary["run_summary_gcs_uri"] = storage.write_json(
            f"{prefix}/run-summary.json", run_summary
        )
    except WorkflowError as error:
        run_summary["run_summary_write_error"] = _sanitized(error)
    _emit(run_summary)
    if args.output:
        write_json(args.output, run_summary)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="site-visit",
        description="Safety-first Site Visit workflow. Google is contacted only by explicit commands.",
    )
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("config-check").set_defaults(func=cmd_config_check)
    commands.add_parser(
        "auth-preflight",
        help="Read-only: report identity, Drive, GCS, Sheets, and runtime prerequisites.",
    ).set_defaults(func=cmd_auth_preflight)
    commands.add_parser(
        "list-folder-children",
        help="Read-only: list every immediate child of the configured Drive folder.",
    ).set_defaults(func=cmd_list_folder_children)
    commands.add_parser(
        "list-visits",
        help="Explicitly list only immediate visit folders in the configured Drive folder.",
    ).set_defaults(func=cmd_list_visits)

    process = commands.add_parser(
        "process-folder",
        help=(
            "Cloud-native end-to-end run over the configured Drive folder: manifest, media, "
            "Chirp, L1-L3, and one idempotent Sheets row per asset."
        ),
    )
    process.add_argument("--limit", type=int, default=None, help="Process at most N manifest assets.")
    process.add_argument("--asset-id", default=None, help="Process exactly one Drive asset ID.")
    process.add_argument(
        "--dry-run",
        action="store_true",
        help="Do everything except the Chirp, Vertex, and Sheets calls.",
    )
    process.add_argument("--run-id", default=None, help="Override RUN_ID for this execution.")
    process.add_argument(
        "--sheet-name", default=None, help="Catalog tab name; defaults to CATALOG_TAB_NAME."
    )
    process.add_argument(
        "--prompts-dir",
        type=_path,
        default=Path("prompts"),
        help="Directory holding the versioned l1/l2/l3 prompt files, read at runtime.",
    )
    process.add_argument(
        "--work-dir",
        type=_path,
        default=None,
        help="Container-local staging directory; a fresh temp directory by default.",
    )
    process.add_argument("--poll-timeout-seconds", type=int, default=1800)
    process.add_argument(
        "--output", type=_path, default=None, help="Optional local copy of the run summary JSON."
    )
    process.set_defaults(func=cmd_process_folder)

    intake = commands.add_parser("intake", help="Explicitly contact Drive and create one visit manifest.")
    intake.add_argument("--visit-id", required=True)
    intake.add_argument("--output", required=True, type=_path)
    intake.set_defaults(func=cmd_intake)

    stage = commands.add_parser("stage-video", help="Explicitly download one manifest asset.")
    stage.add_argument("--manifest", required=True, type=_path)
    stage.add_argument("--asset-id", required=True)
    stage.add_argument("--output", required=True, type=_path)
    stage.set_defaults(func=cmd_stage_video)

    prep = commands.add_parser("prepare-media", help="Run local ffprobe and ffmpeg for one manifest asset.")
    prep.add_argument("--manifest", required=True, type=_path)
    prep.add_argument("--asset-id", required=True)
    prep.add_argument("--staged-video", required=True, type=_path)
    prep.add_argument("--wav-output", required=True, type=_path)
    prep.add_argument("--probe-output", required=True, type=_path)
    prep.set_defaults(func=cmd_prepare_media)

    transcribe = commands.add_parser("transcribe", help="Explicitly upload one WAV and submit one batch.")
    transcribe.add_argument("--manifest", required=True, type=_path)
    transcribe.add_argument("--asset-id", required=True)
    transcribe.add_argument("--wav", required=True, type=_path)
    transcribe.add_argument("--attempt", required=True, type=int, choices=(0, 1))
    transcribe.add_argument("--gcs-object", required=True)
    transcribe.add_argument(
        "--staged-wav-uri",
        default=None,
        help=(
            "gs:// URI of a WAV already staged in GCS. Supplying it skips the upload entirely; "
            "without it the WAV is uploaded once and a collision fails rather than overwriting."
        ),
    )
    transcribe.add_argument("--output", required=True, type=_path)
    transcribe.set_defaults(func=cmd_transcribe)

    evaluate = commands.add_parser("evaluate-transcript", help="Apply the deterministic empty-transcript policy.")
    evaluate.add_argument("--record", required=True, type=_path)
    evaluate.add_argument("--transcript", required=True, type=_path)
    evaluate.add_argument("--output", required=True, type=_path)
    evaluate.set_defaults(func=cmd_evaluate_transcript)

    l1_request = commands.add_parser("create-l1-request", help="Create an offline L1 boundary payload.")
    l1_request.add_argument("--manifest", required=True, type=_path)
    l1_request.add_argument("--asset-id", required=True)
    l1_request.add_argument("--transcript", required=True, type=_path)
    l1_request.add_argument("--output", required=True, type=_path)
    l1_request.set_defaults(func=cmd_create_l1_request)

    l1_accept = commands.add_parser("accept-l1-result", help="Validate an approved external L1 result.")
    l1_accept.add_argument("--manifest", required=True, type=_path)
    l1_accept.add_argument("--asset-id", required=True)
    l1_accept.add_argument("--external-result", required=True, type=_path)
    l1_accept.add_argument("--output", required=True, type=_path)
    l1_accept.set_defaults(func=cmd_accept_l1_result)

    catalog = commands.add_parser("draft-catalog", help="Create a local, unpublished catalog draft.")
    catalog.add_argument("--manifest", required=True, type=_path)
    catalog.add_argument("--asset-id", required=True)
    catalog.add_argument("--l1-result", required=True, type=_path)
    catalog.add_argument("--transcription-record", required=True, type=_path)
    catalog.add_argument("--output", required=True, type=_path)
    catalog.set_defaults(func=cmd_draft_catalog)

    rename = commands.add_parser("rename-drive", help="Explicitly rename one file after approval.")
    rename.add_argument("--manifest", required=True, type=_path)
    rename.add_argument("--asset-id", required=True)
    rename.add_argument("--new-name", required=True)
    rename.add_argument("--approval", required=True, type=_path)
    rename.set_defaults(func=cmd_rename_drive)

    publish = commands.add_parser("publish-catalog", help="Explicitly publish an approved draft to Sheets.")
    publish.add_argument("--draft", required=True, type=_path)
    publish.add_argument("--approval", required=True, type=_path)
    publish.add_argument(
        "--sheet-name",
        default=None,
        help="Catalog tab name. Defaults to CATALOG_TAB_NAME; the tab is created if absent.",
    )
    publish.set_defaults(func=cmd_publish_catalog)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        args.func(args)
        return 0
    except WorkflowError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
