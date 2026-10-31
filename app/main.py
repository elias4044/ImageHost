import asyncio
import hashlib
import io
import json
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings
from app.database import Database
from app.images import normalizeImage
from app.worker import ScanWorker

ROOT = Path(__file__).parent
bearer = HTTPBearer(auto_error=False)


def digestToken(token):
    return hashlib.sha256(token.encode()).hexdigest()


class KeyInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[Literal["images:read", "images:write", "images:delete"]] = Field(min_length=1, max_length=3)
    expiresInDays: int = Field(default=90, ge=1, le=365)


class LoginInput(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class ImageOutput(BaseModel):
    id: str
    name: str
    state: str
    public: bool
    size: int
    width: int
    height: int
    created: float
    reason: str | None
    url: str | None
    views: int
    bytes_served: int


class ImagePage(BaseModel):
    images: list[ImageOutput]
    total: int
    limit: int
    offset: int


class BodyLimit:
    def __init__(self, app, maxBytes):
        self.app = app
        self.maxBytes = maxBytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        received = 0

        async def limitedReceive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > self.maxBytes:
                raise HTTPException(413, "Request body too large")
            return message

        await self.app(scope, limitedReceive, send)


def createApp(settings=None):
    settings = settings or Settings.fromEnvironment()
    settings.validate()
    settings.dataDir.mkdir(parents=True, exist_ok=True)
    objectDir = settings.dataDir / "objects"
    objectDir.mkdir(exist_ok=True)
    database = Database(settings.dataDir / "imagehost.db")
    worker = ScanWorker(settings, database)
    passwordHasher = PasswordHasher()
    passwordVersion = digestToken(settings.passwordHash)
    uploadSlots = asyncio.Semaphore(2)

    async def uploadCapacity():
        if uploadSlots.locked():
            raise HTTPException(429, "Upload capacity busy", headers={"Retry-After": "2"})
        async with uploadSlots:
            yield

    @asynccontextmanager
    async def lifespan(app):
        database.execute("UPDATE images SET state='pending' WHERE state='scanning'")
        # Sweep files left by an interrupted upload before accepting new requests.
        known = {row["id"] for row in database.rows("SELECT id FROM images")}
        for path in objectDir.iterdir():
            if path.stem not in known and path.is_file():
                path.unlink()
        if settings.workerEnabled:
            worker.thread.start()
        yield
        worker.stopEvent.set()
        if settings.workerEnabled:
            await run_in_threadpool(worker.thread.join, 100)

    app = FastAPI(
        title="ImageHost API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        description="Quarantine-first image hosting. Bearer keys are scoped to their own images. "
        "Upload returns 202; poll metadata until ready. See /docs for integration details.",
    )
    app.state.database = database
    app.state.worker = worker
    app.state.settings = settings
    app.add_middleware(BodyLimit, maxBytes=settings.maxUploadBytes + 65536)
    templates = Jinja2Templates(directory=ROOT / "templates")
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    def rateLimit(bucket, maximum):
        window = int(time.time() // 60)
        with database.connect() as connection:
            row = connection.execute(
                "INSERT INTO rate_limits(bucket,window,count) VALUES (?,?,1) "
                "ON CONFLICT(bucket) DO UPDATE SET count=CASE WHEN window=excluded.window "
                "THEN count+1 ELSE 1 END, window=excluded.window RETURNING count",
                (bucket, window),
            ).fetchone()
        if row["count"] > maximum:
            raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": "60"})

    def hasSession(request):
        token = request.cookies.get("imagehost_session", "")
        return bool(
            token
            and database.rows(
                "SELECT digest FROM sessions WHERE digest=? AND expires>? AND password_version=?",
                (digestToken(token), time.time(), passwordVersion),
            )
        )

    def requireAdmin(request: Request):
        if not hasSession(request):
            raise HTTPException(401, "Sign in required")
        return "admin"

    def sameOrigin(request):
        if request.headers.get("origin") != settings.baseUrl:
            raise HTTPException(403, "Same-origin request required")

    def principal(
        request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
    ):
        if credentials:
            keys = database.rows(
                "SELECT * FROM api_keys WHERE digest=? AND revoked=0 AND expires>?",
                (digestToken(credentials.credentials), time.time()),
            )
            if not keys:
                raise HTTPException(401, "Invalid or expired API key")
            key = keys[0]
            rateLimit("key:" + key["id"], 120)
            return {"id": key["id"], "scopes": json.loads(key["scopes"])}
        requireAdmin(request)
        if request.method not in ("GET", "HEAD"):
            sameOrigin(request)
        rateLimit("admin", 300)
        return {"id": "admin", "scopes": ["images:read", "images:write", "images:delete"]}

    def checkScope(actor, scope):
        if scope not in actor["scopes"]:
            raise HTTPException(403, "API key lacks required scope")

    def ownedImage(imageId, actor):
        rows = database.rows("SELECT * FROM images WHERE id=?", (imageId,))
        if not rows or (actor["id"] != "admin" and rows[0]["owner"] != actor["id"]):
            raise HTTPException(404, "Image not found")
        return rows[0]

    def serialize(image):
        fields = {key: image[key] for key in ImageOutput.model_fields if key != "url"}
        fields["url"] = (
            f"{settings.baseUrl}/i/{image['id']}.webp"
            if image["state"] == "ready" and image["public"]
            else None
        )
        return fields

    def audit(actor, action, target):
        database.execute(
            "INSERT INTO audit(created,actor,action,target) VALUES (?,?,?,?)",
            (time.time(), actor, action, target),
        )

    @app.middleware("http")
    async def securityHeaders(request, callNext):
        requestId = str(uuid.uuid4())
        response = await callNext(request)
        response.headers.update(
            {
                "X-Request-ID": requestId,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'self'; object-src 'none'",
                "Cache-Control": "no-store",
            }
        )
        if settings.baseUrl.startswith("https://"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def httpError(request, error):
        return JSONResponse(
            {"error": {"code": error.status_code, "message": error.detail}},
            status_code=error.status_code,
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validationError(request, error):
        return JSONResponse(
            {
                "error": {
                    "code": 422,
                    "message": "Invalid request fields",
                    "fields": [".".join(str(part) for part in item["loc"]) for item in error.errors()],
                }
            },
            status_code=422,
        )

    @app.get("/health/live", include_in_schema=False)
    def live():
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    def loginPage(request: Request):
        return templates.TemplateResponse(request=request, name="login.html")

    @app.post("/auth/login", include_in_schema=False)
    def login(request: Request, body: LoginInput):
        sameOrigin(request)
        rateLimit("login:" + request.client.host, 5)
        rateLimit("login:global", 30)
        try:
            passwordHasher.verify(settings.passwordHash, body.password)
        except VerificationError, InvalidHashError:
            raise HTTPException(401, "Incorrect password") from None
        token = secrets.token_urlsafe(48)
        database.execute(
            "INSERT INTO sessions VALUES (?,?,?)", (digestToken(token), time.time() + 43200, passwordVersion)
        )
        audit("admin", "session.created", "admin")
        response = JSONResponse({"status": "ok"})
        response.set_cookie(
            "imagehost_session",
            token,
            httponly=True,
            secure=settings.baseUrl.startswith("https"),
            samesite="strict",
            max_age=43200,
            path="/",
        )
        return response

    @app.post("/auth/logout", include_in_schema=False)
    def logout(request: Request, admin=Depends(requireAdmin)):
        sameOrigin(request)
        database.execute(
            "DELETE FROM sessions WHERE digest=?", (digestToken(request.cookies["imagehost_session"]),)
        )
        response = JSONResponse({"status": "ok"})
        response.delete_cookie("imagehost_session", path="/")
        return response

    @app.get("/", include_in_schema=False)
    @app.get("/images", include_in_schema=False)
    @app.get("/keys", include_in_schema=False)
    @app.get("/safety", include_in_schema=False)
    def dashboard(request: Request):
        if not hasSession(request):
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(
            request=request, name="dashboard.html", context={"page": request.url.path}
        )

    @app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    def docs(request: Request):
        return templates.TemplateResponse(request=request, name="docs.html")

    @app.get("/openapi.json", include_in_schema=False)
    def openapi():
        return app.openapi()

    @app.post(
        "/api/v1/images",
        status_code=202,
        response_model=ImageOutput,
        tags=["Images"],
        dependencies=[Depends(uploadCapacity)],
    )
    async def uploadImage(
        file: Annotated[UploadFile, File(description="JPEG, PNG or static WebP; up to MAX_UPLOAD_MB")],
        public: Annotated[bool, Form()] = True,
        actor=Depends(principal),
    ):
        """Queue an image for mandatory scanning. A 202 response is not a publication approval."""
        checkScope(actor, "images:write")
        try:
            content = await file.read(settings.maxUploadBytes + 1)
        finally:
            await file.close()
        if not content or len(content) > settings.maxUploadBytes:
            raise HTTPException(413, "Image is empty or exceeds upload limit")
        try:
            normalized, width, height, digest = await run_in_threadpool(
                normalizeImage, content, settings.imageQuality, settings.imageMaxDimension
            )
        except ValueError as error:
            raise HTTPException(415, str(error)) from None
        if len(normalized) > settings.maxUploadBytes:
            raise HTTPException(413, "Normalized image exceeds upload limit")
        imageId = uuid.uuid4().hex
        name = Path((file.filename or "image").replace("\\", "/")).name[:160]
        name = "".join(char for char in name if char.isprintable()) or "image"
        now = time.time()
        # Reserve capacity and write both files under the same writer lock.
        with database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            used = connection.execute(
                "SELECT COALESCE(SUM(size + CASE WHEN state='ready' THEN 0 ELSE original_size END),0) "
                "FROM images WHERE state IN ('pending','scanning','scan_error','ready')"
            ).fetchone()[0]
            if used + len(content) + len(normalized) > settings.maxStorageBytes:
                raise HTTPException(507, "Storage quota exceeded")
            try:
                (objectDir / f"{imageId}.original").write_bytes(content)
                (objectDir / f"{imageId}.webp").write_bytes(normalized)
                connection.execute(
                    "INSERT INTO images(id,owner,name,created,state,public,size,original_size,width,height,sha256) "
                    "VALUES (?,?,?,?,'pending',?,?,?,?,?,?)",
                    (
                        imageId,
                        actor["id"],
                        name,
                        now,
                        public,
                        len(normalized),
                        len(content),
                        width,
                        height,
                        digest,
                    ),
                )
                day = datetime.now(UTC).date().isoformat()
                connection.execute(
                    "INSERT INTO usage_daily(day,owner,uploads) VALUES (?,?,1) "
                    "ON CONFLICT(day,owner) DO UPDATE SET uploads=uploads+1",
                    (day, actor["id"]),
                )
                connection.execute(
                    "INSERT INTO audit(created,actor,action,target) VALUES (?,?,?,?)",
                    (now, actor["id"], "image.uploaded", imageId),
                )
            except Exception:
                worker.removeFiles(imageId)
                raise
        return serialize(ownedImage(imageId, actor))

    @app.get("/api/v1/images", response_model=ImagePage, tags=["Images"])
    def listImages(
        state: Literal["pending", "scanning", "scan_error", "ready", "blocked", "expired"] | None = None,
        search: str = Query(default="", max_length=100),
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=1000000),
        actor=Depends(principal),
    ):
        checkScope(actor, "images:read")
        where, params = ["1=1"], []
        if actor["id"] != "admin":
            where.append("owner=?")
            params.append(actor["id"])
        if state:
            where.append("state=?")
            params.append(state)
        if search:
            where.append("instr(lower(name),lower(?)) > 0")
            params.append(search)
        condition = " AND ".join(where)
        total = database.rows(f"SELECT COUNT(*) AS total FROM images WHERE {condition}", params)[0]["total"]
        images = database.rows(
            f"SELECT * FROM images WHERE {condition} ORDER BY created DESC, id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        return {
            "images": [serialize(image) for image in images],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/v1/images/{imageId}", response_model=ImageOutput, tags=["Images"])
    def imageMetadata(imageId: str, actor=Depends(principal)):
        checkScope(actor, "images:read")
        return serialize(ownedImage(imageId, actor))

    def deliver(image):
        if image["state"] != "ready":
            raise HTTPException(404, "Image not found")
        try:
            # Hold bytes before returning; a concurrent deletion cannot break a file response.
            content = (objectDir / f"{image['id']}.webp").read_bytes()
        except FileNotFoundError:
            raise HTTPException(404, "Image not found") from None
        day = datetime.now(UTC).date().isoformat()
        with database.connect() as connection:
            connection.execute(
                "UPDATE images SET views=views+1, bytes_served=bytes_served+? WHERE id=?",
                (len(content), image["id"]),
            )
            connection.execute(
                "INSERT INTO usage_daily(day,owner,views,bytes_served) VALUES (?,?,1,?) "
                "ON CONFLICT(day,owner) DO UPDATE SET views=views+1, bytes_served=bytes_served+excluded.bytes_served",
                (day, image["owner"], len(content)),
            )
        return StreamingResponse(
            io.BytesIO(content),
            media_type="image/webp",
            headers={
                "Content-Length": str(len(content)),
                "Content-Disposition": f'inline; filename="{image["id"]}.webp"',
                "Cross-Origin-Resource-Policy": "cross-origin",
            },
        )

    @app.get(
        "/api/v1/images/{imageId}/content",
        tags=["Images"],
        response_class=StreamingResponse,
        responses={200: {"content": {"image/webp": {"schema": {"type": "string", "format": "binary"}}}}},
    )
    def privateContent(imageId: str, actor=Depends(principal)):
        """Read an approved image, including private images owned by this key."""
        checkScope(actor, "images:read")
        return deliver(ownedImage(imageId, actor))

    @app.get(
        "/i/{imageId}.webp",
        tags=["Delivery"],
        response_class=StreamingResponse,
        responses={200: {"content": {"image/webp": {"schema": {"type": "string", "format": "binary"}}}}},
    )
    def publicContent(imageId: str, request: Request):
        rateLimit("delivery:" + request.client.host, 600)
        rows = database.rows("SELECT * FROM images WHERE id=? AND public=1 AND state='ready'", (imageId,))
        if not rows:
            raise HTTPException(404, "Image not found")
        return deliver(rows[0])

    @app.delete("/api/v1/images/{imageId}", status_code=204, tags=["Images"])
    def deleteImage(imageId: str, actor=Depends(principal)):
        checkScope(actor, "images:delete")
        ownedImage(imageId, actor)
        database.execute("DELETE FROM images WHERE id=?", (imageId,))
        worker.removeFiles(imageId)
        audit(actor["id"], "image.deleted", imageId)

    @app.post("/api/v1/images/{imageId}/retry", tags=["Images"])
    def retryImage(imageId: str, request: Request, admin=Depends(requireAdmin)):
        sameOrigin(request)
        rateLimit("retry", 20)
        changed = database.execute(
            "UPDATE images SET state='pending', attempts=0, next_attempt=0, reason=NULL "
            "WHERE id=? AND state='scan_error' AND created>?",
            (imageId, time.time() - 86400),
        )
        if not changed:
            raise HTTPException(409, "Only scanner errors within 24 hours may be retried")
        audit("admin", "image.retry", imageId)
        return {"status": "pending"}

    @app.get("/api/v1/stats", tags=["Statistics"])
    def stats(actor=Depends(principal)):
        checkScope(actor, "images:read")
        condition, params = ("1=1", []) if actor["id"] == "admin" else ("owner=?", [actor["id"]])
        states = database.rows(
            f"SELECT state, COUNT(*) AS count FROM images WHERE {condition} GROUP BY state", params
        )
        totals = database.rows(
            f"SELECT COUNT(*) AS images, COALESCE(SUM(CASE WHEN state='ready' THEN size "
            f"WHEN state IN ('pending','scanning','scan_error') THEN size+original_size ELSE 0 END),0) AS storage "
            f"FROM images WHERE {condition}",
            params,
        )[0]
        start = datetime.now(UTC).date() - timedelta(days=13)
        usage = database.rows(
            f"SELECT day, SUM(uploads) AS uploads, SUM(views) AS views, SUM(bytes_served) AS bytes "
            f"FROM usage_daily WHERE {condition} AND day>=? GROUP BY day",
            [*params, start.isoformat()],
        )
        days = {row["day"]: row for row in usage}
        history = [
            days.get(
                (start + timedelta(days=index)).isoformat(),
                {"day": (start + timedelta(days=index)).isoformat(), "uploads": 0, "views": 0, "bytes": 0},
            )
            for index in range(14)
        ]
        return {
            **totals,
            "states": {row["state"]: row["count"] for row in states},
            "history": history,
            "storageLimit": settings.maxStorageBytes,
            "views14d": sum(day["views"] for day in history),
            "bytes14d": sum(day["bytes"] for day in history),
        }

    @app.get("/api/v1/keys", tags=["Administration"])
    def listKeys(admin=Depends(requireAdmin)):
        return database.rows(
            "SELECT id,name,prefix,scopes,created,expires,revoked FROM api_keys ORDER BY created DESC"
        )

    @app.post("/api/v1/keys", status_code=201, tags=["Administration"])
    def createKey(body: KeyInput, request: Request, admin=Depends(requireAdmin)):
        sameOrigin(request)
        rateLimit("keys:create", 10)
        token, keyId = "ih_" + secrets.token_urlsafe(36), uuid.uuid4().hex
        now = time.time()
        database.execute(
            "INSERT INTO api_keys(id,name,digest,prefix,scopes,created,expires) VALUES (?,?,?,?,?,?,?)",
            (
                keyId,
                body.name,
                digestToken(token),
                token[:10],
                json.dumps(body.scopes),
                now,
                now + body.expiresInDays * 86400,
            ),
        )
        audit("admin", "key.created", keyId)
        return {"id": keyId, "key": token, "message": "Copy this key now. It cannot be retrieved again."}

    @app.delete("/api/v1/keys/{keyId}", status_code=204, tags=["Administration"])
    def revokeKey(keyId: str, request: Request, admin=Depends(requireAdmin)):
        sameOrigin(request)
        if not database.execute("UPDATE api_keys SET revoked=1 WHERE id=? AND revoked=0", (keyId,)):
            raise HTTPException(404, "Active API key not found")
        audit("admin", "key.revoked", keyId)

    @app.get("/api/v1/system", tags=["Administration"])
    def system(admin=Depends(requireAdmin)):
        return {
            "scanners": settings.scannerConfig(),
            "requiredScanners": settings.requiredScanners(),
            "nsfwBackend": settings.nsfwBackend,
            "maxUploadBytes": settings.maxUploadBytes,
            "maxStorageBytes": settings.maxStorageBytes,
            "compression": {
                "format": "webp",
                "quality": settings.imageQuality,
                "maxDimension": settings.imageMaxDimension,
            },
            "quarantineHours": 24,
            "policy": "NSFW screening is required. Optional enabled checks must also approve. Blocked content cannot be released.",
            "workerAlive": worker.thread.is_alive(),
            "baseUrl": settings.baseUrl,
        }

    @app.get("/api/v1/audit", tags=["Administration"])
    def auditLog(limit: int = Query(default=25, ge=1, le=100), admin=Depends(requireAdmin)):
        return database.rows("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))

    return app
