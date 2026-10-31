import pytest
from argon2 import PasswordHasher

from app.config import Settings


def test_local_env_loads_literal_password_hash_and_quoted_values(tmp_path, monkeypatch):
    passwordHash = PasswordHasher().hash("local-startup-test-password")
    envFile = tmp_path / ".env"
    envFile.write_text(
        f"ADMIN_PASSWORD_HASH='{passwordHash}'\nBASE_URL=http://localhost:8000\n"
        "SAFETY_TOKEN='literal-${NOT_A_VARIABLE}-token'\n",
        encoding="utf-8",
    )
    for name in ("ADMIN_PASSWORD_HASH", "BASE_URL", "SAFETY_TOKEN"):
        monkeypatch.setenv(name, "temporary-test-value")
        monkeypatch.delenv(name)
    settings = Settings.fromEnvironment(envFile)
    assert settings.passwordHash == passwordHash
    assert settings.safetyToken == "literal-${NOT_A_VARIABLE}-token"
    assert settings.baseUrl == "http://localhost:8000"


def test_process_environment_takes_precedence_over_env_file(tmp_path, monkeypatch):
    envFile = tmp_path / ".env"
    envFile.write_text("ADMIN_PASSWORD_HASH='file-value'\n", encoding="utf-8")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "process-value")
    assert Settings.fromEnvironment(envFile).passwordHash == "process-value"


def test_mistyped_antivirus_flag_does_not_silently_disable_it(monkeypatch):
    monkeypatch.setenv("ANTIVIRUS_ENABLED", "yes")
    with pytest.raises(ValueError, match="ANTIVIRUS_ENABLED must be true or false"):
        Settings()
