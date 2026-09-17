from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import DEPLOYED_SERVICE_ACCOUNT, Settings, gcs_uri
from .errors import ExternalServiceError, ValidationError
from .models import DriveMediaFile, TranscriptionRecord, TranscriptStatus, VisitFolder, utc_now

GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/devstorage.read_write",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/spreadsheets",
)


def runtime_credentials(settings: Settings) -> Any:
    """Obtain ambient ADC; deployed jobs must be attached to the designated identity."""
    try:
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError, RefreshError
        from google.auth.transport.requests import Request
    except ImportError as error:
        raise ExternalServiceError("Google dependencies are not installed.") from error

    try:
        credentials, _ = google.auth.default(scopes=GOOGLE_SCOPES)
    except DefaultCredentialsError as error:
        raise ExternalServiceError("Application Default Credentials are unavailable.") from error
    if settings.environment == "deployed":
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            raise ExternalServiceError("Unable to refresh deployed workload credentials.") from error
        identity = getattr(credentials, "service_account_email", None)
        if identity != DEPLOYED_SERVICE_ACCOUNT:
            raise ValidationError(
                "Deployed workload identity is not site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com."
            )
    return credentials


class DriveGateway:
    """Drive operations are limited to immediate children of configured folders."""

    def __init__(self, service: Any, shared_folder_id: str) -> None:
        self._service = service
        self._shared_folder_id = shared_folder_id

    @classmethod
    def from_settings(cls, settings: Settings) -> "DriveGateway":
        try:
            from googleapiclient.discovery import build
        except ImportError as error:
            raise ExternalServiceError("Google Drive dependency is not installed.") from error
        return cls(
            build("drive", "v3", credentials=runtime_credentials(settings), cache_discovery=False),
            settings.drive_shared_folder_id,
        )

    def _children(self, parent_id: str, folder_only: bool) -> list[dict[str, Any]]:
        try:
            from googleapiclient.errors import HttpError
        except ImportError as error:
            raise ExternalServiceError("Google Drive dependency is not installed.") from error
        query = f"'{parent_id}' in parents and trashed = false"
        if folder_only:
            query += " and mimeType = 'application/vnd.google-apps.folder'"
        try:
            response = self._service.files().list(
                q=query,
                spaces="drive",
                fields=(
                    "nextPageToken,files(id,name,mimeType,webViewLink,size,modifiedTime,"
                    "trashed,capabilities(canDownload,canRename,canDelete))"
                ),
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                pageSize=100,
            ).execute()
        except HttpError as error:
            raise ExternalServiceError(f"Drive immediate-child listing failed for {parent_id}: {error}") from error
        if response.get("nextPageToken"):
            raise ExternalServiceError("More than 100 immediate children; refine the test folder before use.")
        return response.get("files", [])

    def list_visit_folders(self) -> list[VisitFolder]:
        return [
            VisitFolder(drive_id=item["id"], name=item["name"], web_view_link=item.get("webViewLink"))
            for item in self._children(self._shared_folder_id, folder_only=True)
        ]

    def list_immediate_children(self, parent_id: str | None = None) -> list[dict[str, Any]]:
        """Return metadata for every immediate child, without filtering by type."""
        return [
            {
                "name": item["name"],
                "drive_id": item["id"],
                "mime_type": item["mimeType"],
                "web_view_link": item.get("webViewLink"),
            }
            for item in self._children(parent_id or self._shared_folder_id, folder_only=False)
        ]

    def list_immediate_videos(self, visit_id: str) -> list[DriveMediaFile]:
        return [
            DriveMediaFile(
                drive_id=item["id"],
                original_name=item["name"],
                mime_type=item["mimeType"],
                web_view_link=item.get("webViewLink"),
                size_bytes=int(item["size"]) if item.get("size") else None,
                modified_time=item.get("modifiedTime"),
            )
            for item in self._children(visit_id, folder_only=False)
            if item.get("mimeType", "").startswith("video/")
        ]

    def download(self, asset_id: str, destination: Path) -> None:
        try:
            from googleapiclient.errors import HttpError
            from googleapiclient.http import MediaIoBaseDownload
        except ImportError as error:
            raise ExternalServiceError("Google Drive dependency is not installed.") from error
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("xb") as file:
                request = self._service.files().get_media(fileId=asset_id, supportsAllDrives=True)
                downloader = MediaIoBaseDownload(file, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
        except FileExistsError as error:
            raise ValidationError(f"Refusing to overwrite staged file: {destination}") from error
        except HttpError as error:
            raise ExternalServiceError(f"Drive download failed for {asset_id}: {error}") from error

    def list_immediate_children_detailed(self, parent_id: str | None = None) -> list[dict[str, Any]]:
        """Return every immediate child with the fields Gate 1 classification needs.

        Boundary: this is one non-recursive listing of direct children. It never
        descends into a subfolder and never mutates anything.
        """
        return [
            {
                "name": item["name"],
                "drive_id": item["id"],
                "mime_type": item["mimeType"],
                "web_view_link": item.get("webViewLink"),
                "size_bytes": int(item["size"]) if item.get("size") else None,
                "modified_time": item.get("modifiedTime"),
                "trashed": bool(item.get("trashed", False)),
                "capabilities": item.get("capabilities") or {},
            }
            for item in self._children(parent_id or self._shared_folder_id, folder_only=False)
        ]

    def folder_metadata(self, folder_id: str | None = None) -> dict[str, Any]:
        """Read-only: resolve the configured folder's own name and link for the manifest."""
        try:
            from googleapiclient.errors import HttpError
        except ImportError as error:
            raise ExternalServiceError("Google Drive dependency is not installed.") from error
        target = folder_id or self._shared_folder_id
        try:
            return self._service.files().get(
                fileId=target,
                fields="id,name,mimeType,webViewLink,driveId,trashed",
                supportsAllDrives=True,
            ).execute()
        except HttpError as error:
            raise ExternalServiceError(f"Drive folder lookup failed for {target}: {error}") from error

    def stage_asset(self, asset_id: str, destination: Path) -> Path:
        """Download one Drive asset into the container's ephemeral filesystem.

        Boundary: bytes go Drive -> this container -> GCS. No operator
        workstation is ever involved, and the Drive source is never modified.
        """
        self.download(asset_id, destination)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise ExternalServiceError(f"Drive download produced an empty staged file: {destination}")
        return destination

    def rename(self, asset_id: str, new_name: str) -> None:
        if not new_name.strip():
            raise ValidationError("New Drive name must be non-empty.")
        try:
            from googleapiclient.errors import HttpError
            self._service.files().update(
                fileId=asset_id, body={"name": new_name}, supportsAllDrives=True
            ).execute()
        except HttpError as error:
            raise ExternalServiceError(f"Drive rename failed for {asset_id}: {error}") from error


def speech_client_options(settings: Settings) -> Any:
    """Chirp needs the location-specific endpoint for every location except `global`."""
    from google.api_core.client_options import ClientOptions

    if settings.speech_location == "global":
        return ClientOptions()
    return ClientOptions(api_endpoint=f"{settings.speech_location}-speech.googleapis.com")


def submit_transcription(
    settings: Settings,
    wav_path: Path | None,
    asset_id: str,
    attempt: int,
    object_name: str,
    staged_wav_uri: str | None = None,
) -> TranscriptionRecord:
    """Submit one Chirp BatchRecognize operation for one WAV.

    Boundary: when `staged_wav_uri` is supplied the WAV is ALREADY in GCS and
    this function uploads nothing. Re-uploading an existing object is an
    overwrite, and an overwrite needs `storage.objects.delete`, which the
    runtime identity deliberately does not hold (ADR 0005). A live trial run
    caught exactly that double-write, so the staged URI is now the normal path
    and the upload here is the compatibility fallback for the standalone
    `transcribe` command.

    `object_name` remains the single source of truth for the object's path. A
    supplied `staged_wav_uri` must agree with it, so there is no second path
    that can drift away from what Gate 3 actually staged.
    """
    if attempt not in (0, 1):
        raise ValidationError("Only attempts 0 and 1 are permitted.")
    if not object_name.endswith(".wav") or asset_id not in object_name:
        raise ValidationError("GCS object must be a clearly named .wav path containing the Drive asset ID.")
    expected_uri = gcs_uri(settings.gcs_staging_bucket, object_name)
    if staged_wav_uri is not None and staged_wav_uri != expected_uri:
        raise ValidationError(
            "Staged WAV URI does not match the computed object path. "
            f"Staged: {staged_wav_uri}. Expected: {expected_uri}."
        )
    if staged_wav_uri is None and (wav_path is None or not wav_path.is_file()):
        raise ValidationError(f"WAV input does not exist: {wav_path}")
    try:
        from google.api_core.exceptions import GoogleAPICallError, PreconditionFailed
        from google.cloud import speech_v2, storage
        from google.cloud.speech_v2.types import cloud_speech
    except ImportError as error:
        raise ExternalServiceError("Speech and Storage dependencies are not installed.") from error

    credentials = runtime_credentials(settings)
    wav_uri = expected_uri
    # Run-scoped so a second run of the same asset writes beside the first
    # instead of colliding with objects this identity cannot delete.
    output_uri = gcs_uri(settings.gcs_staging_bucket, speech_output_prefix(settings, asset_id, attempt))
    try:
        if staged_wav_uri is None:
            # Compatibility path only. `if_generation_match=0` makes a collision
            # a loud failure rather than a silent overwrite.
            bucket = storage.Client(project=settings.project_id, credentials=credentials).bucket(
                settings.gcs_staging_bucket
            )
            try:
                bucket.blob(object_name).upload_from_filename(
                    str(wav_path), content_type="audio/wav", if_generation_match=0
                )
            except PreconditionFailed as error:
                raise ValidationError(
                    f"Refusing to overwrite an existing staged WAV: {wav_uri}. "
                    "Pass the staged URI instead of re-uploading, or use a fresh RUN_ID."
                ) from error
        client = speech_v2.SpeechClient(
            credentials=credentials, client_options=speech_client_options(settings)
        )
        # Boundary: Chirp 3 is served from the `us`/`eu` MULTI-REGIONS only, so the
        # recognizer path uses `speech_location`, never the Cloud Run `region`.
        recognizer = f"projects/{settings.project_id}/locations/{settings.speech_location}/recognizers/_"
        operation = client.batch_recognize(
            request=cloud_speech.BatchRecognizeRequest(
                recognizer=recognizer,
                config=cloud_speech.RecognitionConfig(
                    auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
                    language_codes=["en-US"],
                    # The only place a Speech model string is set. Defaults to
                    # `chirp_3`; the legacy `chirp` alias is rejected in config.
                    model=settings.speech_model,
                ),
                files=[cloud_speech.BatchRecognizeFileMetadata(uri=wav_uri)],
                recognition_output_config=cloud_speech.RecognitionOutputConfig(
                    gcs_output_config=cloud_speech.GcsOutputConfig(uri=output_uri)
                ),
            )
        )
    except GoogleAPICallError as error:
        raise ExternalServiceError(f"Speech BatchRecognize submission failed: {error}") from error
    return TranscriptionRecord(
        source_asset_identifier=asset_id,
        wav_gcs_uri=wav_uri,
        output_gcs_uri=output_uri,
        attempt=attempt,
        status=TranscriptStatus.SUBMITTED,
        started_at=utc_now(),
        operation_name=operation.operation.name,
    )


# ---------------------------------------------------------------------------
# Cloud-native staging: Drive -> ephemeral container filesystem -> GCS.
#
# Boundary: this section only CREATES objects. The runtime identity holds
# objectCreator + objectViewer and deliberately has NO delete permission on
# GCS, so nothing here deletes, truncates, or rewrites an object in place.
# Every write is a distinct, run-scoped object name guarded by an
# if_generation_match=0 precondition, which fails loudly instead of clobbering.
# ---------------------------------------------------------------------------


def run_prefix(settings: Settings) -> str:
    """The run-scoped evidence prefix; every artifact for a run lives beneath it."""
    return f"{settings.gcs_staging_prefix}/{settings.run_id}"


def asset_prefix(settings: Settings, asset_id: str) -> str:
    """One prefix per asset per run, keyed by the immutable Drive asset ID."""
    if not asset_id.strip():
        raise ValidationError("Asset prefix requires a non-empty Drive asset ID.")
    return f"{run_prefix(settings)}/{asset_id}"


def wav_object_name(settings: Settings, asset_id: str, attempt: int) -> str:
    """A unique WAV path containing the run ID, the Drive asset ID, and the attempt."""
    if attempt not in (0, 1):
        raise ValidationError("Only attempts 0 and 1 are permitted.")
    return f"{asset_prefix(settings, asset_id)}/audio/attempt-{attempt}/{asset_id}.wav"


def speech_output_prefix(settings: Settings, asset_id: str, attempt: int) -> str:
    """Chirp writes its own result objects under this run-scoped prefix."""
    if attempt not in (0, 1):
        raise ValidationError("Only attempts 0 and 1 are permitted.")
    return f"{asset_prefix(settings, asset_id)}/speech-output/attempt-{attempt}/"


class StorageGateway:
    """Create-only access to the staging bucket.

    How to update this later: keep every method create-only. If a future
    requirement seems to need a delete, raise it as an ADR instead - the
    service account has no delete permission by design, and code that assumes
    otherwise will fail in production rather than in review.
    """

    def __init__(self, client: Any, bucket_name: str) -> None:
        self._client = client
        self._bucket = client.bucket(bucket_name)
        self._bucket_name = bucket_name

    @classmethod
    def from_settings(cls, settings: Settings) -> "StorageGateway":
        try:
            from google.cloud import storage
        except ImportError as error:
            raise ExternalServiceError("Cloud Storage dependency is not installed.") from error
        if not settings.gcs_staging_bucket:
            raise ValidationError("GCS_STAGING_BUCKET must be configured before staging to GCS.")
        return cls(
            storage.Client(project=settings.project_id, credentials=runtime_credentials(settings)),
            settings.gcs_staging_bucket,
        )

    @property
    def bucket_name(self) -> str:
        return self._bucket_name

    def _create(self, object_name: str, upload: Any) -> str:
        from google.api_core.exceptions import GoogleAPICallError, PreconditionFailed

        uri = gcs_uri(self._bucket_name, object_name)
        try:
            upload(self._bucket.blob(object_name))
        except PreconditionFailed as error:
            raise ValidationError(
                f"Refusing to overwrite an existing GCS object: {uri}. Use a fresh RUN_ID."
            ) from error
        except GoogleAPICallError as error:
            raise ExternalServiceError(f"GCS write failed for {uri}: {error}") from error
        return uri

    def upload_file(self, local_path: Path, object_name: str, content_type: str) -> str:
        """Upload one staged file from the container to a new GCS object."""
        if not local_path.is_file():
            raise ValidationError(f"Cannot upload a file that does not exist: {local_path}")
        return self._create(
            object_name,
            lambda blob: blob.upload_from_filename(
                str(local_path), content_type=content_type, if_generation_match=0
            ),
        )

    def write_text(self, object_name: str, text: str, content_type: str = "text/plain") -> str:
        """Write one new text artifact; never truncates an existing object."""
        return self._create(
            object_name,
            lambda blob: blob.upload_from_string(
                text, content_type=content_type, if_generation_match=0
            ),
        )

    def write_json(self, object_name: str, payload: Any) -> str:
        """Write one new JSON artifact under the run-scoped prefix."""
        import json as _json

        body = _json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
        return self.write_text(object_name, body, content_type="application/json")

    def read_text(self, object_name: str) -> str:
        from google.api_core.exceptions import GoogleAPICallError

        try:
            return self._bucket.blob(object_name).download_as_text()
        except GoogleAPICallError as error:
            raise ExternalServiceError(
                f"GCS read failed for {gcs_uri(self._bucket_name, object_name)}: {error}"
            ) from error

    def list_object_names(self, prefix: str) -> list[str]:
        from google.api_core.exceptions import GoogleAPICallError

        try:
            return [blob.name for blob in self._client.list_blobs(self._bucket_name, prefix=prefix)]
        except GoogleAPICallError as error:
            raise ExternalServiceError(f"GCS listing failed for prefix {prefix}: {error}") from error


def transcript_text_from_batch_result(payload: dict[str, Any]) -> str:
    """Flatten one BatchRecognize GCS result document into plain transcript text.

    The v2 output document is `{"results": [{"alternatives": [{"transcript": ...}]}]}`.
    An absent or empty alternative contributes nothing; it is never invented.
    """
    parts: list[str] = []
    for result in payload.get("results") or []:
        for alternative in (result or {}).get("alternatives") or []:
            text = (alternative or {}).get("transcript") or ""
            if text.strip():
                parts.append(text.strip())
            break
    return " ".join(parts).strip()


def read_batch_transcript(
    storage_gateway: "StorageGateway", output_prefix: str
) -> tuple[str, list[str]]:
    """Read every BatchRecognize output object under a prefix; return text and sources."""
    import json as _json

    names = [
        name for name in storage_gateway.list_object_names(output_prefix) if name.endswith(".json")
    ]
    chunks: list[str] = []
    for name in sorted(names):
        try:
            document = _json.loads(storage_gateway.read_text(name))
        except ValueError as error:
            raise ExternalServiceError(f"BatchRecognize output {name} is not valid JSON.") from error
        text = transcript_text_from_batch_result(document)
        if text:
            chunks.append(text)
    return " ".join(chunks).strip(), names


def await_transcription(
    settings: Settings, operation_name: str, timeout_seconds: int = 1800
) -> dict[str, Any]:
    """Poll one BatchRecognize long-running operation until it settles.

    Boundary: polling is read-only. A timeout returns `done: False` and leaves
    the operation running; it never cancels or deletes anything.
    """
    import time

    try:
        from google.api_core.exceptions import GoogleAPICallError
        from google.cloud import speech_v2
    except ImportError as error:
        raise ExternalServiceError("Speech dependency is not installed.") from error

    client = speech_v2.SpeechClient(
        credentials=runtime_credentials(settings), client_options=speech_client_options(settings)
    )
    deadline = time.monotonic() + timeout_seconds
    delay = 5.0
    while True:
        try:
            operation = client.transport.operations_client.get_operation(operation_name)
        except GoogleAPICallError as error:
            raise ExternalServiceError(
                f"Operation poll failed for {operation_name}: {error}"
            ) from error
        if operation.done:
            error_message = operation.error.message if operation.error.code else None
            return {"done": True, "operation_name": operation_name, "error": error_message or None}
        if time.monotonic() >= deadline:
            return {
                "done": False,
                "operation_name": operation_name,
                "error": f"Operation did not complete within {timeout_seconds}s; it is still running.",
            }
        time.sleep(min(delay, max(1.0, deadline - time.monotonic())))
        delay = min(delay * 1.5, 30.0)


# ---------------------------------------------------------------------------
# Sheets catalog upsert.
#
# Boundary: this section creates a tab if it is missing and writes/updates one
# row keyed by the immutable Drive asset ID. It never deletes or renames a tab
# (including the spreadsheet default "Sheet1"), and it never deletes a row.
# ---------------------------------------------------------------------------


def column_letter(index: int) -> str:
    """1-based spreadsheet column letter, so header sets wider than Z still work."""
    if index < 1:
        raise ValidationError("Spreadsheet columns are 1-based.")
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def sheets_service(settings: Settings) -> Any:
    try:
        from googleapiclient.discovery import build
    except ImportError as error:
        raise ExternalServiceError("Google Sheets dependency is not installed.") from error
    return build("sheets", "v4", credentials=runtime_credentials(settings), cache_discovery=False)


def ensure_sheet_tab(service: Any, spreadsheet_id: str, tab_name: str) -> dict[str, Any]:
    """Create the catalog tab when it is absent. Existing tabs are left untouched."""
    try:
        from googleapiclient.errors import HttpError
    except ImportError as error:
        raise ExternalServiceError("Google Sheets dependency is not installed.") from error
    if not tab_name.strip():
        raise ValidationError("Catalog tab name must be non-empty.")
    try:
        meta = (
            service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, includeGridData=False)
            .execute()
        )
        existing = [sheet["properties"]["title"] for sheet in meta.get("sheets", [])]
        if tab_name in existing:
            return {"created": False, "tab_name": tab_name, "existing_tabs": existing}
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]},
        ).execute()
    except HttpError as error:
        raise ExternalServiceError(
            f"Catalog tab preparation failed for {tab_name}: {error}"
        ) from error
    return {"created": True, "tab_name": tab_name, "existing_tabs": existing}


def upsert_catalog_row(
    service: Any,
    spreadsheet_id: str,
    tab_name: str,
    headers: tuple[str, ...],
    values: list[Any],
    row_key: str,
) -> dict[str, Any]:
    """Create or update exactly one row, keyed by the immutable Drive asset ID.

    The header row is written only when the tab is empty. A row whose key
    already exists is updated in place; nothing is ever deleted or shifted.
    """
    try:
        from googleapiclient.errors import HttpError
    except ImportError as error:
        raise ExternalServiceError("Google Sheets dependency is not installed.") from error
    if len(values) != len(headers):
        raise ValidationError("Catalog row width must match the catalog header width.")
    if not row_key.strip():
        raise ValidationError("Catalog row key must be the non-empty immutable Drive asset ID.")
    last = column_letter(len(headers))
    span = f"{tab_name}!A:{last}"
    header_written = False
    try:
        existing = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"{tab_name}!A:A")
            .execute()
            .get("values", [])
        )
        if not existing:
            service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=span,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [list(headers)]},
            ).execute()
            header_written = True
        elif not existing[0] or existing[0][0] != "row_key":
            raise ValidationError(
                "Catalog sheet is missing the required row_key header in column A."
            )
        match = next(
            (index + 2 for index, row in enumerate(existing[1:]) if row and row[0] == row_key),
            None,
        )
        if match:
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{tab_name}!A{match}:{last}{match}",
                valueInputOption="RAW",
                body={"values": [values]},
            ).execute()
            outcome = "UPDATED"
        else:
            service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=span,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [values]},
            ).execute()
            outcome = "APPENDED"
    except HttpError as error:
        raise ExternalServiceError(f"Catalog publication failed: {error}") from error
    return {
        "outcome": outcome,
        "row_key": row_key,
        "tab_name": tab_name,
        "matched_row": match,
        "header_written": header_written,
    }
