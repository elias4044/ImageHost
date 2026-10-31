import os
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


def environmentFlag(name, default="false"):
    value = os.getenv(name, default).lower()
    if value not in ("true", "false"):
        raise ValueError(f"{name} must be true or false")
    return value == "true"


@dataclass
class Settings:
    dataDir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "data")))
    baseUrl: str = field(default_factory=lambda: os.getenv("BASE_URL", "http://localhost:8000").rstrip("/"))
    passwordHash: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD_HASH", ""))
    clamavHost: str = field(default_factory=lambda: os.getenv("CLAMAV_HOST", "clamav"))
    clamavPort: int = field(default_factory=lambda: int(os.getenv("CLAMAV_PORT", "3310")))
    antivirusEnabled: bool = field(default_factory=lambda: environmentFlag("ANTIVIRUS_ENABLED"))
    nsfwBackend: str = field(default_factory=lambda: os.getenv("NSFW_BACKEND", "local"))
    nsfwUrl: str = field(default_factory=lambda: os.getenv("NSFW_URL", "http://nsfw:8080/scan"))
    nsfwToken: str = field(default_factory=lambda: os.getenv("NSFW_TOKEN", ""))
    safetyUrl: str = field(default_factory=lambda: os.getenv("SAFETY_URL", ""))
    safetyToken: str = field(default_factory=lambda: os.getenv("SAFETY_TOKEN", ""))
    maxUploadBytes: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024**2)
    maxStorageBytes: int = field(default_factory=lambda: int(os.getenv("MAX_STORAGE_MB", "10240")) * 1024**2)
    nsfwThreshold: float = field(default_factory=lambda: float(os.getenv("NSFW_THRESHOLD", "0.5")))
    workerEnabled: bool = True

    @classmethod
    def fromEnvironment(cls, envFile=None):
        envFile = envFile if envFile is not None else Path(__file__).resolve().parent.parent / ".env"
        # Preserve real environment overrides and literal dollar signs in credentials.
        load_dotenv(envFile, override=False, interpolate=False)
        return cls()

    def validate(self):
        origin = urlsplit(self.baseUrl)
        if (
            origin.scheme not in ("http", "https")
            or not origin.hostname
            or origin.path
            or origin.query
            or origin.fragment
            or origin.username
            or origin.password
        ):
            raise ValueError("BASE_URL must be an origin without a path")
        if origin.scheme != "https" and origin.hostname not in ("localhost", "127.0.0.1"):
            raise ValueError("Use HTTPS outside localhost")
        if not self.passwordHash.startswith("$argon2id$"):
            raise ValueError(
                "ADMIN_PASSWORD_HASH is missing or is not an Argon2id hash. "
                "Run 'python -m app.password' and put its full output in .env."
            )
        if self.safetyUrl and (urlsplit(self.safetyUrl).scheme != "https" or not self.safetyToken):
            raise ValueError("SAFETY_URL requires HTTPS and SAFETY_TOKEN")
        if self.safetyToken and not self.safetyUrl:
            raise ValueError(
                "SAFETY_TOKEN requires SAFETY_URL; leave both empty to disable the optional check"
            )
        if self.nsfwBackend not in ("local", "http"):
            raise ValueError("NSFW_BACKEND must be local or http")
        if self.nsfwUrl and urlsplit(self.nsfwUrl).scheme not in ("http", "https"):
            raise ValueError("NSFW_URL must use HTTP on the private Docker network or HTTPS")
        if self.nsfwToken and len(self.nsfwToken) < 32:
            raise ValueError("NSFW_TOKEN must contain at least 32 characters")
        if not 0.25 <= self.nsfwThreshold < 1 or self.maxUploadBytes < 1 or self.maxStorageBytes < 1:
            raise ValueError("Invalid content limits")

    def scannerConfig(self):
        return {
            "antivirus": self.antivirusEnabled and bool(self.clamavHost),
            "nsfw": (
                find_spec("nudenet") is not None
                if self.nsfwBackend == "local"
                else bool(self.nsfwUrl and self.nsfwToken)
            ),
            "specialist": bool(self.safetyUrl and self.safetyToken),
        }

    def requiredScanners(self):
        required = ["nsfw"]
        if self.antivirusEnabled:
            required.append("antivirus")
        if self.safetyUrl or self.safetyToken:
            required.append("specialist")
        return required
