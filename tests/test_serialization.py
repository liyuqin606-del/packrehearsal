from __future__ import annotations

import os
from pathlib import Path

import pytest

from packrehearsal.serialization import atomic_write_text


def test_atomic_write_replaces_regular_file(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.write_text("old", encoding="utf-8")
    atomic_write_text(target, "new\n", mode=0o600)
    assert target.read_text(encoding="utf-8") == "new\n"
    assert target.is_file()
    assert not target.is_symlink()
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600


def test_atomic_write_refuses_existing_symlink_without_touching_victim(tmp_path: Path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    target = tmp_path / "report.json"
    target.symlink_to(victim)
    with pytest.raises(ValueError, match="symlink"):
        atomic_write_text(target, "replace")
    assert victim.read_text(encoding="utf-8") == "keep"
    assert target.is_symlink()


def test_atomic_write_refuses_broken_symlink(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError, match="symlink"):
        atomic_write_text(target, "replace")
    assert target.is_symlink()
