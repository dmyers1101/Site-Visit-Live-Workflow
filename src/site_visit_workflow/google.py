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
                fields="nextPageToken,files(id,name,mimeType,webViewLink,size,modifiedTime)",
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


def submit_transcription(
    settings: Settings, wav_path: Path, asset_id: str, attempt: int, object_name: str
) -> TranscriptionRecord:
    """Explicitly upload one WAV and submit one Chirp BatchRecognize operation."""
    if attempt not in (0, 1):
        raise ValidationError("Only attempts 0 and 1 are permitted.")
    if not wav_path.is_file():
        raise ValidationError(f"WAV input does not exist: {wav_path}")
    if not object_name.endswith(".wav") or asset_id not in object_name:
        raise ValidationError("GCS object must be a clearly named .wav path containing the Drive asset ID.")
    try:
        from google.api_core.exceptions import GoogleAPICallError
        from google.cloud import speech_v2, storage
        from google.cloud.speech_v2.types import cloud_speech
    except ImportError as error:
        raise ExternalServiceError("Speech and Storage dependencies are not installed.") from error

    credentials = runtime_credentials(settings)
    wav_uri = gcs_uri(settings.gcs_staging_bucket, object_name)
    output_uri = gcs_uri(
        settings.gcs_staging_bucket,
        f"{settings.gcs_staging_prefix}/speech-output/{asset_id}/attempt-{attempt}/",
    )
    try:
        bucket = storage.Client(project=settings.project_id, credentials=credentials).bucket(
            settings.gcs_staging_bucket
        )
        bucket.blob(object_name).upload_from_filename(str(wav_path), content_type="audio/wav")
        client = speech_v2.SpeechClient(credentials=credentials)
        recognizer = f"projects/{settings.project_id}/locations/{settings.region}/recognizers/_"
        operation = client.batch_recognize(
            request=cloud_speech.BatchRecognizeRequest(
                recognizer=recognizer,
                config=cloud_speech.RecognitionConfig(
                    auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
                    language_codes=["en-US"],
                    model="chirp_3",
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
