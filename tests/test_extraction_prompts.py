"""Prompt files are read at runtime, so the loader is tested against the real files.

No test here contacts Vertex. They cover the file contract, the prompt/validator
drift guard, and the empty-transcript stop.
"""

from pathlib import Path

import pytest

from site_visit_workflow.config import (
    DEFAULT_CATALOG_TAB_NAME,
    DEFAULT_SPEECH_MODEL,
    Settings,
)
from site_visit_workflow.errors import ValidationError
from site_visit_workflow.extraction import (
    LAYER_FIELDS,
    PROMPT_FILES,
    RESPONSE_SCHEMAS,
    assert_prompt_schema_matches,
    load_prompt_file,
    transcript_is_processable,
)

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


@pytest.mark.parametrize("layer", sorted(PROMPT_FILES))
def test_every_governed_prompt_file_loads_and_declares_a_version(layer: str) -> None:
    prompt = load_prompt_file(layer, PROMPTS_DIR)

    assert prompt.version
    assert prompt.instruction_text.strip()
    assert len(prompt.sha256) == 64
    assert prompt.evidence()["prompt_file"].endswith(PROMPT_FILES[layer])


@pytest.mark.parametrize("layer", sorted(PROMPT_FILES))
def test_prompt_file_schema_matches_the_validator_for_every_layer(layer: str) -> None:
    prompt = load_prompt_file(layer, PROMPTS_DIR)

    assert set(prompt.declared_schema_keys) == set(LAYER_FIELDS[layer])
    assert_prompt_schema_matches(prompt)


@pytest.mark.parametrize("layer", sorted(PROMPT_FILES))
def test_wire_response_schema_covers_exactly_the_governed_keys(layer: str) -> None:
    schema = RESPONSE_SCHEMAS[layer]

    assert set(schema["properties"]) == set(LAYER_FIELDS[layer])
    assert set(schema["required"]) == set(LAYER_FIELDS[layer])


def test_a_missing_prompt_file_is_a_clear_runtime_stop(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="missing at runtime"):
        load_prompt_file("L2", tmp_path)


def test_prompt_schema_drift_is_reported_rather_than_tolerated(tmp_path: Path) -> None:
    source = (PROMPTS_DIR / PROMPT_FILES["L1"]).read_text(encoding="utf-8")
    drifted = source.replace('"confidence_note":"string"}', '"confidence_note":"string","priority":"string"}')
    (tmp_path / PROMPT_FILES["L1"]).write_text(drifted, encoding="utf-8")

    prompt = load_prompt_file("L1", tmp_path)
    with pytest.raises(ValidationError, match="drifted"):
        assert_prompt_schema_matches(prompt)


@pytest.mark.parametrize("transcript", ["", "   ", "\n", "a"])
def test_an_empty_or_near_empty_transcript_never_reaches_l1(transcript: str) -> None:
    assert transcript_is_processable(transcript) is False


def test_a_real_transcript_is_processable() -> None:
    assert transcript_is_processable("Downspout is detached at the elbow.") is True


def test_new_location_and_model_settings_have_the_documented_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("SPEECH_LOCATION", "VERTEX_LOCATION", "VERTEX_MODEL", "CATALOG_TAB_NAME", "RUN_ID", "SPEECH_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "shir-sitevisit")
    monkeypatch.setenv("DRIVE_SHARED_FOLDER_ID", "folder")

    settings = Settings.from_environment(required=("GOOGLE_CLOUD_PROJECT", "DRIVE_SHARED_FOLDER_ID"))

    assert settings.region == "us-central1"
    assert settings.speech_location == "us"
    assert settings.speech_model == DEFAULT_SPEECH_MODEL == "chirp_3"
    assert settings.vertex_location == "us-central1"
    assert settings.vertex_model == "gemini-2.5-flash"
    assert settings.catalog_tab_name == DEFAULT_CATALOG_TAB_NAME == "Catalog"
    assert settings.run_id.endswith("Z") and len(settings.run_id) == 16


def test_the_legacy_chirp_alias_is_rejected_not_silently_remapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "shir-sitevisit")
    monkeypatch.setenv("DRIVE_SHARED_FOLDER_ID", "folder")
    monkeypatch.setenv("SPEECH_MODEL", "chirp")

    with pytest.raises(ValidationError, match="legacy alias"):
        Settings.from_environment(required=("GOOGLE_CLOUD_PROJECT", "DRIVE_SHARED_FOLDER_ID"))


def test_run_id_is_honoured_when_supplied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "shir-sitevisit")
    monkeypatch.setenv("DRIVE_SHARED_FOLDER_ID", "folder")
    monkeypatch.setenv("RUN_ID", "20260917T055321Z")

    settings = Settings.from_environment(required=("GOOGLE_CLOUD_PROJECT", "DRIVE_SHARED_FOLDER_ID"))

    assert settings.run_id == "20260917T055321Z"


def test_gcs_prefixes_are_run_scoped_and_carry_the_asset_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from site_visit_workflow.google import asset_prefix, speech_output_prefix, wav_object_name

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "shir-sitevisit")
    monkeypatch.setenv("DRIVE_SHARED_FOLDER_ID", "folder")
    monkeypatch.setenv("GCS_STAGING_PREFIX", "site-visit-staging")
    monkeypatch.setenv("RUN_ID", "20260917T055321Z")
    settings = Settings.from_environment(required=("GOOGLE_CLOUD_PROJECT", "DRIVE_SHARED_FOLDER_ID"))

    assert asset_prefix(settings, "asset-1") == "site-visit-staging/20260917T055321Z/asset-1"
    assert wav_object_name(settings, "asset-1", 0).endswith("audio/attempt-0/asset-1.wav")
    assert speech_output_prefix(settings, "asset-1", 1).endswith("speech-output/attempt-1/")
    with pytest.raises(ValidationError):
        wav_object_name(settings, "asset-1", 2)


def test_l2_prompt_separates_already_tracked_from_no_finding() -> None:
    """l2 1.2.0: "I already have a task for that" is ALREADY_TRACKED, never NO_FINDING."""
    from site_visit_workflow.extraction import L2_RESPONSE_SCHEMA, load_prompt_file

    prompt = load_prompt_file("L2", Path(__file__).resolve().parents[1] / "prompts")
    assert prompt.version == "1.2.0"
    assert "ALREADY_TRACKED" in prompt.instruction_text
    assert "never a reason for\nNO_FINDING" in prompt.instruction_text
    assert "ALREADY_TRACKED" in L2_RESPONSE_SCHEMA["properties"]["enrichment_status"]["enum"]


def _l2_inputs():
    from types import SimpleNamespace

    from site_visit_workflow.extraction import LayerResult
    from site_visit_workflow.models import L1Extraction

    l1 = L1Extraction("asset-1", "Unit 4B", "Leak under sink", "unit_4b_leak", "clear")
    l1_result = LayerResult("L1", "asset-1", "L1-rec-1", "p", "1", "h", "m", "s", {}, "", {}, True, "t0", "t1")
    settings = SimpleNamespace(vertex_model="gemini-2.5-flash")
    good = ('{"source_asset_identifier":"asset-1","prior_layer":"L1","prior_layer_record_id":"L1-rec-1",'
            '"enrichment_status":"ENRICHED","trade":"plumbing","area_type":"unit","severity":2,'
            '"recommended_action":"Fix the leak","enrichment_note":"Leak stated."}')
    bad = good.replace("L1-rec-1", "L1-rec-l")  # the observed mis-copy
    return l1, l1_result, settings, good, bad


def test_l2_recovers_from_repeated_record_id_mis_copies(monkeypatch: pytest.MonkeyPatch) -> None:
    from site_visit_workflow import extraction as ex

    l1, l1_result, settings, good, bad = _l2_inputs()
    answers = iter([bad, bad, bad, good])
    monkeypatch.setattr(ex, "_generate", lambda *a, **k: (next(answers), {}))
    _result, enrichment = ex.run_l2(None, settings, Path(__file__).resolve().parents[1] / "prompts",
                                    "asset-1", l1_result, l1, "There is a leak under the sink in unit 4B.")
    assert enrichment.enrichment_status == "ENRICHED"
    assert ex.L2_VALIDATION_ATTEMPTS == 4


def test_l2_raises_after_the_last_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    from site_visit_workflow import extraction as ex

    l1, l1_result, settings, _good, bad = _l2_inputs()
    calls = []
    monkeypatch.setattr(ex, "_generate", lambda *a, **k: (calls.append(1) or bad, {}))
    with pytest.raises(ValidationError, match="prior_layer_record_id"):
        ex.run_l2(None, settings, Path(__file__).resolve().parents[1] / "prompts",
                  "asset-1", l1_result, l1, "There is a leak under the sink in unit 4B.")
    assert len(calls) == ex.L2_VALIDATION_ATTEMPTS
