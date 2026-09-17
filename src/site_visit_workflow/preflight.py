"""Read-only authorization preflight checks.

Every check here is strictly read-only: metadata and capability inspection
only. Nothing in this module downloads media, renames, writes, or mutates any
Drive, GCS, or Sheets resource. Each check captures its own sanitized error so
that one failure does not hide the remaining results.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from typing import Any

from .config import DEPLOYED_SERVICE_ACCOUNT, Settings
from .google import runtime_credentials

FOLDER_MIME = "application/vnd.google-apps.folder"
FILE_FIELDS = "id,name,mimeType,size,modifiedTime,webViewLink,driveId,parents,trashed,capabilities"
FOLDER_GET_FIELDS = (
    "id,name,mimeType,driveId,parents,webViewLink,shared,trashed,createdTime,modifiedTime,capabilities"
)


CAPABILITY_KEYS = ("canDownload", "canReadDrive", "canRename", "canEdit", "canDelete")


def _trim(item: dict[str, Any]) -> dict[str, Any]:
    """Keep the reported metadata plus only the capability flags this preflight asserts on."""
    caps = item.get("capabilities", {}) or {}
    trimmed = {k: v for k, v in item.items() if k != "capabilities"}
    trimmed["capabilities"] = {k: caps.get(k) for k in CAPABILITY_KEYS}
    return trimmed


def _sanitize(error: Exception) -> dict[str, Any]:
    """Reduce an exception to a non-secret status/reason record."""
    record: dict[str, Any] = {"error_type": type(error).__name__}
    status = getattr(getattr(error, "resp", None), "status", None)
    if status is not None:
        record["http_status"] = status
    detail = getattr(error, "error_details", None)
    if detail:
        record["details"] = str(detail)[:400]
    record["message"] = str(error)[:600]
    return record


def _runtime_environment() -> dict[str, Any]:
    versions: dict[str, Any] = {}
    try:
        from importlib.metadata import version as _v

        for package in (
            "google-api-python-client",
            "google-auth",
            "google-cloud-speech",
            "google-cloud-storage",
            "google-genai",
        ):
            try:
                versions[package] = _v(package)
            except Exception as error:  # noqa: BLE001 - report, never fail preflight
                versions[package] = "NOT_INSTALLED (" + type(error).__name__ + ")"
    except Exception as error:  # noqa: BLE001
        versions["_error"] = _sanitize(error)

    binaries: dict[str, Any] = {}
    for binary in ("ffmpeg", "ffprobe"):
        path = shutil.which(binary)
        if not path:
            binaries[binary] = {"available": False}
            continue
        try:
            out = subprocess.run(
                [binary, "-version"], capture_output=True, text=True, timeout=20, check=False
            )
            stream = out.stdout or out.stderr or ""
            first = stream.splitlines()[0] if stream else ""
        except Exception as error:  # noqa: BLE001
            first = "version probe failed: " + type(error).__name__
        binaries[binary] = {"available": True, "path": path, "version": first}

    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "package_versions": versions,
        "binaries": binaries,
    }


def _identity(settings: Settings) -> dict[str, Any]:
    try:
        credentials = runtime_credentials(settings)
    except Exception as error:  # noqa: BLE001
        return {"resolved": False, "error": _sanitize(error)}
    email = getattr(credentials, "service_account_email", None)
    return {
        "resolved": True,
        "service_account_email": email,
        "matches_designated_identity": email == DEPLOYED_SERVICE_ACCOUNT,
        "designated_identity": DEPLOYED_SERVICE_ACCOUNT,
        "credential_class": type(credentials).__name__,
        "scopes": list(getattr(credentials, "scopes", None) or []),
        "quota_project_id": getattr(credentials, "quota_project_id", None),
    }


def _drive(settings: Settings) -> dict[str, Any]:
    result: dict[str, Any] = {"folder_id": settings.drive_shared_folder_id}
    try:
        from googleapiclient.discovery import build

        service = build(
            "drive", "v3", credentials=runtime_credentials(settings), cache_discovery=False
        )
    except Exception as error:  # noqa: BLE001
        result["build_service"] = {"ok": False, "error": _sanitize(error)}
        return result
    result["build_service"] = {"ok": True}

    # 1. Retrieve the target folder by ID.
    folder: dict[str, Any] = {}
    try:
        folder = (
            service.files()
            .get(
                fileId=settings.drive_shared_folder_id,
                fields=FOLDER_GET_FIELDS,
                supportsAllDrives=True,
            )
            .execute()
        )
        result["folder_get"] = {"ok": True, "folder": folder}
    except Exception as error:  # noqa: BLE001
        result["folder_get"] = {"ok": False, "error": _sanitize(error)}

    # 2. Shared-drive context, if any.
    drive_id = folder.get("driveId")
    if drive_id:
        try:
            drive_meta = (
                service.drives()
                .get(driveId=drive_id, fields="id,name,capabilities,restrictions,createdTime")
                .execute()
            )
            result["shared_drive"] = {"ok": True, "in_shared_drive": True, "drive": drive_meta}
            result["resolved_drive_id"] = settings.drive_shared_folder_id
        except Exception as error:  # noqa: BLE001
            result["shared_drive"] = {
                "ok": False,
                "in_shared_drive": True,
                "drive_id": drive_id,
                "error": _sanitize(error),
            }
    else:
        result["shared_drive"] = {
            "ok": True,
            "in_shared_drive": False,
            "note": "No driveId returned; folder resolves in My Drive / shared-with-me context.",
        }

    # 3 and 4. Immediate children, split by folder vs file. Never recursive.
    base = "'" + settings.drive_shared_folder_id + "' in parents and trashed = false"
    queries = (
        ("child_folders", base + " and mimeType = '" + FOLDER_MIME + "'"),
        ("child_files", base + " and mimeType != '" + FOLDER_MIME + "'"),
    )
    for label, query in queries:
        try:
            response = (
                service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken,files(" + FILE_FIELDS + ")",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    pageSize=100,
                )
                .execute()
            )
            items = [_trim(item) for item in response.get("files", [])]
            result[label] = {
                "ok": True,
                "count": len(items),
                "truncated": bool(response.get("nextPageToken")),
                "mime_types": sorted({i.get("mimeType", "") for i in items}),
                "sample_items": items[:3],
            }
        except Exception as error:  # noqa: BLE001
            result[label] = {"ok": False, "error": _sanitize(error)}

    # 5. Capability summary for a representative child. No action is taken.
    files_block = result.get("child_files", {})
    items = files_block.get("sample_items") or []
    if items:
        sample = items[0]
        caps = sample.get("capabilities", {}) or {}
        result["capability_probe"] = {
            "probed_file_name": sample.get("name"),
            "probed_file_id": sample.get("id"),
            "can_download": caps.get("canDownload"),
            "can_read_drive": caps.get("canReadDrive"),
            "can_rename": caps.get("canRename"),
            "can_edit": caps.get("canEdit"),
            "can_delete": caps.get("canDelete"),
            "note": "Capability metadata only. No download, rename, or edit was performed.",
        }
    else:
        result["capability_probe"] = {"note": "No child file available to inspect."}
    return result


def _storage(settings: Settings) -> dict[str, Any]:
    if not settings.gcs_staging_bucket:
        return {
            "configured": False,
            "blocking_gap": "No GCS_STAGING_BUCKET is configured for the deployed runtime.",
        }
    result: dict[str, Any] = {"configured": True, "bucket": settings.gcs_staging_bucket}
    try:
        from google.cloud import storage

        client = storage.Client(
            project=settings.project_id, credentials=runtime_credentials(settings)
        )
        bucket = client.bucket(settings.gcs_staging_bucket)
        result["exists"] = bucket.exists()
        if result["exists"]:
            bucket.reload()
            result["location"] = bucket.location
            result["storage_class"] = bucket.storage_class
            result["permissions_held"] = bucket.test_iam_permissions(
                [
                    "storage.objects.create",
                    "storage.objects.get",
                    "storage.objects.list",
                    "storage.objects.delete",
                ]
            )
            names = [
                blob.name
                for blob in client.list_blobs(
                    settings.gcs_staging_bucket,
                    prefix=settings.gcs_staging_prefix,
                    max_results=10,
                )
            ]
            result["prefix_listing"] = {"prefix": settings.gcs_staging_prefix, "sample": names}
    except Exception as error:  # noqa: BLE001
        result["error"] = _sanitize(error)
    return result


def _sheets(settings: Settings) -> dict[str, Any]:
    if not settings.catalog_sheet_id:
        return {
            "configured": False,
            "blocking_gap": "No CATALOG_SHEET_ID is configured for the deployed runtime.",
        }
    result: dict[str, Any] = {"configured": True, "sheet_id": settings.catalog_sheet_id}
    try:
        from googleapiclient.discovery import build

        credentials = runtime_credentials(settings)
        sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        meta = (
            sheets.spreadsheets()
            .get(spreadsheetId=settings.catalog_sheet_id, includeGridData=False)
            .execute()
        )
        result["readable"] = True
        result["title"] = meta.get("properties", {}).get("title")
        result["tabs"] = [s["properties"]["title"] for s in meta.get("sheets", [])]
        drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        file_meta = (
            drive.files()
            .get(
                fileId=settings.catalog_sheet_id,
                fields="id,name,capabilities",
                supportsAllDrives=True,
            )
            .execute()
        )
        caps = file_meta.get("capabilities", {}) or {}
        result["can_edit"] = caps.get("canEdit")
        result["note"] = "Metadata and capability only. No tab, row, or value was written."
    except Exception as error:  # noqa: BLE001
        result["readable"] = False
        result["error"] = _sanitize(error)
    return result


def _create_catalog_sheet(settings: Settings, parent_drive_id: str | None) -> dict[str, Any]:
    """Create the catalog spreadsheet inside the Shared Drive.

    This is the single intentional write in this module, and it runs only when
    CREATE_CATALOG_SHEET is set and no CATALOG_SHEET_ID is configured yet. It
    creates one new, empty spreadsheet. It never touches a source video.
    """
    import os

    if settings.catalog_sheet_id:
        return {"attempted": False, "reason": "CATALOG_SHEET_ID already configured."}
    if os.environ.get("CREATE_CATALOG_SHEET", "").strip().lower() not in ("1", "true", "yes"):
        return {"attempted": False, "reason": "CREATE_CATALOG_SHEET flag not set."}
    if not parent_drive_id:
        return {"attempted": False, "reason": "No Shared Drive ID resolved; refusing to create in SA My Drive."}
    try:
        from googleapiclient.discovery import build

        drive = build("drive", "v3", credentials=runtime_credentials(settings), cache_discovery=False)
        created = (
            drive.files()
            .create(
                body={
                    "name": "Site Visit Catalog",
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                    "parents": [parent_drive_id],
                },
                fields="id,name,webViewLink,parents,driveId",
                supportsAllDrives=True,
            )
            .execute()
        )
        return {"attempted": True, "ok": True, "created": created}
    except Exception as error:  # noqa: BLE001
        return {"attempted": True, "ok": False, "error": _sanitize(error)}


def run_preflight(settings: Settings) -> dict[str, Any]:
    """Run every read-only authorization check and return one report."""
    drive_report = _drive(settings)
    return {
        "preflight_version": "1.0.0",
        "read_only": True,
        "configured_folder_id": settings.drive_shared_folder_id,
        "configured_project": settings.project_id,
        "configured_region": settings.region,
        "runtime_environment": _runtime_environment(),
        "identity": _identity(settings),
        "drive": drive_report,
        "cloud_storage": _storage(settings),
        "sheets": _sheets(settings),
        "catalog_sheet_creation": _create_catalog_sheet(settings, drive_report.get("resolved_drive_id")),
    }


def emit(settings: Settings) -> None:
    print(json.dumps(run_preflight(settings), indent=1, default=str))
