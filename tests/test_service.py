import hashlib
import io
import time
from unittest.mock import patch

import httpx
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import createApp
from app.scanners import ContentBlocked, ScanUnavailable, probability, scanImage

PASSWORD = "a-long-test-password-123"
PASSWORD_HASH = PasswordHasher().hash(PASSWORD)
ORIGIN = {"Origin": "http://localhost:8000"}


@pytest.fixture
def service(tmp_path):
    settings = Settings(dataDir=tmp_path, passwordHash=PASSWORD_HASH, workerEnabled=False)
    app = createApp(settings)
    with TestClient(app, base_url=settings.baseUrl) as client:
        yield client, app


def signIn(client):
    response = client.post("/auth/login", json={"password": PASSWORD}, headers=ORIGIN)
    assert response.status_code == 200


def createKey(client, scopes=None):
    response = client.post(
        "/api/v1/keys",
        json={"name": "Integration", "scopes": scopes or ["images:read", "images:write", "images:delete"]},
        headers=ORIGIN,
    )
    assert response.status_code == 201
    return response.json()


def imageBytes(mode="RGB", size=(24, 16)):
    image = Image.new(mode, size, "blue")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def upload(client, headers=None, public=True, content=None):
    return client.post(
        "/api/v1/images",
        files={"file": ("photo.png", content or imageBytes(), "image/png")},
        data={"public": str(public).lower()},
        headers=headers or ORIGIN,
    )


def test_authentication_csrf_and_password_rotation(service):
    client, app = service
    assert client.get("/api/v1/stats").status_code == 401
    assert client.post("/auth/login", json={"password": PASSWORD}).status_code == 403
    assert client.post("/auth/login", json={"password": "incorrect"}, headers=ORIGIN).status_code == 401
    signIn(client)
    assert client.get("/").status_code == 200
    cookie = next(iter(client.cookies.jar))
    assert cookie.has_nonstandard_attr("HttpOnly")
    assert cookie.get_nonstandard_attr("SameSite") == "strict"
    assert client.post("/api/v1/keys", json={"name": "bad", "scopes": ["images:read"]}).status_code == 403
    app.state.database.execute("UPDATE sessions SET password_version='old'")
    assert client.get("/api/v1/stats").status_code == 401


def test_quarantine_is_never_delivered(service):
    client, app = service
    signIn(client)
    response = upload(client)
    assert response.status_code == 202, response.text
    image = response.json()
    assert image["state"] == "pending" and image["url"] is None
    assert client.get(f"/i/{image['id']}.webp").status_code == 404
    assert client.get(f"/api/v1/images/{image['id']}/content").status_code == 404
    with patch("app.worker.scanImage", side_effect=ScanUnavailable("provider_down")):
        assert app.state.worker.processOne()
    assert client.get(f"/api/v1/images/{image['id']}").json()["state"] == "scan_error"
    assert client.get(f"/i/{image['id']}.webp").status_code == 404


def test_approval_delivery_metadata_and_stats(service):
    client, app = service
    signIn(client)
    image = upload(client).json()
    with patch("app.worker.scanImage") as scanner:
        app.state.worker.processOne()
        assert scanner.call_args.args[1] == imageBytes()
        assert scanner.call_args.args[-1] == hashlib.sha256(imageBytes()).hexdigest()
    approved = client.get(f"/api/v1/images/{image['id']}").json()
    assert approved["state"] == "ready" and approved["url"]
    assert not (app.state.settings.dataDir / "objects" / f"{image['id']}.original").exists()
    content = client.get(approved["url"])
    assert content.status_code == 200 and content.headers["content-type"] == "image/webp"
    assert content.headers["cache-control"] == "no-store"
    decoded = Image.open(io.BytesIO(content.content))
    assert decoded.size == (24, 16) and not decoded.getexif()
    stats = client.get("/api/v1/stats").json()
    assert stats["views14d"] == 1 and stats["bytes14d"] == len(content.content)
    assert sum(day["uploads"] for day in stats["history"]) == 1
    assert stats["storage"] == len(content.content)
    assert client.delete(f"/api/v1/images/{image['id']}", headers=ORIGIN).status_code == 204
    assert client.get(approved["url"]).status_code == 404
    assert client.get("/api/v1/stats").json()["views14d"] == 1


def test_ownership_scopes_revocation_and_private_images(service):
    client, app = service
    signIn(client)
    keyA, keyB = createKey(client), createKey(client)
    headersA, headersB = (
        {"Authorization": f"Bearer {keyA['key']}"},
        {"Authorization": f"Bearer {keyB['key']}"},
    )
    image = upload(client, headersA, public=False).json()
    imageId = image["id"]
    assert client.get(f"/api/v1/images/{imageId}", headers=headersB).status_code == 404
    assert client.delete(f"/api/v1/images/{imageId}", headers=headersB).status_code == 404
    assert client.get("/api/v1/images", headers=headersB).json()["total"] == 0
    assert client.get("/api/v1/stats", headers=headersB).json()["images"] == 0
    with patch("app.worker.scanImage"):
        app.state.worker.processOne()
    assert client.get(f"/i/{imageId}.webp").status_code == 404
    assert client.get(f"/api/v1/images/{imageId}/content", headers=headersA).status_code == 200
    client.cookies.clear()
    assert client.get("/api/v1/keys", headers=headersA).status_code == 401
    signIn(client)
    readKey = createKey(client, ["images:read"])
    assert upload(client, {"Authorization": f"Bearer {readKey['key']}"}).status_code == 403
    assert client.delete(f"/api/v1/keys/{keyA['id']}", headers=ORIGIN).status_code == 204
    assert client.get("/api/v1/images", headers=headersA).status_code == 401
    stored = app.state.database.rows("SELECT digest FROM api_keys WHERE id=?", (keyB["id"],))[0]
    assert keyB["key"] not in stored["digest"]


def test_blocked_bytes_removed_no_release(service):
    client, app = service
    signIn(client)
    image = upload(client).json()
    with patch("app.worker.scanImage", side_effect=ContentBlocked("specialist_policy")):
        app.state.worker.processOne()
    record = client.get(f"/api/v1/images/{image['id']}").json()
    assert record["state"] == "blocked"
    assert list((app.state.settings.dataDir / "objects").iterdir()) == []
    assert client.post(f"/api/v1/images/{image['id']}/retry", headers=ORIGIN).status_code == 409


def test_expiration_retry_and_restart_recovery(service):
    client, app = service
    signIn(client)
    image = upload(client).json()
    with patch("app.worker.scanImage", side_effect=ScanUnavailable("offline")):
        app.state.worker.processOne()
    assert client.post(f"/api/v1/images/{image['id']}/retry", headers=ORIGIN).status_code == 200
    app.state.database.execute("UPDATE images SET created=?", (time.time() - 86401,))
    app.state.worker.maintenance()
    assert client.get(f"/api/v1/images/{image['id']}").json()["state"] == "expired"
    assert list((app.state.settings.dataDir / "objects").iterdir()) == []


def test_deletion_during_scan_cannot_resurrect(service):
    client, app = service
    signIn(client)
    image = upload(client).json()

    def deleteWhileScanning(*args):
        assert client.delete(f"/api/v1/images/{image['id']}", headers=ORIGIN).status_code == 204

    with patch("app.worker.scanImage", side_effect=deleteWhileScanning):
        app.state.worker.processOne()
    assert client.get(f"/i/{image['id']}.webp").status_code == 404
    assert app.state.database.rows("SELECT id FROM images") == []


def test_scan_crossing_retention_deadline_cannot_publish(service):
    client, app = service
    signIn(client)
    image = upload(client).json()
    now = time.time()
    with patch("app.worker.scanImage"), patch("app.worker.time.time", side_effect=[now, now + 86401]):
        app.state.worker.processOne()
    record = client.get(f"/api/v1/images/{image['id']}").json()
    assert record["state"] == "expired"
    assert client.get(f"/i/{image['id']}.webp").status_code == 404
    assert list((app.state.settings.dataDir / "objects").iterdir()) == []


def test_reject_invalid_animated_oversize_and_quota(service):
    client, app = service
    signIn(client)
    assert upload(client, content=b"<svg onload='alert(1)'></svg>").status_code == 415
    frame = Image.new("RGB", (10, 10), "red")
    buffer = io.BytesIO()
    frame.save(buffer, "PNG", save_all=True, append_images=[Image.new("RGB", (10, 10), "blue")])
    assert upload(client, content=buffer.getvalue()).status_code == 415
    app.state.settings.maxUploadBytes = 10
    assert upload(client).status_code == 413
    app.state.settings.maxUploadBytes = 1024**2
    app.state.settings.maxStorageBytes = 10
    assert upload(client).status_code == 507
    assert list((app.state.settings.dataDir / "objects").iterdir()) == []


def test_chunked_request_limit(service):
    client, app = service
    signIn(client)
    response = client.post(
        "/auth/login",
        content=iter([b"x" * 1024**2 for _ in range(22)]),
        headers={**ORIGIN, "Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_search_pagination_schema_headers_and_pages(service):
    client, app = service
    signIn(client)
    upload(client)
    assert client.get("/api/v1/images?search=photo&limit=1").json()["total"] == 1
    assert client.get("/api/v1/images?search=%27%20OR%201=1").json()["total"] == 0
    assert client.get("/api/v1/images?offset=1").json()["images"] == []
    assert client.get("/api/v1/images?limit=0").status_code == 422
    for path in ("/", "/images", "/keys", "/safety", "/docs", "/login"):
        response = client.get(path)
        assert response.status_code == 200
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert "X-Request-ID" in response.headers
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/v1/images"]["post"]["responses"]["202"]
    assert schema["components"]["securitySchemes"]["HTTPBearer"]
    assert client.get("/api/v1/system").json()["scanners"]["specialist"] is False


def test_login_rate_limit(service):
    client, _ = service
    for _ in range(5):
        assert client.post("/auth/login", json={"password": "bad"}, headers=ORIGIN).status_code == 401
    response = client.post("/auth/login", json={"password": PASSWORD}, headers=ORIGIN)
    assert response.status_code == 429 and response.headers["retry-after"] == "60"


def test_key_expiration(service):
    client, app = service
    signIn(client)
    key = createKey(client)
    app.state.database.execute("UPDATE api_keys SET expires=0")
    assert client.get("/api/v1/images", headers={"Authorization": f"Bearer {key['key']}"}).status_code == 401


@pytest.mark.parametrize("value", [None, True, "0.1", float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_scores_fail_closed(value):
    with pytest.raises(ScanUnavailable):
        probability(value)


def configuredSettings():
    return Settings(
        passwordHash=PASSWORD_HASH,
        nsfwBackend="http",
        nsfwToken="local-scanner-test-token-32-characters",
        safetyUrl="https://safety.example/scan",
        safetyToken="test",
    )


@pytest.mark.parametrize(
    "decision,expected",
    [("block", ContentBlocked), ("review", ScanUnavailable), ("unknown", ScanUnavailable)],
)
def test_specialist_decisions(decision, expected):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"image_id": "image", "sha256": "hash", "decision": decision}
            )
        )
    )
    with (
        patch("app.scanners.antivirus"),
        patch("app.scanners.httpx.Client", return_value=client),
        pytest.raises(expected),
    ):
        scanImage(configuredSettings(), b"original", b"normalized", "image", "hash")


def test_scanner_identity_and_nsfw_threshold():
    def handler(request):
        if request.url.host == "safety.example":
            return httpx.Response(200, json={"image_id": "image", "sha256": "hash", "decision": "allow"})
        return httpx.Response(
            200,
            json={
                "image_id": "image",
                "sha256": hashlib.sha256(b"normalized").hexdigest(),
                "model": "nudenet-3.4.2-320n",
                "scores": {
                    field: 0.5
                    for field in (
                        "FEMALE_BREAST_EXPOSED",
                        "FEMALE_GENITALIA_EXPOSED",
                        "MALE_GENITALIA_EXPOSED",
                        "ANUS_EXPOSED",
                        "BUTTOCKS_EXPOSED",
                    )
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with (
        patch("app.scanners.antivirus"),
        patch("app.scanners.httpx.Client", return_value=client),
        pytest.raises(ContentBlocked),
    ):
        scanImage(configuredSettings(), b"original", b"normalized", "image", "hash")


def test_missing_scanner_configuration():
    with pytest.raises(ScanUnavailable, match="nsfw_not_configured"):
        scanImage(Settings(nsfwBackend="http", nsfwToken=""), b"a", b"b", "id", "hash")


def test_config_requires_tls_and_admin_hash():
    for settings in (
        Settings(),
        Settings(passwordHash=PASSWORD_HASH, baseUrl="http://images.example"),
        Settings(passwordHash=PASSWORD_HASH, safetyUrl="http://scanner/scan", safetyToken="token"),
    ):
        with pytest.raises(ValueError):
            settings.validate()
