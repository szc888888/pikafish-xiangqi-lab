import base64
import os

import pytest

from app.backup_crypto import decrypt_file, encrypt_file


def test_encrypted_backup_round_trip_and_tamper_rejection(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
    source = tmp_path / "chess.dump"
    source.write_bytes(os.urandom(1024 * 1024 + 7))
    encrypted = tmp_path / "chess.dump.enc"
    restored = tmp_path / "restored.dump"
    encrypt_file(source, encrypted)
    assert encrypted.read_bytes() != source.read_bytes()
    decrypt_file(encrypted, restored)
    assert restored.read_bytes() == source.read_bytes()
    data = bytearray(encrypted.read_bytes())
    data[30] ^= 1
    encrypted.write_bytes(data)
    restored.unlink()
    with pytest.raises(ValueError):
        decrypt_file(encrypted, restored)
    assert not restored.exists()
