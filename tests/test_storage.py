from pathlib import Path

import pytest

pytest.importorskip("sqlcipher3")

from crewlisterpro.storage import EncryptedStore


def test_sqlcipher_and_payload_encryption_hide_plaintext(tmp_path: Path) -> None:
    store = EncryptedStore(tmp_path, "test-only-passphrase")
    store.save("person", "person-1", {"name": "PRIVATE TEST"})
    assert store.get("person", "person-1") == {"name": "PRIVATE TEST"}
    store.close()
    assert b"PRIVATE TEST" not in (tmp_path / "crewlisterpro.db").read_bytes()


def test_existing_encrypted_store_reopens_without_data_migration(tmp_path: Path) -> None:
    first = EncryptedStore(tmp_path, "test-only-passphrase")
    first.save("trip", "trip-1", {"status": "draft"})
    first.close()
    reopened = EncryptedStore(tmp_path, "test-only-passphrase")
    assert reopened.get("trip", "trip-1") == {"status": "draft"}
    reopened.close()
