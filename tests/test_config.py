from __future__ import annotations

from pathlib import Path

import pytest

from grokko.config import GrokExportConfig, GrokSessionConfig


def test_session_config_paths_and_storage_dir(tmp_path: Path) -> None:
    config = GrokSessionConfig(storage_dir=tmp_path)

    assert config.profile_dir == tmp_path / ".grok_profile"
    assert config.state_file == tmp_path / "auth.json"

    config.ensure_storage_dir()
    assert tmp_path.exists()


def test_export_config_validate_requires_credentials() -> None:
    config = GrokExportConfig(imap_user="", imap_password="")

    with pytest.raises(OSError, match="IMAP_USER, IMAP_PASSWORD"):
        config.validate()


def test_export_config_validate_succeeds_with_credentials() -> None:
    config = GrokExportConfig(imap_user="user@example.com", imap_password="secret")

    config.validate()
