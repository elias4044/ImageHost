"""Local-only nudity detector service. Licensed under AGPL-3.0-or-later."""

import hashlib
import io
import logging
import os
import secrets
import threading
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from moderation.inference import MODEL, detectionScores, loadDetector, prepareImage

logger = logging.getLogger(__name__)


def createApp(detectorFactory=loadDetector, token=None, maxUploadBytes=None):
    token = token if token is not None else os.getenv("NSFW_TOKEN", "")
    if len(token) < 32:
        raise ValueError("NSFW_TOKEN must contain at least 32 characters")
    maxUploadBytes = maxUploadBytes or int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024**2
    inferenceLock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        app.state.detector = await run_in_threadpool(detectorFactory)
        buffer = io.BytesIO()
        Image.new("RGB", (32, 32), "white").save(buffer, "WEBP")
        detectionScores(await run_in_threadpool(app.state.detector.detect, buffer.getvalue()))
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health/ready")
    def ready():
        return {"model": MODEL, "ready": True}

    def infer(content):
        prepared = prepareImage(content)
        with inferenceLock:
            return detectionScores(app.state.detector.detect(prepared))

    @app.post("/scan")
    async def scan(
        request: Request,
        authorization: Annotated[str, Header()],
        xImageId: Annotated[str, Header(alias="X-Image-ID", pattern=r"^[a-f0-9]{32}$")],
        xContentSha256: Annotated[str, Header(alias="X-Content-SHA256", pattern=r"^[a-f0-9]{64}$")],
    ):
        if not secrets.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
            raise HTTPException(401, "Invalid scanner credential")
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > maxUploadBytes:
                raise HTTPException(413, "Image exceeds scanner limit")
            content.extend(chunk)
        digest = hashlib.sha256(content).hexdigest()
        if digest != xContentSha256:
            raise HTTPException(422, "Image digest mismatch")
        try:
            scores = await run_in_threadpool(infer, bytes(content))
        except (
            ValueError,
            OSError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            raise HTTPException(415, "Invalid or unsupported image") from None
        except Exception:
            logger.exception("Local inference failed")
            raise HTTPException(503, "Local scanner unavailable") from None
        return {"image_id": xImageId, "sha256": digest, "model": MODEL, "scores": scores}

    return app
