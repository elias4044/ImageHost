"""Start a local, isolated preview with a random admin credential."""

import secrets
from pathlib import Path

import uvicorn
from argon2 import PasswordHasher

from app.config import Settings
from app.main import createApp

password = secrets.token_urlsafe(32)
settings = Settings(dataDir=Path(".tmp/preview"), passwordHash=PasswordHasher().hash(password))
app = createApp(settings)
# Keep the random preview credential local and out of source control.
Path(".tmp/preview-password.txt").write_text(password)
uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)
