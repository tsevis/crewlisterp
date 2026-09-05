"""Encrypted local persistence.

SQLCipher protects database pages; original documents are separately encrypted
so accidental copies outside the database remain unreadable.  The passphrase
is deliberately never stored by the application.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

try:  # The production installers always ship this dependency.
    from sqlcipher3 import dbapi2 as sqlcipher
except ImportError:  # pragma: no cover - makes the configuration error explicit.
    sqlcipher = None


class StorageUnavailable(RuntimeError):
    pass


class EncryptedStore:
    """A tiny typed-record store with encrypted originals and revisions."""

    def __init__(self, app_dir: Path, master_passphrase: str):
        if not master_passphrase:
            raise ValueError("A master passphrase is required.")
        if sqlcipher is None:
            raise StorageUnavailable(
                "SQLCipher is unavailable. Reinstall CrewListr Pro with its bundled dependencies."
            )
        self.app_dir = app_dir
        self.documents_dir = app_dir / "documents"
        self.revisions_dir = app_dir / "revisions"
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.documents_dir.mkdir(exist_ok=True)
        self.revisions_dir.mkdir(exist_ok=True)
        self._salt_path = self.app_dir / "salt.bin"
        salt = self._salt_path.read_bytes() if self._salt_path.exists() else os.urandom(16)
        if not self._salt_path.exists():
            self._salt_path.write_bytes(salt)
            os.chmod(self._salt_path, 0o600)
        key_material = hashlib.scrypt(
            master_passphrase.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=128 * 1024 * 1024
        )
        self._fernet = Fernet(base64.urlsafe_b64encode(key_material))
        self._conn = sqlcipher.connect(self.app_dir / "crewlisterpro.db")
        key_hex = key_material.hex()
        self._conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        # Memory hardening is off by default upstream, and the SQLCipher that
        # sqlcipher3 0.6 bundles (4.12.0) crashes on Windows with it enabled:
        # pytest died with "Windows fatal exception: stack overflow" on the
        # CREATE TABLE immediately below. SQLCipher 4.18.0 fixed a Windows
        # crash under this pragma, so drop the guard once sqlcipher3 ships a
        # build with 4.18.0 or later. Linux and macOS keep the hardening.
        if sys.platform != "win32":
            self._conn.execute("PRAGMA cipher_memory_security = ON")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS records (kind TEXT NOT NULL, id TEXT NOT NULL, payload BLOB NOT NULL, PRIMARY KEY(kind, id))"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def save(self, kind: str, record_id: str, payload: dict[str, Any]) -> None:
        token = self._fernet.encrypt(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        self._conn.execute(
            "INSERT INTO records(kind, id, payload) VALUES(?, ?, ?) ON CONFLICT(kind, id) DO UPDATE SET payload=excluded.payload",
            (kind, record_id, token),
        )
        self._conn.commit()

    def get(self, kind: str, record_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        return self._decode(row[0]) if row else None

    def list(self, kind: str) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT payload FROM records WHERE kind=? ORDER BY id", (kind,)).fetchall()
        return [self._decode(row[0]) for row in rows]

    def delete(self, kind: str, record_id: str) -> None:
        self._conn.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, record_id))
        self._conn.commit()

    def write_document(self, document_id: str, source: Path) -> tuple[str, str]:
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        destination = self.documents_dir / f"{document_id}.bin"
        destination.write_bytes(self._fernet.encrypt(raw))
        return str(destination), digest

    def read_document(self, encrypted_path: str) -> bytes:
        return self._fernet.decrypt(Path(encrypted_path).read_bytes())

    def write_revision(self, document_id: str, raw: bytes) -> str:
        revision = self.revisions_dir / f"{document_id}-{hashlib.sha256(raw).hexdigest()[:12]}.bin"
        revision.write_bytes(self._fernet.encrypt(raw))
        return str(revision)

    def overwrite_document(self, encrypted_path: str, raw: bytes) -> None:
        Path(encrypted_path).write_bytes(self._fernet.encrypt(raw))

    def delete_document(self, encrypted_path: str) -> None:
        Path(encrypted_path).unlink(missing_ok=True)

    def _decode(self, token: bytes) -> dict[str, Any]:
        decoded = json.loads(self._fernet.decrypt(token).decode("utf-8"))
        if not isinstance(decoded, dict):
            raise TypeError("Encrypted record was not an object.")
        return decoded
