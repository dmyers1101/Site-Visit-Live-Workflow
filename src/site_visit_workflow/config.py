from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from .errors import ValidationError

DEPLOYED_SERVICE_ACCOUNT = "site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com"
ALL_REQUIRED_SETTINGS = (
    "GOOGLE_CLOUD_PROJECT",
    "DRIVE_SHARED_FOLDER_ID",
    "GCS_STAGING_BUCKET",
    "CATALOG_SHEET_ID",
)


DEFAULT_CATALOG_TAB_NAME = "Catalog"
DEFAULT_SPEECH_MODEL = "chirp_3"
# `chirp` is a legacy alias that appears in .env.example and in pilot notes. The
# Speech-to-Text v2 API does not accept it, so it is rejected loudly here rather
# than silently rewritten - a silent mapping would hide the next such drift.
REJECTED_SPEECH_MODEL_ALIASES = {"chirp": DEFAULT_SPEECH_MODEL}


def _speech_model() -> str:
    """Resolve SPEECH_MODEL, refusing the legacy `chirp` alias instead of mapping it."""
    value = os.environ.get("SPEECH_MODEL", "").strip() or DEFAULT_SPEECH_MODEL
    if value in REJECTED_SPEECH_MODEL_ALIASES:
        raise ValidationError(
            f"SPEECH_MODEL={value!r} is a legacy alias the Speech-to-Text v2 API rejects. "
            f"Set SPEECH_MODEL={REJECTED_SPEECH_MODEL_ALIASES[value]!r} explicitly. "
            "Note that TRANSCRIPTION_MODEL in .env.example is a non-authoritative alias "
            "and is not read by this package."
        )
    return value


def default_run_id() -> str:
    """One compact UTC stamp per job execution; also the GCS evidence prefix segment."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@dataclass(frozen=True)
class Settings:
    project_id: str
    region: str
    drive_shared_folder_id: str
    gcs_staging_bucket: str
    gcs_staging_prefix: str
    catalog_sheet_id: str
    runtime_service_account: str
    environment: str
    # Boundary: `region` stays the Cloud Run / general Google region. Speech and
    # Vertex resolve their own locations because Chirp 3 is served only from the
    # `us` and `eu` multi-regions, not from us-central1.
    speech_location: str = "us"
    speech_model: str = DEFAULT_SPEECH_MODEL
    vertex_location: str = "us-central1"
    vertex_model: str = "gemini-2.5-flash"
    catalog_tab_name: str = DEFAULT_CATALOG_TAB_NAME
    run_id: str = ""

    @classmethod
    def from_environment(
        cls, required: tuple[str, ...] = ALL_REQUIRED_SETTINGS
    ) -> "Settings":
        missing = [name for name in required if not os.environ.get(name, "").strip()]
        if missing:
            raise ValidationError("Missing required configuration: " + ", ".join(missing))
        settings = cls(
            project_id=os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip(),
            region=os.environ.get("GOOGLE_CLOUD_REGION", "us-central1").strip(),
            drive_shared_folder_id=os.environ.get("DRIVE_SHARED_FOLDER_ID", "").strip(),
            gcs_staging_bucket=os.environ.get("GCS_STAGING_BUCKET", "").strip(),
            gcs_staging_prefix=os.environ.get("GCS_STAGING_PREFIX", "site-visit-staging").strip("/"),
            catalog_sheet_id=os.environ.get("CATALOG_SHEET_ID", "").strip(),
            runtime_service_account=os.environ.get(
                "SITE_VISIT_RUNTIME_SERVICE_ACCOUNT", DEPLOYED_SERVICE_ACCOUNT
            ).strip(),
            environment=os.environ.get("SITE_VISIT_ENVIRONMENT", "local").strip().lower(),
            speech_location=os.environ.get("SPEECH_LOCATION", "us").strip() or "us",
            speech_model=_speech_model(),
            vertex_location=os.environ.get("VERTEX_LOCATION", "us-central1").strip() or "us-central1",
            vertex_model=os.environ.get("VERTEX_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash",
            catalog_tab_name=os.environ.get("CATALOG_TAB_NAME", DEFAULT_CATALOG_TAB_NAME).strip()
            or DEFAULT_CATALOG_TAB_NAME,
            run_id=os.environ.get("RUN_ID", "").strip() or default_run_id(),
        )
        if settings.environment == "deployed" and settings.runtime_service_account != DEPLOYED_SERVICE_ACCOUNT:
            raise ValidationError(
                "Deployed runtime must use the designated site-visit-workflow service account."
            )
        return settings


def gcs_uri(bucket: str, object_name: str) -> str:
    if not bucket or "/" in bucket:
        raise ValidationError("GCS bucket must be a bucket name, without gs:// or a path.")
    if not object_name.strip() or object_name.startswith("/"):
        raise ValidationError("GCS object name must be a non-empty relative path.")
    return f"gs://{bucket}/{object_name}"
