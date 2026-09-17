from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import ValidationError

DEPLOYED_SERVICE_ACCOUNT = "site-visit-workflow@shir-sitevisit.iam.gserviceaccount.com"
ALL_REQUIRED_SETTINGS = (
    "GOOGLE_CLOUD_PROJECT",
    "DRIVE_SHARED_FOLDER_ID",
    "GCS_STAGING_BUCKET",
    "CATALOG_SHEET_ID",
)


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
