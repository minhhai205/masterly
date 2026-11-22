"""Test setup: every run gets its own runtime home with a declared administrator.

The settings and the auth service are read when the modules are first imported,
so the home and auth.json must exist before anything from `masterly` is imported.
"""

import json
import os
from pathlib import Path
import tempfile

import bcrypt

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin-pass"

_HOME = Path(tempfile.mkdtemp(prefix="masterly-test-home-"))
_settings = _HOME / "data" / "user" / "settings"
_settings.mkdir(parents=True)
(_settings / "auth.json").write_text(
    json.dumps(
        {
            "version": 1,
            "enabled": True,
            "username": ADMIN_USERNAME,
            "password_hash": bcrypt.hashpw(ADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode(),
            "token_expire_hours": 24,
            "cookie_secure": False,
            "private_login_hosts": [],
        }
    )
)
os.environ["MASTERLY_HOME"] = str(_HOME)

# Default settings files the app writes on first start (``agents.yaml``), for
# tests that read them without starting the app.
from masterly.services.setup import ensure_agents_settings  # noqa: E402

ensure_agents_settings()
