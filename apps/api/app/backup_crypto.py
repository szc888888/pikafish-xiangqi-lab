"""Stream authenticated backup encryption using a 32-byte environment key."""
import argparse
import base64
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"CHESSBK1"
CHUNK = 1024 * 1024


def _key() -> bytes:
    encoded = os.getenv("BACKUP_ENCRYPTION_KEY", "")
    try:
        key = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError("BACKUP_ENCRYPTION_KEY must be base64 for 32 bytes") from exc
    if len(key) != 32:
        raise ValueError("BACKUP_ENCRYPTION_KEY must be base64 for 32 bytes")
    return key


def encrypt_file(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    key, nonce = _key(), os.urandom(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(MAGIC + nonce)
    temp = destination.with_name(destination.name + ".tmp")
    try:
        with source.open("rb") as reader, temp.open("wb") as writer:
            writer.write(MAGIC + nonce)
            while chunk := reader.read(CHUNK):
                writer.write(encryptor.update(chunk))
            writer.write(encryptor.finalize())
            writer.write(encryptor.tag)
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


def decrypt_file(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    key = _key()
    size = source.stat().st_size
    if size < len(MAGIC) + 12 + 16:
        raise ValueError("Invalid backup archive")
    temp = destination.with_name(destination.name + ".tmp")
    try:
        with source.open("rb") as reader, temp.open("wb") as writer:
            header = reader.read(len(MAGIC) + 12)
            if not header.startswith(MAGIC):
                raise ValueError("Invalid backup archive")
            reader.seek(size - 16)
            tag = reader.read(16)
            decryptor = Cipher(algorithms.AES(key), modes.GCM(header[len(MAGIC):], tag)).decryptor()
            decryptor.authenticate_additional_data(header)
            reader.seek(len(header))
            remaining = size - len(header) - 16
            while remaining:
                chunk = reader.read(min(CHUNK, remaining))
                if not chunk:
                    raise ValueError("Truncated backup archive")
                remaining -= len(chunk)
                writer.write(decryptor.update(chunk))
            try:
                writer.write(decryptor.finalize())
            except InvalidTag as exc:
                raise ValueError("Backup authentication failed") from exc
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["encrypt", "decrypt"])
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    (encrypt_file if args.operation == "encrypt" else decrypt_file)(args.source, args.destination)
