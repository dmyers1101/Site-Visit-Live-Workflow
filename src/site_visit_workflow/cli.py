from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from .config import (
    PROCESS_FOLDER_REQUIRED_SETTINGS,
    Settings,
    assert_output_targets_resolvable,
    default_run_id,
    gcs_uri,
)
from .errors import ExternalServiceError, ValidationError, WorkflowError
from .work_order import detect_work_order_request
from .google import (
    DriveGateway,
    StorageGateway,
    add_document_tab,
    asset_prefix,
    await_transcription,
    docs_service,
    ensure_catalog_spreadsheet,
    ensure_report_document,
    ensure_sheet_tab,
    list_document_tabs,
    read_batch_transcript,
    read_sheet_records,
    retitle_document_tab,
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


def _catalogued_ids(settings: Settings, sheet_id: str, tab_name: str) -> set[str]:
    """Row keys (Drive IDs) of rows whose asset_status is CATALOGUED. Read-only."""
    values = (
        sheets_service(settings).spreadsheets().values()
        .get(spreadsheetId=sheet_id, range=f"{tab_name}!A:ZZ").execute().get("values", [])
    )
    if not values:
        return set()
    header = values[0]
    if "asset_status" not in header:
        return set()
    col = header.index("asset_status")
    return {row[0] for row in values[1:] if row and len(row) > col and row[col] == "CATALOGUED"}


def cmd_list_portfolio(args: argparse.Namespace) -> None:
    """Read-only coverage report of every visit folder under the master folder."""
    from .portfolio import inventory_summary, walk_portfolio

    settings = Settings.from_environment(required=("GOOGLE_CLOUD_PROJECT",))
    root = args.root or os.environ.get("PORTFOLIO_ROOT_ID", "")
    drive = DriveGateway.from_settings(settings)
    visits = walk_portfolio(root, drive.list_children_paged)
    done: set[str] = set()
    for sheet_id in args.catalog_sheet_id or []:
        done |= _catalogued_ids(settings, sheet_id, args.tab_name)
    summary = inventory_summary(visits, done)
    summary["root_id"] = root
    summary["catalogued_ids_known"] = len(done)
    if args.details:
        summary["visit_details"] = [v.to_dict() for v in visits]
    print(json.dumps(summary, indent=2, default=str), flush=True)


MASTER_CATALOG_TITLE = "Site Visit Master Catalog"


def _portfolio_context(args: argparse.Namespace):
    """Shared setup: settings, Drive, walk, master Sheet, and its current records."""
    from . import portfolio as pf

    settings = Settings.from_environment(required=("GOOGLE_CLOUD_PROJECT", "GCS_STAGING_BUCKET"))
    root = (args.root or os.environ.get("PORTFOLIO_ROOT_ID", "")).strip()
    if not root:
        raise ValidationError("process-portfolio requires --root or PORTFOLIO_ROOT_ID.")
    drive = DriveGateway.from_settings(settings)
    visits = pf.walk_portfolio(root, drive.list_children_paged)
    sheet_id = (args.catalog_sheet_id or settings.catalog_sheet_id or "").strip()
    sheets = sheets_service(settings)
    created = False
    if not sheet_id:
        from .google import SPREADSHEET_MIME_TYPE, find_or_create_file

        sheet_id, _, created = find_or_create_file(drive, root, MASTER_CATALOG_TITLE, SPREADSHEET_MIME_TYPE)
    tab = settings.catalog_tab_name
    ensure_sheet_tab(sheets, sheet_id, tab)
    records = {r["row_key"]: r for r in read_sheet_records(sheets, sheet_id, tab)}
    _emit({"gate": "portfolio-outputs", "root_id": root, "master_catalog_sheet_id": sheet_id,
           "master_catalog_created": created, "visit_count": len(visits),
           "clip_count": sum(len(v.clips) for v in visits), "known_rows": len(records)})
    return settings, drive, sheets, visits, sheet_id, tab, records, root


def _uploaders(settings: Settings, drive: DriveGateway, visit) -> dict[str, tuple[str | None, str | None]]:
    """Uploader per clip, captured BEFORE any rename; revision fallback if the SA is last modifier."""
    from .portfolio import resolve_uploader

    result = {}
    for clip in visit.clips:
        who = resolve_uploader(clip, settings.runtime_service_account)
        if who == (None, None):
            who = resolve_uploader(clip, settings.runtime_service_account, drive.first_revision_user(clip.drive_id))
        result[clip.drive_id] = who
    return result


def _write_visit_report(settings, drive, sheets, sheet_id, tab, visit, prompts_dir, run_id) -> dict[str, Any]:
    """Gate 7 for one visit: property Doc -> visit tab -> report replaces that tab (ADR 0013) -> retitle."""
    from . import portfolio as pf
    from . import report as rp
    from .extraction import build_client
    from .google import DOCUMENT_MIME_TYPE, find_or_create_file

    rows = [r for r in read_sheet_records(sheets, sheet_id, tab) if r.get("visit_drive_id") == visit.drive_id]
    if not rows:
        return {"status": "SKIPPED_NO_ROWS"}
    docs = docs_service(settings)
    property_folder = visit.path[:2]
    doc_parent = _property_folder_id(drive, visit)
    doc_id, doc_link, doc_created = find_or_create_file(
        drive, doc_parent, f"{visit.property_name or property_folder[-1]} Site Visit Reports", DOCUMENT_MIME_TYPE
    )
    ensure_sheet_tab(sheets, sheet_id, pf.REPORTS_TAB)
    registry = {r["row_key"]: r for r in read_sheet_records(sheets, sheet_id, pf.REPORTS_TAB)}
    title = pf.tab_title(rows)
    tabs = list_document_tabs(docs, doc_id)
    known = registry.get(visit.drive_id, {})
    tab_id = known.get("tab_id") if known.get("doc_id") == doc_id else None
    if tab_id and tab_id not in {t["tab_id"] for t in tabs}:
        tab_id = None  # a human removed the tab; make a new one rather than fail
    # ADR 0013: only the tab the registry maps to THIS visit may be cleared. A
    # new tab, or an unclaimed empty one, has nothing to clear.
    clear_existing = bool(tab_id)
    if not tab_id:
        claimed = {r.get("tab_id") for r in registry.values() if r.get("doc_id") == doc_id}
        spare = next((t for t in tabs if t["empty"] and t["tab_id"] not in claimed), None)
        tab_id = spare["tab_id"] if spare else add_document_tab(docs, doc_id, title)
    folder_label = f"{visit.property_name} / {visit.name}"
    record = rp.run_report(build_client(settings), replace(settings, run_id=run_id), docs,
                           prompts_dir, doc_id, doc_link, doc_created, folder_label, rows,
                           new_names=pf.renamed_names(rows), tab_id=tab_id, replace=clear_existing)
    retitle_document_tab(docs, doc_id, tab_id, title)
    upsert_catalog_row(sheets, sheet_id, pf.REPORTS_TAB, pf.REPORT_REGISTRY_HEADERS,
                       [visit.drive_id, visit.property_name or "", visit.name, doc_id, tab_id, title, utc_now()],
                       visit.drive_id)
    return {"status": record.status, "doc_id": doc_id, "doc_web_link": doc_link,
            "doc_created": doc_created, "tab_id": tab_id, "tab_title": title,
            "replaced_existing": record.replaced_existing, "prompt_version": record.prompt_version,
            "action_items": record.action_item_count, "backfilled_refs": record.backfilled_refs,
            "validation_errors": record.validation_errors, "counts": record.summary_counts,
            "usage": record.usage}


def _property_folder_id(drive: DriveGateway, visit) -> str:
    """The Drive ID of the visit's Property folder (path segment 2), found by walking up."""
    service = drive._service  # noqa: SLF001 - read-only parent lookup
    current = visit.drive_id
    chain = []
    for _ in range(len(visit.path)):
        meta = service.files().get(fileId=current, fields="id,parents", supportsAllDrives=True).execute()
        chain.append(meta["id"])
        parents = meta.get("parents") or []
        if not parents:
            break
        current = parents[0]
    # chain = [visit, ..., state]; the Property folder is len(path)-2 steps above the visit.
    index = len(visit.path) - 2
    return chain[index] if 0 <= index < len(chain) else visit.drive_id


def cmd_process_portfolio(args: argparse.Namespace) -> None:
    """Every visit under the master folder: new clips only, then one report per touched visit.

    Reuses `cmd_process_folder` per visit (Gates 1-6) with portfolio hooks, so
    there is exactly one implementation of the gates. Gate 7 runs here, per
    visit, over ALL of that visit's rows in the master Sheet.
    """
    from types import SimpleNamespace

    from . import portfolio as pf

    settings, drive, sheets, visits, sheet_id, tab, records, root = _portfolio_context(args)
    run_id = (args.run_id or "").strip() or default_run_id()
    budget = args.max_clips
    results = []
    only = set(args.visit_id or [])
    registry: dict[str, dict[str, Any]] = {}
    if args.report and not args.dry_run:
        ensure_sheet_tab(sheets, sheet_id, pf.REPORTS_TAB)
        registry = {r["row_key"]: r for r in read_sheet_records(sheets, sheet_id, pf.REPORTS_TAB)}
    for index, visit in enumerate(visits, start=1):
        if only and visit.drive_id not in only:
            continue
        skip, attempts = pf.select_pending(visit, records, retry_failed=args.retry_failed)
        pending = len(visit.clips) - len(skip)
        entry: dict[str, Any] = {"visit": visit.name, "property": visit.property_name,
                                 "visit_drive_id": visit.drive_id, "pending": pending, "processed": 0}
        if pending == 0:
            entry["status"] = "NOTHING_PENDING"
        elif budget is not None and budget <= 0:
            entry["status"] = "DEFERRED_BUDGET"
        else:
            os.environ["DRIVE_SHARED_FOLDER_ID"] = visit.drive_id
            os.environ["DRIVE_OUTPUT_PARENT_ID"] = visit.drive_id
            visit_args = SimpleNamespace(
                dry_run=args.dry_run, run_id=f"{run_id}-v{index:02d}", catalog_sheet_id=sheet_id,
                report_doc_id="", report=False, rename_approved=args.rename_approved,
                sheet_name=tab, prompts_dir=args.prompts_dir, work_dir=None, asset_id=None,
                limit=budget, poll_timeout_seconds=args.poll_timeout_seconds, output=None,
                skip_asset_ids=skip,
                row_extras=pf.row_extras(visit, _uploaders(settings, drive, visit), attempts),
            )
            try:
                summary = cmd_process_folder(visit_args)
                entry["status_counts"] = summary.get("status_counts", {})
                entry["processed"] = len(summary.get("assets", []))
                if budget is not None:
                    budget -= entry["processed"]
                entry["status"] = "PROCESSED"
            except Exception as error:  # noqa: BLE001 - one visit must not end the run
                entry["status"] = "FAILED"
                entry["error"] = _sanitized(error)
        # Gate 7 self-heals: report when this run processed clips OR the visit's
        # rows are newer than its last written report (e.g. a prior report failed).
        if args.report and not args.dry_run:
            # The due-check read is inside the try too: run site-visit-nightly-6nvhm
            # died on a BrokenPipe in this read, outside any handler (2026-09-29).
            try:
                visit_rows = [r for r in read_sheet_records(sheets, sheet_id, tab)
                              if r.get("visit_drive_id") == visit.drive_id]
                if pf.report_is_due(visit_rows, registry.get(visit.drive_id), entry["processed"]):
                    entry["report"] = _write_visit_report(
                        settings, drive, sheets, sheet_id, tab, visit, args.prompts_dir, run_id)
            except Exception as error:  # noqa: BLE001 - a report failure never fails the run
                entry["report"] = {"status": "FAILED", "error": _sanitized(error)}
        results.append(entry)
        _emit({"gate": "portfolio-visit", "run_id": run_id, **entry})
    _emit({"gate": "portfolio-summary", "run_id": run_id, "root_id": root,
           "master_catalog_sheet_id": sheet_id, "dry_run": args.dry_run,
           "rename_approved_flag": args.rename_approved, "max_clips": args.max_clips,
           "visits": results})


def cmd_preview_report(args: argparse.Namespace) -> None:
    """Write one visit's report into a NEW tab of a scratch Doc for review.

    Read-only against the catalog and the property report Docs: it never
    touches a property Doc, never clears anything, and never writes the
    Reports registry. Used to review a template or prompt change (ADR 0013).
    """
    from . import portfolio as pf
    from . import report as rp
    from .extraction import build_client

    settings = Settings.from_environment(required=("GOOGLE_CLOUD_PROJECT",))
    sheet_id = (args.catalog_sheet_id or settings.catalog_sheet_id or "").strip()
    if not sheet_id or not args.doc_id.strip():
        raise ValidationError("preview-report requires --doc-id and --catalog-sheet-id (or CATALOG_SHEET_ID).")
    sheets = sheets_service(settings)
    rows = [r for r in read_sheet_records(sheets, sheet_id, args.tab_name)
            if r.get("visit_drive_id") == args.visit_id]
    if not rows:
        raise ValidationError(f"No catalog rows for visit {args.visit_id} in {sheet_id}/{args.tab_name}.")
    docs = docs_service(settings)
    run_id = (args.run_id or "").strip() or default_run_id()
    tab_id = add_document_tab(docs, args.doc_id, f"Preview {run_id} · {pf.tab_title(rows)}")
    label = f"{rows[0].get('property', '')} / {rows[0].get('visit_name', '')}"
    record = rp.run_report(build_client(settings), replace(settings, run_id=run_id), docs, args.prompts_dir,
                           args.doc_id, None, False, label, rows,
                           new_names=pf.renamed_names(rows), tab_id=tab_id, replace=False)
    _emit({"gate": "preview-report", "visit_id": args.visit_id, "report": record.to_dict()})


def cmd_reprocess_l2(args: argparse.Namespace) -> None:
    """Re-run L2 (+L3) on one visit's catalogued clips with the current prompts.

    Transcripts and L1 are read from GCS evidence and never changed. Every new
    row is computed and checked in memory first (`reprocess.py` invariants);
    nothing is written unless all pass. `--dry-run` writes nothing at all.
    """
    import json as _json

    from . import extraction as ex
    from . import portfolio as pf
    from . import reprocess as rpc
    from .catalog import FULL_CATALOG_HEADERS, row_values
    from .extraction import LayerResult
    from .models import L1Extraction, l3_is_permitted

    settings, drive, sheets, visits, sheet_id, tab, records, _root = _portfolio_context(args)
    visit = next((v for v in visits if v.drive_id == args.visit_id), None)
    if visit is None:
        raise ValidationError(f"Visit {args.visit_id} is not under the portfolio root.")
    run_id = (args.run_id or "").strip() or default_run_id()
    settings = replace(settings, run_id=run_id)
    storage = StorageGateway.from_settings(settings)
    client = ex.build_client(settings)
    rows = [r for r in records.values() if r.get("visit_drive_id") == visit.drive_id]
    planned, skipped, failures = [], [], []
    for row in rows:
        ok, why = rpc.eligible(row)
        if not ok:
            skipped.append({"row_key": row["row_key"], "reason": why})
            continue
        try:
            transcript = storage.read_text(rpc.object_name(row["transcript_gcs_uri"], storage.bucket_name))
            l1_record = _json.loads(storage.read_text(rpc.object_name(
                row["evidence_gcs_prefix"], storage.bucket_name) + "/prompt-execution/l1.json"))
            from dataclasses import fields as _fields

            known = {f.name for f in _fields(LayerResult)}
            l1_result = LayerResult(**{k: v for k, v in l1_record.items() if k in known})
            if l1_result.layer != "L1" or l1_result.source_asset_identifier != row["row_key"]                     or not l1_result.validated:
                raise ValidationError(f"Stored L1 evidence for {row['row_key']} is not a validated L1 record.")
            l1 = L1Extraction(**l1_result.parsed_output)
            errors: dict[str, Any] = {}
            l2_result = l2 = l3_result = l3 = None
            try:
                l2_result, l2 = ex.run_l2(client, settings, args.prompts_dir, row["row_key"], l1_result, l1, transcript)
            except WorkflowError as error:
                errors["L2"] = _sanitized(error)
            if l2 is not None and l3_is_permitted(l2):
                try:
                    l3_result, l3 = ex.run_l3(client, settings, args.prompts_dir, row["row_key"],
                                              l2_result, l2, l1, transcript)
                except WorkflowError as error:
                    errors["L3"] = _sanitized(error)
            new = rpc.rebuild_row(row, l1, l2, l3, errors, utc_now())
            changed = rpc.assert_only_layer_columns_changed(row, new)
            planned.append({"row": new, "old": row, "changed": sorted(changed - {"updated_at"}),
                            "l2": l2_result, "l3": l3_result, "errors": errors})
        except WorkflowError as error:
            failures.append({"row_key": row["row_key"], "error": _sanitized(error)})
    if failures:
        _emit({"gate": "reprocess-l2", "status": "ABORTED_NOTHING_WRITTEN", "failures": failures})
        raise ValidationError(f"{len(failures)} row(s) failed the reprocess checks; nothing was written.")
    if {p["row"]["row_key"] for p in planned} - {r["row_key"] for r in rows}:
        raise ValidationError("Reprocess produced a row key outside the selected visit; nothing was written.")
    transitions: dict[str, int] = {}
    for p in planned:
        key = f"{p['old'].get('l2_status') or '-'}->{p['row']['l2_status'] or '-'}"
        transitions[key] = transitions.get(key, 0) + 1
    summary = {"gate": "reprocess-l2", "run_id": run_id, "visit_id": visit.drive_id, "dry_run": args.dry_run,
               "selected": len(rows), "reprocessed": len(planned), "skipped": skipped,
               "status_transitions": transitions,
               "changed_rows": [{"row_key": p["row"]["row_key"], "changed": p["changed"],
                                 "l2_status": [p["old"].get("l2_status"), p["row"]["l2_status"]],
                                 "errors": p["errors"]} for p in planned if p["changed"]]}
    if args.dry_run:
        _emit(summary)
        return
    prefix = f"{settings.gcs_staging_prefix}/{run_id}/reprocess-l2"
    for p in planned:
        key = p["row"]["row_key"]
        for name in ("l2", "l3"):
            if p[name] is not None:
                storage.write_json(f"{prefix}/{key}/{name}.json", p[name].to_dict())
        upsert_catalog_row(sheets, sheet_id, tab, FULL_CATALOG_HEADERS, row_values(p["row"]), key)
    storage.write_json(f"{prefix}/summary.json", summary)
    if args.report:
        summary["report"] = _write_visit_report(settings, drive, sheets, sheet_id, tab, visit,
                                                args.prompts_dir, run_id)
    _emit(summary)


def cmd_migrate_catalog(args: argparse.Namespace) -> None:
    """Copy rows from an old per-visit catalog into the master Sheet. Never deletes the source.

    Portfolio columns are filled from the walk (state/property/visit/uploader).
    A row already present in the master Sheet is left alone.
    """
    from . import portfolio as pf
    from .catalog import FULL_CATALOG_HEADERS

    settings, drive, sheets, visits, sheet_id, tab, records, _ = _portfolio_context(args)
    by_clip = {c.drive_id: v for v in visits for c in v.clips}
    moved, skipped = 0, 0
    for row in read_sheet_records(sheets, args.source_sheet_id, args.source_tab):
        key = row.get("row_key", "")
        if not key or key in records:
            skipped += 1
            continue
        visit = by_clip.get(key)
        if visit is not None:
            clip = next(c for c in visit.clips if c.drive_id == key)
            uploader = _uploaders(settings, drive, SimpleNamespaceVisit(visit, clip))[key]
            row.update(pf.row_extras(visit, {key: uploader}, {})[key])
        values = [row.get(name, "") for name in FULL_CATALOG_HEADERS]
        upsert_catalog_row(sheets, sheet_id, tab, FULL_CATALOG_HEADERS, values, key)
        moved += 1
    _emit({"gate": "migrate-catalog", "source_sheet_id": args.source_sheet_id,
           "master_catalog_sheet_id": sheet_id, "copied": moved, "skipped_existing": skipped})


class SimpleNamespaceVisit:
    """A one-clip view of a visit, so `_uploaders` can resolve a single clip."""

    def __init__(self, visit, clip) -> None:
        self.clips = (clip,)
        self.drive_id = visit.drive_id


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
# process-folder: the cloud-native, end-to-end Gate 1..7 run.
#
# THE RULE THAT NEVER CHANGES: this command deletes nothing, anywhere - not a
# Drive file, not a GCS object, not a Sheets row or tab, not a paragraph of a
# Doc. The runtime identity holds no delete permission anywhere by design
# (ADR 0005), and no future gate may assume otherwise.
#
# Two statements that used to sit beside that rule are no longer true, and are
# corrected rather than removed:
#   * The command DOES now create Drive files - the catalog Spreadsheet and the
#     report Doc, in the configured Drive output folder, when no ID was given.
#     Source videos are never created, copied, or moved.
#   * The command DOES now rename Drive source videos, in Gate 6, and ONLY when
#     both the RENAME_APPROVED environment flag and the --rename-approved CLI
#     flag are present. Without both approvals a suggested filename remains a
#     proposal recorded in the catalog for human review, exactly as before.
#
# Media bytes still flow Drive -> this container's ephemeral filesystem -> GCS.
# No operator workstation is involved at any point.
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


def cmd_process_folder(args: argparse.Namespace) -> dict[str, Any]:
    """Run Gates 1 to 7 over the configured Drive folder, one asset at a time.

    Gates 1-5 are discovery, media, transcription, extraction, and the catalog
    upsert. Gate 6 is the approval-gated Drive rename, and Gate 7 writes the
    narrative report into a Google Doc - deliberately after Gate 6, so the
    report can refer to the new filenames. A failure in Gate 6 or Gate 7 is
    recorded and the run continues, exactly like a per-asset failure.

    CATALOG_SHEET_ID and REPORT_DOC_ID are OPTIONAL inputs. When either is
    empty the run creates that file in the Drive output folder and the
    resulting ID becomes an OUTPUT, emitted early and repeated in the run
    summary so a later failure still leaves the file discoverable.
    """
    import tempfile

    from .catalog import FULL_CATALOG_HEADERS, build_catalog_row, row_values
    from .discovery import select_assets
    from . import rename as rn
    from . import report as rp

    dry_run = bool(args.dry_run)
    # CATALOG_SHEET_ID is no longer required here: the sheet ID is an output of
    # this command when it is not supplied. The "is there a viable target at
    # all" check moved to `assert_output_targets_resolvable`, below, so a
    # genuine misconfiguration still fails before any asset is processed.
    settings = Settings.from_environment(required=PROCESS_FOLDER_REQUIRED_SETTINGS)
    if args.run_id:
        settings = replace(settings, run_id=args.run_id.strip())
    if getattr(args, "catalog_sheet_id", None):
        settings = replace(settings, catalog_sheet_id=args.catalog_sheet_id.strip())
    if getattr(args, "report_doc_id", None):
        settings = replace(settings, report_doc_id=args.report_doc_id.strip())
    report_requested = bool(getattr(args, "report", False))
    # Belt and braces: the environment flag alone authorizes nothing, and the
    # CLI flag alone authorizes nothing. Gate 6 needs both.
    rename_authorized = rn.rename_is_authorized(
        settings.rename_approved, bool(getattr(args, "rename_approved", False))
    )
    if not dry_run:
        assert_output_targets_resolvable(settings, report_requested)
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

    # Portfolio hooks (ADR 0009). Absent on a plain process-folder run, so its
    # behaviour is unchanged. `skip_asset_ids` is applied BEFORE `--limit` so
    # the clip budget is spent only on clips that still need work.
    skip_ids: set[str] = set(getattr(args, "skip_asset_ids", None) or ())
    row_extras: dict[str, dict[str, Any]] = getattr(args, "row_extras", None) or {}
    pending_files = tuple(a for a in manifest.media_files if a.drive_id not in skip_ids)
    if not pending_files:
        _emit({"gate": "select", "run_id": settings.run_id, "pending": 0,
               "note": "Every clip in this folder is already catalogued or under review."})
        return {"run_id": settings.run_id, "status_counts": {}, "assets": [], "catalog_rows": []}
    pending_manifest = replace(manifest, media_files=pending_files) if skip_ids else manifest
    assets = select_assets(pending_manifest, asset_id=args.asset_id, limit=args.limit)
    client = None
    sheets = None
    # Resolved ONCE, here, before the asset loop. Everything downstream uses
    # these two variables and never `settings.catalog_sheet_id` /
    # `settings.report_doc_id` directly: a second code path reading the raw
    # setting is exactly the class of bug that produced the double-WAV-upload.
    catalog_sheet_id = settings.catalog_sheet_id
    catalog_sheet_link: str | None = None
    catalog_sheet_created = False
    report_doc_id = settings.report_doc_id
    report_doc_link: str | None = None
    report_doc_created = False
    if not dry_run:
        from .extraction import build_client

        catalog_sheet_id, catalog_sheet_link, catalog_sheet_created = ensure_catalog_spreadsheet(
            settings, drive, f"Site Visit Catalog - {manifest.visit.name}"
        )
        if report_requested:
            report_doc_id, report_doc_link, report_doc_created = ensure_report_document(
                settings, drive, f"Site Visit Report - {manifest.visit.name} - {settings.run_id}"
            )
        # Emitted immediately: if a later gate fails, the operator can still
        # find the files this run created.
        _emit({
            "gate": "outputs",
            "run_id": settings.run_id,
            "catalog_sheet_id": catalog_sheet_id,
            "catalog_sheet_web_link": catalog_sheet_link,
            "catalog_sheet_created": catalog_sheet_created,
            "report_doc_id": report_doc_id or None,
            "report_doc_web_link": report_doc_link,
            "report_doc_created": report_doc_created,
            "drive_output_parent_id": settings.drive_output_parent_id,
            "rename_authorized": rename_authorized,
        })
        client = build_client(settings)
        sheets = sheets_service(settings)
        ensure_sheet_tab(sheets, catalog_sheet_id, tab_name)

    summaries: list[dict[str, Any]] = []
    catalog_rows: list[dict[str, Any]] = []
    rename_outcomes: list[rn.RenameOutcome] = []
    new_drive_names: dict[str, str | None] = {}
    # Every name currently held in the folder, for Gate 6's collision check.
    # The whole manifest plus excluded items, not just the --limit selection.
    folder_names: set[str] = {item.original_name for item in manifest.media_files} | {
        str(item.get("name")) for item in manifest_doc["excluded_items"] if isinstance(item, dict) and item.get("name")
    }
    for index, asset in enumerate(assets, start=1):
        # Sequential by design: conservative, documented concurrency of one.
        evidence_prefix = asset_prefix(settings, asset.drive_id)
        summary: dict[str, Any] = {
            "index": index,
            "of": len(assets),
            "source_asset_identifier": asset.drive_id,
            "original_drive_name": asset.original_name,
            "evidence_gcs_prefix": gcs_uri(storage.bucket_name, evidence_prefix),
            # The ACTUAL rename outcome, not a hardcoded claim. This record is
            # archived to GCS as evidence, so it starts at the honest default
            # for an asset that has not yet become eligible and is replaced by
            # the real Gate 6 outcome below.
            "drive_rename": rn.plan_rename(
                asset.drive_id,
                asset.original_name,
                None,
                "NOT_YET_PROCESSED",
                False,
                rename_authorized,
                dry_run=dry_run,
            ).to_dict(),
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

            work_order = detect_work_order_request(
                transcript if final["status"] == TranscriptStatus.COMPLETED.value else None
            )
            summary["work_order"] = work_order
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

            # Gate 6: the approval-gated rename, before the row is built so the
            # catalogue records what actually happened rather than a proposal.
            l1_parsed = layers.get("l1_parsed")
            rename_outcome = rn.execute_rename(
                drive,
                asset.drive_id,
                asset.original_name,
                getattr(l1_parsed, "suggested_filename", None),
                asset_status,
                rn.l1_has_finding(l1_parsed),
                rename_authorized,
                dry_run=dry_run,
                taken_names=folder_names,
            )
            if rename_outcome.rename_status == rn.RENAME_RENAMED and rename_outcome.new_drive_name:
                folder_names.discard(asset.original_name)
                folder_names.add(rename_outcome.new_drive_name)
            rename_outcomes.append(rename_outcome)
            summary["drive_rename"] = rename_outcome.to_dict()
            new_drive_names[asset.drive_id] = (
                rename_outcome.new_drive_name
                if rename_outcome.rename_status == rn.RENAME_RENAMED
                else None
            )
            storage.write_json(f"{evidence_prefix}/drive-rename.json", rename_outcome.to_dict())
            if rename_outcome.rename_status == rn.RENAME_RENAMED:
                rename_decision = f"RENAMED_TO:{rename_outcome.new_drive_name}"
            elif rename_outcome.rename_status == rn.RENAME_SKIPPED_NOT_APPROVED:
                # No approval was given, so the historical wording is the true
                # one: the suggested name remains a proposal.
                rename_decision = None
            else:
                rename_decision = rename_outcome.rename_status

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
                drive_rename_decision=rename_decision,
                extras=row_extras.get(asset.drive_id),
                work_order=work_order,
            )
            catalog_rows.append(row)
            storage.write_json(f"{evidence_prefix}/catalog-row.json", row)
            upsert = upsert_catalog_row(
                sheets,
                catalog_sheet_id,
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
        if summary.get("asset_status") == ASSET_STATUS_FAILED and row_extras and sheets is not None:
            # Portfolio runs record a FAILED row so the Sheet shows the clip and
            # its attempt_count, which caps nightly retries. Best effort only.
            try:
                failed_row = build_catalog_row(
                    asset=asset, visit_drive_id=manifest.visit.drive_id, run_id=settings.run_id,
                    asset_status=ASSET_STATUS_FAILED, transcription={}, updated_at=utc_now(),
                    evidence_gcs_prefix=gcs_uri(storage.bucket_name, evidence_prefix),
                    drive_rename_decision="NOT_RENAMED_FAILED", extras=row_extras.get(asset.drive_id),
                )
                upsert_catalog_row(sheets, catalog_sheet_id, tab_name, FULL_CATALOG_HEADERS,
                                   row_values(failed_row), failed_row["row_key"])
            except Exception as row_error:  # noqa: BLE001
                summary["failed_row_error"] = _sanitized(row_error)
        summaries.append(summary)
        _emit(summary)

    counts: dict[str, int] = {}
    for item in summaries:
        status = item.get("asset_status", ASSET_STATUS_FAILED)
        counts[status] = counts.get(status, 0) + 1

    # Gate 7: one narrative report per run, written into the Google Doc. It runs
    # AFTER Gate 6 so it can name the new filenames, and its failure is recorded
    # rather than fatal - the catalogue is already written by this point.
    report_record: dict[str, Any] | None = None
    report_status = rp.REPORT_STATUS_NOT_REQUESTED
    if report_requested and dry_run:
        report_status = rp.REPORT_STATUS_SKIPPED_DRY_RUN
    elif report_requested:
        try:
            record = rp.run_report(
                client,
                settings,
                docs_service(settings),
                prompts_dir,
                report_doc_id,
                report_doc_link,
                report_doc_created,
                manifest.visit.name,
                catalog_rows,
                new_names=new_drive_names,
            )
            report_record = record.to_dict()
            report_status = record.status
        except Exception as error:  # noqa: BLE001 - Gate 7 must not fail the run
            report_status = rp.REPORT_STATUS_FAILED
            report_record = {
                "run_id": settings.run_id,
                "status": rp.REPORT_STATUS_FAILED,
                "document_id": report_doc_id or None,
                "document_web_link": report_doc_link,
                "document_created": report_doc_created,
                "error": _sanitized(error),
            }
        if report_record is not None:
            try:
                storage.write_json(f"{prefix}/report-record.json", report_record)
            except WorkflowError as error:
                report_record["evidence_write_error"] = _sanitized(error)
        _emit({"gate": 7, "run_id": settings.run_id, "report": report_record})

    run_summary = {
        "gate": "run-summary",
        "run_id": settings.run_id,
        "dry_run": dry_run,
        "drive_folder_id": settings.drive_shared_folder_id,
        "processing_boundary": "DIRECT_MEDIA_CHILDREN",
        "manifest_gcs_uri": manifest_uri,
        "evidence_gcs_prefix": gcs_uri(storage.bucket_name, prefix),
        "catalog_sheet_id": catalog_sheet_id or None,
        "catalog_sheet_web_link": catalog_sheet_link,
        "catalog_sheet_created": catalog_sheet_created,
        "report_doc_id": report_doc_id or None,
        "report_doc_web_link": report_doc_link,
        "report_doc_created": report_doc_created,
        "report_status": report_status,
        "report": report_record,
        "rename_authorized": rename_authorized,
        "rename_summary": rn.summarize_renames(rename_outcomes),
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
    if getattr(args, "output", None):
        write_json(args.output, run_summary)
    run_summary["catalog_rows"] = catalog_rows
    return run_summary


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

    portfolio = commands.add_parser(
        "list-portfolio",
        help="Read-only: walk the master folder and report every visit folder and clip count.",
    )
    portfolio.add_argument("--root", default="", help="Master folder ID (default: PORTFOLIO_ROOT_ID).")
    portfolio.add_argument(
        "--catalog-sheet-id", action="append", default=[],
        help="Catalog Sheet(s) whose CATALOGUED rows count as done. Repeatable.",
    )
    portfolio.add_argument("--tab-name", default="Catalog")
    portfolio.add_argument("--details", action="store_true", help="Include per-clip detail.")
    portfolio.set_defaults(func=cmd_list_portfolio)

    run_portfolio = commands.add_parser(
        "process-portfolio",
        help="Every visit under the master folder: new clips only, then one report per touched visit.",
    )
    run_portfolio.add_argument("--root", default="", help="Master folder ID (default: PORTFOLIO_ROOT_ID).")
    run_portfolio.add_argument("--catalog-sheet-id", default="",
                               help="Master Sheet ID (default: CATALOG_SHEET_ID; created in --root if empty).")
    run_portfolio.add_argument("--run-id", default="")
    run_portfolio.add_argument("--max-clips", type=int, default=None,
                               help="Clip budget for this run; leftovers roll to the next run.")
    run_portfolio.add_argument("--visit-id", action="append", default=[],
                               help="Limit to these visit folder IDs (repeatable). Default: all.")
    run_portfolio.add_argument("--retry-failed", action="store_true",
                               help="Retry FAILED clips even past the 3-attempt cap (after a code fix).")
    run_portfolio.add_argument("--dry-run", action="store_true")
    run_portfolio.add_argument("--rename-approved", action="store_true")
    run_portfolio.add_argument("--report", action="store_true")
    run_portfolio.add_argument("--prompts-dir", type=Path, default=Path("prompts"))
    run_portfolio.add_argument("--poll-timeout-seconds", type=int, default=1800)
    run_portfolio.set_defaults(func=cmd_process_portfolio)

    # AppFolio work orders (ADR 0015). Imported lazily so the core CLI never needs `requests`.
    def _wo(name: str):
        def run(args: argparse.Namespace) -> None:
            from . import work_order_job

            getattr(work_order_job, name)(args)
        return run

    wo_cand = commands.add_parser("wo-candidates", help="Append new work-order candidates (PENDING_REVIEW) to the WorkOrders tab.")
    wo_cand.add_argument("--catalog-sheet-id", default="")
    wo_cand.add_argument("--sheet-name", default="")
    wo_cand.add_argument("--visit-id", action="append", default=[])
    wo_cand.add_argument("--prompts-dir", type=Path, default=Path("prompts"))
    wo_cand.add_argument("--dry-run", action="store_true", help="Print the rows; write nothing.")
    wo_cand.set_defaults(func=_wo("cmd_wo_candidates"))

    wo_run = commands.add_parser("wo-run", help="Plan (default) or create (--live) AppFolio work orders for approved rows.")
    wo_run.add_argument("--catalog-sheet-id", default="")
    wo_run.add_argument("--run-id", default="")
    wo_run.add_argument("--wo-key", action="append", default=[], help="Limit to these ledger keys (repeatable).")
    wo_run.add_argument("--max-creates", type=int, default=1, help="Hard cap on POSTs this run (default 1).")
    wo_run.add_argument("--live", action="store_true", help="Create in AppFolio; also needs env WORK_ORDERS_LIVE=1.")
    wo_run.set_defaults(func=_wo("cmd_wo_run"))

    reproc = commands.add_parser(
        "reprocess-l2",
        help="Re-run L2/L3 on one visit's clips with the current prompts (transcripts and L1 unchanged).",
    )
    reproc.add_argument("--visit-id", required=True)
    reproc.add_argument("--root", default="", help="Master folder ID (default: PORTFOLIO_ROOT_ID).")
    reproc.add_argument("--catalog-sheet-id", default="")
    reproc.add_argument("--run-id", default="")
    reproc.add_argument("--dry-run", action="store_true", help="Compute and check; write nothing.")
    reproc.add_argument("--report", action="store_true", help="Rewrite the visit's report tab afterwards.")
    reproc.add_argument("--prompts-dir", type=Path, default=Path("prompts"))
    reproc.set_defaults(func=cmd_reprocess_l2)

    preview = commands.add_parser(
        "preview-report",
        help="Write one visit's report into a new tab of a scratch Doc (no property Doc touched).",
    )
    preview.add_argument("--visit-id", required=True, help="Visit folder Drive ID.")
    preview.add_argument("--doc-id", required=True, help="Scratch Google Doc to add the preview tab to.")
    preview.add_argument("--catalog-sheet-id", default="")
    preview.add_argument("--tab-name", default="Catalog")
    preview.add_argument("--run-id", default="")
    preview.add_argument("--prompts-dir", type=Path, default=Path("prompts"))
    preview.set_defaults(func=cmd_preview_report)

    migrate = commands.add_parser(
        "migrate-catalog", help="Copy rows from an old catalog into the master Sheet. Never deletes."
    )
    migrate.add_argument("--root", default="")
    migrate.add_argument("--catalog-sheet-id", default="")
    migrate.add_argument("--source-sheet-id", required=True)
    migrate.add_argument("--source-tab", default="Catalog")
    migrate.set_defaults(func=cmd_migrate_catalog)

    process = commands.add_parser(
        "process-folder",
        help=(
            "Cloud-native end-to-end run over the configured Drive folder: manifest, media, "
            "Chirp, L1-L3, one idempotent Sheets row per asset, the approval-gated Drive "
            "rename, and the narrative Google Docs report."
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
    process.add_argument(
        "--rename-approved",
        action="store_true",
        help=(
            "Gate 6: rename each CATALOGUED asset to its suggested filename. Requires "
            "RENAME_APPROVED to be set in the environment as well - both are needed."
        ),
    )
    process.add_argument(
        "--report",
        action="store_true",
        help="Gate 7: write the narrative run report into the Google Doc.",
    )
    process.add_argument(
        "--report-doc-id",
        default=None,
        help="Existing Google Doc to append the report to; overrides REPORT_DOC_ID. "
        "Omit both and the run creates its own Doc in the Drive output folder.",
    )
    process.add_argument(
        "--catalog-sheet-id",
        default=None,
        help="Existing catalog spreadsheet; overrides CATALOG_SHEET_ID. Omit both and the "
        "run creates its own spreadsheet and reports the new ID in the run summary.",
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
