from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from packrehearsal.baseline import (
    create_baseline,
    load_baseline,
    partition_findings,
    save_baseline,
)
from packrehearsal.exceptions import ReceiptVerificationError
from packrehearsal.models import ArtifactSnapshot, Finding, ScanReport, Severity
from packrehearsal.receipt import create_receipt, load_receipt, save_receipt, verify_receipt
from packrehearsal.serialization import canonical_json


def _rehash_receipt(receipt: dict[str, object]) -> None:
    receipt["receipt_id"] = hashlib.sha256(
        canonical_json(
            {key: value for key, value in receipt.items() if key != "receipt_id"}
        ).encode()
    ).hexdigest()


def _report(artifact: Path | None = None) -> ScanReport:
    finding = Finding(
        rule_id="common-license-missing",
        severity=Severity.MEDIUM,
        title="License missing",
        message="No license reached the artifact.",
        remediation="Include a license file.",
        location="LICENSE",
    )
    artifacts = ()
    if artifact is not None:
        content = artifact.read_bytes()
        artifacts = (
            ArtifactSnapshot(
                path=artifact.name,
                format="zip",
                sha256=hashlib.sha256(content).hexdigest(),
                size=len(content),
                entries=(),
            ),
        )
    return ScanReport(root=".", packages=(), findings=(finding,), artifacts=artifacts)


def test_baseline_round_trip(tmp_path: Path) -> None:
    report = _report()
    path = tmp_path / "baseline.json"
    save_baseline(path, report)
    assert load_baseline(path) == (report.findings[0].fingerprint,)
    assert create_baseline(report)["report_scan_id"] == report.scan_id


def test_baseline_rejects_duplicate_or_invalid_fingerprints(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(
        canonical_json(
            {
                "schema_version": "1",
                "entries": [{"fingerprint": "not-a-fingerprint"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid fingerprint"):
        load_baseline(path)


def test_baseline_rejects_wrong_shapes_and_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    cases = (
        ([], "root must be an object"),
        ({"schema_version": "99", "entries": []}, "unsupported baseline schema"),
        ({"schema_version": "1", "entries": {}}, "entries must be an array"),
        ({"schema_version": "1", "entries": ["bad"]}, "entry 0 must be an object"),
        (
            {
                "schema_version": "1",
                "entries": [{"fingerprint": "a" * 24}, {"fingerprint": "a" * 24}],
            },
            "duplicate fingerprints",
        ),
    )
    for payload, message in cases:
        path.write_text(canonical_json(payload), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            load_baseline(path)


def test_partition_findings_and_new_only_baseline() -> None:
    report = _report()
    finding = report.findings[0]
    new, known = partition_findings(report.findings, (finding.fingerprint,))
    assert new == ()
    assert known == (finding,)
    assert create_baseline(report, include_all=False)["entries"][0]["fingerprint"] == (
        finding.fingerprint
    )


def test_receipt_verifies_content_report_and_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "demo.whl"
    artifact.write_bytes(b"candidate bytes")
    report = _report(artifact)
    receipt = create_receipt(report, repository_commit="abc123", created_at="2026-01-01T00:00:00Z")
    path = tmp_path / "receipt.json"
    save_receipt(path, receipt)

    loaded = load_receipt(path)
    checks = verify_receipt(loaded, report=report, artifact_root=tmp_path)
    assert checks == ("receipt content hash", "report hash", "1 artifact hash(es)")


def test_receipt_detects_tampering(tmp_path: Path) -> None:
    artifact = tmp_path / "demo.whl"
    artifact.write_bytes(b"candidate bytes")
    report = _report(artifact)
    receipt = create_receipt(report, created_at="2026-01-01T00:00:00Z")
    receipt["finding_counts"]["high"] = 99
    with pytest.raises(ReceiptVerificationError, match="receipt_id"):
        verify_receipt(receipt)


def test_receipt_rejects_artifact_path_escape(tmp_path: Path) -> None:
    report = ScanReport(
        root=".",
        packages=(),
        findings=(),
        artifacts=(ArtifactSnapshot("../secret", "zip", "0" * 64, 1, ()),),
    )
    with pytest.raises(ReceiptVerificationError, match="escapes verification root"):
        create_receipt(report, created_at="2026-01-01T00:00:00Z")


def test_receipt_rejects_symlinked_artifact_and_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside.whl"
    outside.write_bytes(b"candidate bytes")
    direct_link = tmp_path / "linked.whl"
    direct_link.symlink_to(outside)
    direct_report = _report(outside)
    direct_receipt = create_receipt(direct_report, created_at="2026-01-01T00:00:00Z")
    direct_receipt["artifacts"][0]["path"] = direct_link.name
    _rehash_receipt(direct_receipt)
    with pytest.raises(ReceiptVerificationError, match="regular file"):
        verify_receipt(direct_receipt, artifact_root=tmp_path)

    real_directory = tmp_path / "real"
    real_directory.mkdir()
    nested = real_directory / "nested.whl"
    nested.write_bytes(b"candidate bytes")
    directory_link = tmp_path / "linked-dir"
    directory_link.symlink_to(real_directory, target_is_directory=True)
    nested_report = _report(nested)
    nested_receipt = create_receipt(nested_report, created_at="2026-01-01T00:00:00Z")
    nested_receipt["artifacts"][0]["path"] = "linked-dir/nested.whl"
    _rehash_receipt(nested_receipt)
    with pytest.raises(ReceiptVerificationError, match="regular file"):
        verify_receipt(nested_receipt, artifact_root=tmp_path)


@pytest.mark.parametrize("path", ("/absolute.whl", "a\\b.whl", "./demo.whl", "a//b.whl"))
def test_receipt_rejects_noncanonical_artifact_paths(tmp_path: Path, path: str) -> None:
    report = ScanReport(
        root=".",
        packages=(),
        findings=(),
        artifacts=(ArtifactSnapshot(path, "zip", "0" * 64, 1, ()),),
    )
    with pytest.raises(ReceiptVerificationError, match="escapes verification root"):
        create_receipt(report, created_at="2026-01-01T00:00:00Z")


def test_receipt_requires_complete_v1_shape() -> None:
    minimal: dict[str, object] = {"schema_version": "1"}
    _rehash_receipt(minimal)
    with pytest.raises(ReceiptVerificationError, match="missing fields"):
        verify_receipt(minimal)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("created_at", "not-a-date", "created_at"),
        ("tool", "other", "invalid tool"),
        ("report_sha256", "short", "report_sha256"),
    ),
)
def test_receipt_rejects_invalid_scalar_shape(field: str, value: object, message: str) -> None:
    receipt = create_receipt(_report(), created_at="2026-01-01T00:00:00Z")
    receipt[field] = value
    _rehash_receipt(receipt)
    with pytest.raises(ReceiptVerificationError, match=message):
        verify_receipt(receipt)


def test_receipt_rejects_non_integer_artifact_size(tmp_path: Path) -> None:
    artifact = tmp_path / "demo.whl"
    artifact.write_bytes(b"candidate bytes")
    receipt = create_receipt(_report(artifact), created_at="2026-01-01T00:00:00Z")
    receipt["artifacts"][0]["size"] = "15"
    _rehash_receipt(receipt)
    with pytest.raises(ReceiptVerificationError, match="artifact size"):
        verify_receipt(receipt)


def test_receipt_rejects_schema_report_and_artifact_mismatches(tmp_path: Path) -> None:
    report = _report()
    receipt = create_receipt(report, created_at="2026-01-01T00:00:00Z")
    with pytest.raises(ReceiptVerificationError, match="unsupported receipt schema"):
        verify_receipt({**receipt, "schema_version": "99"})
    with pytest.raises(ReceiptVerificationError, match="does not match"):
        verify_receipt(receipt, report=ScanReport(root="other", packages=(), findings=()))

    artifact = tmp_path / "candidate.whl"
    artifact.write_bytes(b"content")
    artifact_report = _report(artifact)
    artifact_receipt = create_receipt(artifact_report, created_at="2026-01-01T00:00:00Z")
    artifact.write_bytes(b"changed-size")
    with pytest.raises(ReceiptVerificationError, match="size mismatch"):
        verify_receipt(artifact_receipt, artifact_root=tmp_path)


def test_receipt_timestamp_honors_source_date_epoch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    assert create_receipt(_report())["created_at"] == "1970-01-01T00:00:00Z"
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "invalid")
    with pytest.raises(ValueError, match="valid Unix timestamp"):
        create_receipt(_report())
