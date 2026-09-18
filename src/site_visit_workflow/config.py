from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from .errors import ValidationError

DEPLOYED_SERVICE_ACCOUNT = "site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com"
# The historical "everything is an input" set. `CATALOG_SHEET_ID` is listed here
# for the commands that genuinely consume a pre-existing sheet
# (`publish-catalog`, `auth-preflight`). It is NO LONGER required by
# `process-folder`: that command can create its own catalog spreadsheet, so the
# sheet ID is an OUTPUT of the run there. See PROCESS_FOLDER_REQUIRED_SETTINGS
# and `assert_output_targets_resolvable` below.
ALL_REQUIRED_SETTINGS = (
    "GOOGLE_CLOUD_PROJECT",
    "DRIVE_SHARED_FOLDER_ID",
    "GCS_STAGING_BUCKET",
    "CATALOG_SHEET_ID",
)

# What `process-folder` actually needs before it may contact anything. The
# output files are resolved separately, because either a pre-known ID or a
# writable parent folder is a viable configuration.
PROCESS_FOLDER_REQUIRED_SETTINGS = (
    "GOOGLE_CLOUD_PROJECT",
    "DRIVE_SHARED_FOLDER_ID",
    "GCS_STAGING_BUCKET",
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


TRUTHY_ENVIRONMENT_VALUES = frozenset({"1", "true", "yes", "on"})


def _flag(name: str) -> bool:
    """Read one boolean env flag. Anything not explicitly truthy stays False.

    Boundary: this is deliberately strict rather than "anything non-empty is
    true". `RENAME_APPROVED=no` must not authorize a rename of the operator's
    source library.
    """
    return os.environ.get(name, "").strip().lower() in TRUTHY_ENVIRONMENT_VALUES


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
    # Self-provisioned outputs. `catalog_sheet_id` and `report_doc_id` are now
    # OPTIONAL inputs: when either is empty the run creates that file in
    # `drive_output_parent_id` and the resulting id becomes an OUTPUT of the
    # run, surfaced in the run summary. See `google.ensure_catalog_spreadsheet`.
    report_doc_id: str = ""
    drive_output_parent_id: str = ""
    # Gate 6 belt and braces: the env flag alone never authorizes a rename; the
    # CLI must also be given --rename-approved.
    rename_approved: bool = False

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
            report_doc_id=os.environ.get("REPORT_DOC_ID", "").strip(),
            drive_output_parent_id=(
                os.environ.get("DRIVE_OUTPUT_PARENT_ID", "").strip()
                or os.environ.get("DRIVE_SHARED_FOLDER_ID", "").strip()
            ),
            rename_approved=_flag("RENAME_APPROVED"),
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


def assert_output_targets_resolvable(settings: Settings, report_requested: bool) -> None:
    """Fail loudly when neither a pre-known output ID nor a creatable parent exists.

    Dropping `CATALOG_SHEET_ID` from the required set must not weaken the run
    into silently writing nowhere. Exactly one of two configurations is valid
    per output file: an explicit ID, or a Drive parent folder the run can
    create the file in. Anything else is a misconfiguration and stops the run
    before a single asset is processed.
    """
    if not settings.catalog_sheet_id and not settings.drive_output_parent_id:
        raise ValidationError(
            "No catalog target: set CATALOG_SHEET_ID, or set DRIVE_OUTPUT_PARENT_ID "
            "(or DRIVE_SHARED_FOLDER_ID) so the run can create its own catalog spreadsheet."
        )
    if report_requested and not settings.report_doc_id and not settings.drive_output_parent_id:
        raise ValidationError(
            "No report target: set REPORT_DOC_ID, or set DRIVE_OUTPUT_PARENT_ID "
            "(or DRIVE_SHARED_FOLDER_ID) so the run can create its own report document."
        )
