import hashlib
import io
import random

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.images import normalizeImage
from app.main import createApp


def png(image):
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def test_compression_reduces_detailed_png_and_obeys_quality():
    source = png(Image.frombytes("RGB", (256, 192), random.Random(42).randbytes(256 * 192 * 3)))
    compressed, width, height, digest = normalizeImage(source)
    higherQuality, *_ = normalizeImage(source, quality=95)
    assert len(compressed) < len(source)
    assert len(compressed) < len(higherQuality)
    assert (width, height) == (256, 192)
    assert digest == hashlib.sha256(source).hexdigest()
    assert Image.open(io.BytesIO(compressed)).format == "WEBP"


def test_large_images_resize_without_changing_aspect_ratio():
    source = png(Image.new("RGB", (3000, 1500), "blue"))
    content, width, height, _ = normalizeImage(source)
    assert (width, height) == (2560, 1280)
    assert Image.open(io.BytesIO(content)).size == (width, height)


def test_keep_dimensions_and_no_upscaling():
    source = png(Image.new("RGB", (300, 150), "blue"))
    assert normalizeImage(source, maxDimension=0)[1:3] == (300, 150)
    assert normalizeImage(source, maxDimension=1000)[1:3] == (300, 150)


def test_orientation_is_applied_before_resizing_and_transparency_survives():
    image = Image.new("RGB", (400, 200), "blue")
    exif = Image.Exif()
    exif[274] = 6
    source = io.BytesIO()
    image.save(source, "JPEG", exif=exif)
    content, width, height, _ = normalizeImage(source.getvalue(), maxDimension=100)
    assert (width, height) == (50, 100)
    assert not Image.open(io.BytesIO(content)).getexif()
    transparent = png(Image.new("RGBA", (400, 200), (255, 0, 0, 0)))
    resized, *_ = normalizeImage(transparent, maxDimension=100)
    assert Image.open(io.BytesIO(resized)).convert("RGBA").getpixel((0, 0))[3] == 0


@pytest.mark.parametrize(
    "values",
    [{"imageQuality": 0}, {"imageQuality": 101}, {"imageMaxDimension": -1}, {"imageMaxDimension": 16384}],
)
def test_invalid_compression_configuration_rejected(values):
    settings = Settings(passwordHash=PasswordHasher().hash("compression-test-password"), **values)
    with pytest.raises(ValueError, match="IMAGE_"):
        settings.validate()


def test_upload_uses_configured_compression_and_counts_actual_bytes(tmp_path):
    settings = Settings(
        dataDir=tmp_path,
        passwordHash=PasswordHasher().hash("compression-test-password"),
        imageQuality=70,
        imageMaxDimension=100,
        workerEnabled=False,
    )
    app = createApp(settings)
    source = png(Image.new("RGB", (400, 200), "blue"))
    with TestClient(app, base_url=settings.baseUrl) as client:
        origin = {"Origin": settings.baseUrl}
        assert (
            client.post(
                "/auth/login", json={"password": "compression-test-password"}, headers=origin
            ).status_code
            == 200
        )
        response = client.post(
            "/api/v1/images", files={"file": ("large.png", source, "image/png")}, headers=origin
        )
        assert response.status_code == 202
        image = response.json()
        assert image["state"] == "pending" and image["url"] is None
        assert (image["width"], image["height"]) == (100, 50)
        stored = (tmp_path / "objects" / f"{image['id']}.webp").read_bytes()
        assert image["size"] == len(stored)
        assert stored == normalizeImage(source, quality=70, maxDimension=100)[0]
        assert client.get("/api/v1/stats").json()["storage"] == len(stored) + len(source)
        assert client.get(f"/i/{image['id']}.webp").status_code == 404
