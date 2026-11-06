"""Symmetric encryption for panel credentials and stored config files."""
from cryptography.fernet import Fernet

from config.settings import get_settings


def _fernet() -> Fernet:
    return Fernet(get_settings().encryption_key.encode())


def encrypt_text(value: str | None) -> str | None:
    return None if value is None else _fernet().encrypt(value.encode()).decode()


def decrypt_text(token: str | None) -> str | None:
    return None if token is None else _fernet().decrypt(token.encode()).decode()


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    return _fernet().decrypt(data)
