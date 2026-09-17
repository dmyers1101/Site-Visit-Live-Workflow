from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from .config import Settings, gcs_uri
from .errors import ExternalServiceError, ValidationError, WorkflowError
from .google import DriveGateway, runtime_credentials, submit_transcription
from .jsonio import approval_from_dict, manifest_from_dict, read_json, transcription_from_dict, write_json
from .media import prepare_wav
from .models import (
    CatalogDraft,
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
        record = submit_transcription(settings, args.wav, args.asset_id, args.attempt, args.gcs_object)
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
    service = build("sheets", "v4", credentials=runtime_credentials(settings), cache_discovery=False)
    values = [getattr(draft, header) for header in CATALOG_HEADERS]
    try:
        existing = service.spreadsheets().values().get(
            spreadsheetId=settings.catalog_sheet_id, range=f"{args.sheet_name}!A:A"
        ).execute().get("values", [])
        if not existing:
            service.spreadsheets().values().append(
                spreadsheetId=settings.catalog_sheet_id,
                range=f"{args.sheet_name}!A:O",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [list(CATALOG_HEADERS)]},
            ).execute()
        elif not existing[0] or existing[0][0] != "row_key":
            raise ValidationError("Catalog sheet is missing the required row_key header in column A.")
        match = next(
            (index + 2 for index, row in enumerate(existing[1:]) if row and row[0] == draft.row_key),
            None,
        )
        if match:
            service.spreadsheets().values().update(
                spreadsheetId=settings.catalog_sheet_id,
                range=f"{args.sheet_name}!A{match}:O{match}",
                valueInputOption="RAW",
                body={"values": [values]},
            ).execute()
        else:
            service.spreadsheets().values().append(
                spreadsheetId=settings.catalog_sheet_id,
                range=f"{args.sheet_name}!A:O",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [values]},
            ).execute()
    except HttpError as error:
        raise ExternalServiceError(f"Catalog publication failed: {error}") from error
    print(f"Published approved catalog row using idempotent key: {draft.row_key}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="site-visit",
        description="Safety-first Site Visit workflow. Google is contacted only by explicit commands.",
    )
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("config-check").set_defaults(func=cmd_config_check)
    commands.add_parser(
        "list-visits",
        help="Explicitly list only immediate visit folders in the configured Drive folder.",
    ).set_defaults(func=cmd_list_visits)

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
    publish.add_argument("--sheet-name", default="Catalog Drafts")
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
