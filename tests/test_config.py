import pytest

from site_visit_workflow.config import DEPLOYED_SERVICE_ACCOUNT, Settings
from site_visit_workflow.errors import ValidationError


def test_deployed_mode_requires_designated_service_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project")
    monkeypatch.setenv("DRIVE_SHARED_FOLDER_ID", "folder")
    monkeypatch.setenv("GCS_STAGING_BUCKET", "bucket")
    monkeypatch.setenv("CATALOG_SHEET_ID", "sheet")
    monkeypatch.setenv("SITE_VISIT_ENVIRONMENT", "deployed")
    monkeypatch.setenv("SITE_VISIT_RUNTIME_SERVICE_ACCOUNT", "other@example.com")
    with pytest.raises(ValidationError, match="designated"):
        Settings.from_environment()


def test_deployed_mode_accepts_designated_service_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project")
    monkeypatch.setenv("DRIVE_SHARED_FOLDER_ID", "folder")
    monkeypatch.setenv("GCS_STAGING_BUCKET", "bucket")
    monkeypatch.setenv("CATALOG_SHEET_ID", "sheet")
    monkeypatch.setenv("SITE_VISIT_ENVIRONMENT", "deployed")
    monkeypatch.setenv("SITE_VISIT_RUNTIME_SERVICE_ACCOUNT", DEPLOYED_SERVICE_ACCOUNT)
    assert Settings.from_environment().runtime_service_account == DEPLOYED_SERVICE_ACCOUNT


def test_drive_intake_can_validate_without_later_stage_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project")
    monkeypatch.setenv("DRIVE_SHARED_FOLDER_ID", "folder")

    settings = Settings.from_environment(
        required=("GOOGLE_CLOUD_PROJECT", "DRIVE_SHARED_FOLDER_ID")
    )

    assert settings.drive_shared_folder_id == "folder"
    assert settings.gcs_staging_bucket == ""
    assert settings.catalog_sheet_id == ""
