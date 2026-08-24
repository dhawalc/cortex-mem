from pathlib import Path

from aoms.settings import AOMSSettings


def test_data_dir_env_override(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "portable-data"
    monkeypatch.setenv("AOMS_DATA_DIR", str(target))

    settings = AOMSSettings.load()

    assert settings.data_dir == target
    assert settings.db_path == target / "aoms.sqlite3"
    assert settings.db_path.is_relative_to(settings.data_dir)


def test_platform_default_is_used(monkeypatch, tmp_path: Path) -> None:
    default = tmp_path / "platform-data"
    monkeypatch.delenv("AOMS_DATA_DIR", raising=False)
    monkeypatch.setattr("aoms.settings._platform_data_dir", lambda: default)

    settings = AOMSSettings.load()

    assert settings.data_dir == default
    assert settings.db_path == default / "aoms.sqlite3"


def test_explicit_environment_mapping_does_not_read_process_env(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AOMS_DATA_DIR", str(tmp_path / "ignored"))

    settings = AOMSSettings.load(environ={"AOMS_DATA_DIR": str(tmp_path / "selected")})

    assert settings.data_dir == tmp_path / "selected"
