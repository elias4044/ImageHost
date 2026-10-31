import io

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import createApp


def test_interrupted_scan_recovers_and_orphan_upload_is_removed(tmp_path):
    settings = Settings(
        dataDir=tmp_path, passwordHash=PasswordHasher().hash("recovery-test-password"), workerEnabled=False
    )
    first = createApp(settings)
    with TestClient(first, base_url=settings.baseUrl) as client:
        assert (
            client.post(
                "/auth/login",
                json={"password": "recovery-test-password"},
                headers={"Origin": settings.baseUrl},
            ).status_code
            == 200
        )
        buffer = io.BytesIO()
        Image.new("RGB", (10, 10), "green").save(buffer, "PNG")
        uploaded = client.post(
            "/api/v1/images",
            files={"file": ("image.png", buffer.getvalue(), "image/png")},
            headers={"Origin": settings.baseUrl},
        ).json()
        first.state.database.execute("UPDATE images SET state='scanning'")
    (tmp_path / "objects" / "interrupted-upload.original").write_bytes(b"orphaned bytes")
    second = createApp(settings)
    with TestClient(second, base_url=settings.baseUrl):
        assert (
            second.state.database.rows("SELECT state FROM images WHERE id=?", (uploaded["id"],))[0]["state"]
            == "pending"
        )
        assert not (tmp_path / "objects" / "interrupted-upload.original").exists()
        assert (tmp_path / "objects" / f"{uploaded['id']}.original").exists()
        assert (tmp_path / "objects" / f"{uploaded['id']}.webp").exists()
