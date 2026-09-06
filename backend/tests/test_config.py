from pathlib import Path

import pytest
from pydantic import ValidationError

from timeline_api.config import LogLevel, Settings


def test_settings_load_prefixed_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TIMELINE_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("TIMELINE_POSTGRES_POOL_MAX_SIZE", "4")
    monkeypatch.setenv("TIMELINE_REGISTRY_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("TIMELINE_PACS_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("TIMELINE_VITALS_TIMEOUT_SECONDS", "3.5")

    settings = Settings()

    assert settings.log_level is LogLevel.WARNING
    assert settings.postgres_pool_max_size == 4
    assert settings.registry_timeout_seconds == 1.5
    assert settings.pacs_timeout_seconds == 2.5
    assert settings.vitals_timeout_seconds == 3.5


def test_settings_reject_invalid_pool_size(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TIMELINE_POSTGRES_POOL_MAX_SIZE", "0")

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "environment_name",
    [
        "TIMELINE_REGISTRY_TIMEOUT_SECONDS",
        "TIMELINE_PACS_TIMEOUT_SECONDS",
        "TIMELINE_VITALS_TIMEOUT_SECONDS",
    ],
)
def test_settings_reject_non_positive_adapter_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    environment_name: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(environment_name, "0")

    with pytest.raises(ValidationError):
        Settings()
