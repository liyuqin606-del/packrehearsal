from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from packrehearsal.config import (
    MAX_ARCHIVE_BYTES,
    ArchiveLimits,
    Config,
    config_from_mapping,
    default_config_dict,
    load_config,
)
from packrehearsal.exceptions import ConfigurationError
from packrehearsal.models import Severity


def test_default_config_is_conservative() -> None:
    config = Config()
    assert not config.allow_network
    assert not config.include_hidden
    assert config.fail_on is Severity.HIGH
    assert config.archive.max_entries == 20_000
    assert "node_modules/**" in config.exclude


def test_config_loader_rejects_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / ".packrehearsal.json"
    path.write_text('{"fail_onn": "high"}', encoding="utf-8")
    with pytest.raises(ConfigurationError, match="unknown configuration keys"):
        load_config(tmp_path)


def test_config_loader_parses_rules_and_limits(tmp_path: Path) -> None:
    path = tmp_path / ".packrehearsal.json"
    path.write_text(
        json.dumps(
            {
                "archive": {"max_entries": 42},
                "disabled_rules": ["common-readme-missing"],
                "fail_on": "medium",
                "severity_overrides": {"common-license-missing": "critical"},
            }
        ),
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.archive.max_entries == 42
    assert config.fail_on is Severity.MEDIUM
    assert not config.rule_enabled("common-readme-missing")
    assert config.severity_for("common-license-missing", Severity.LOW) is Severity.CRITICAL


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"allow_network": "no"}, "must be a boolean"),
        ({"max_depth": True}, "must be an integer"),
        ({"enabled_rules": ["a"], "disabled_rules": ["a"]}, "both enabled and disabled"),
        ({"archive": {"max_compression_ratio": 0.5}}, "at least 1"),
        ({"archive": {"max_entries": 1.5}}, "must be integers"),
        ({"archive": {"max_compression_ratio": True}}, "must be a number"),
    ],
)
def test_invalid_config_is_rejected(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        config_from_mapping(payload)


def test_default_config_round_trips() -> None:
    config = config_from_mapping(default_config_dict())
    assert config == Config()


def test_repository_config_can_tighten_but_not_raise_archive_ceiling() -> None:
    assert ArchiveLimits(max_archive_bytes=1024).max_archive_bytes == 1024
    with pytest.raises(ConfigurationError, match="only tighten"):
        ArchiveLimits(max_archive_bytes=MAX_ARCHIVE_BYTES + 1)


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_archive_compression_ratio_must_be_finite(value: float) -> None:
    with pytest.raises(ConfigurationError, match="must be finite"):
        ArchiveLimits(max_compression_ratio=value)


def test_config_json_rejects_non_finite_numbers(tmp_path: Path) -> None:
    path = tmp_path / ".packrehearsal.json"
    path.write_text('{"archive":{"max_compression_ratio":NaN}}', encoding="utf-8")
    with pytest.raises(ConfigurationError, match="non-finite JSON number"):
        load_config(tmp_path)
