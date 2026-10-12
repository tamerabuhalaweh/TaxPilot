"""Migration-manifest unit tests: no database required (checksum verification
happens before any connection), so these run everywhere including plain CI."""

import pytest
from db.migrate import discover, load_checksums, migrate


def test_manifest_covers_all_versions():
    manifest = load_checksums()
    assert set(manifest) >= {"0001", "0002", "0003", "0004"}
    discovered = {p.stem.split("_")[0] for p in discover()}
    assert set(manifest) >= discovered


def test_checksum_tampering_detected_before_connect(tmp_path):  # type: ignore[no-untyped-def]
    (tmp_path / "0009_probe.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "CHECKSUMS").write_text("0009  " + "0" * 64 + "  0009_probe.sql\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        # Unreachable DB proves the checksum gate fires before any connection.
        migrate("postgresql://u:p@127.0.0.1:9/db", versions_dir=tmp_path)


def test_missing_manifest_fails_closed(tmp_path):  # type: ignore[no-untyped-def]
    (tmp_path / "0009_probe.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(ValueError, match="CHECKSUMS manifest missing"):
        migrate("postgresql://u:p@127.0.0.1:9/db", versions_dir=tmp_path)


def test_missing_checksum_entry_fails_closed(tmp_path):  # type: ignore[no-untyped-def]
    (tmp_path / "0009_probe.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "CHECKSUMS").write_text("0008  " + "0" * 64 + "  0008_other.sql\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no CHECKSUMS entry"):
        migrate("postgresql://u:p@127.0.0.1:9/db", versions_dir=tmp_path)
