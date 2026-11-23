"""Stored credentials are encrypted with ENCRYPTION_KEY."""

from __future__ import annotations

from cryptography.fernet import Fernet
import pytest

from masterly.services import encryption
from masterly.services.config import map_catalog_secrets


def test_round_trip_and_plain_values_pass_through():
    stored = encryption.encrypt_text("sk-secret")
    assert stored.startswith(encryption.ENCRYPTED_PREFIX)
    assert "sk-secret" not in stored
    assert encryption.encrypt_text(stored) == stored
    assert encryption.decrypt_text(stored) == "sk-secret"
    assert encryption.decrypt_text("written-before-encryption") == "written-before-encryption"


def test_a_different_key_refuses_to_decrypt(monkeypatch):
    stored = encryption.encrypt_text("sk-secret")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    encryption._fernet.cache_clear()
    try:
        with pytest.raises(encryption.EncryptionKeyError):
            encryption.decrypt_text(stored)
    finally:
        monkeypatch.undo()
        encryption._fernet.cache_clear()


def test_only_credentials_are_encrypted_in_a_catalog():
    catalog = {
        "connections": [
            {"id": "c", "name": "Gateway", "api_key": ["k1", "k2"], "extra_headers": {"X": "h"}}
        ],
        "services": {"llm": {"profiles": [{"id": "p", "base_url": "https://x", "api_key": ""}]}},
    }
    stored = map_catalog_secrets(catalog, encryption.encrypt_text)
    connection = stored["connections"][0]
    assert connection["name"] == "Gateway"
    assert all(key.startswith(encryption.ENCRYPTED_PREFIX) for key in connection["api_key"])
    assert connection["extra_headers"]["X"].startswith(encryption.ENCRYPTED_PREFIX)
    assert stored["services"]["llm"]["profiles"][0] == {
        "id": "p",
        "base_url": "https://x",
        "api_key": "",
    }
    assert map_catalog_secrets(stored, encryption.decrypt_text) == catalog
