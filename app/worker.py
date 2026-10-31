import logging
import threading
import time

from app.scanners import ContentBlocked, ScanUnavailable, scanImage

logger = logging.getLogger(__name__)


class ScanWorker:
    def __init__(self, settings, database):
        self.settings = settings
        self.database = database
        self.stopEvent = threading.Event()
        self.thread = threading.Thread(target=self.run, name="image-scanner", daemon=True)

    def removeFiles(self, imageId):
        for suffix in ("original", "webp"):
            (self.settings.dataDir / "objects" / f"{imageId}.{suffix}").unlink(missing_ok=True)

    def processOne(self):
        now = time.time()
        rows = self.database.rows(
            "SELECT * FROM images WHERE state IN ('pending', 'scan_error') "
            "AND next_attempt <= ? AND attempts < 5 ORDER BY created LIMIT 1",
            (now,),
        )
        if not rows:
            return False
        image = rows[0]
        imageId = image["id"]
        self.database.execute(
            "UPDATE images SET state='scanning', attempts=attempts+1 WHERE id=?", (imageId,)
        )
        objectDir = self.settings.dataDir / "objects"
        try:
            scanImage(
                self.settings,
                (objectDir / f"{imageId}.original").read_bytes(),
                (objectDir / f"{imageId}.webp").read_bytes(),
                imageId,
                image["sha256"],
            )
            state, reason = "ready", None
            (objectDir / f"{imageId}.original").unlink(missing_ok=True)
        except ContentBlocked as error:
            state, reason = "blocked", str(error)
            self.removeFiles(imageId)
        except ScanUnavailable as error:
            state, reason = "scan_error", str(error)
        except OSError:
            state, reason = "scan_error", "storage_unavailable"
        if state == "ready" and time.time() >= image["created"] + 86400:
            state, reason = "expired", "quarantine_expired"
            self.removeFiles(imageId)
        # A deleted image cannot be resurrected by an in-flight scan.
        with self.database.connect() as connection:
            updated = connection.execute(
                "UPDATE images SET state=?, reason=?, next_attempt=? WHERE id=? AND state='scanning'",
                (state, reason, now + 60 * 2 ** image["attempts"], imageId),
            ).rowcount
            if updated:
                connection.execute(
                    "INSERT INTO audit(created,actor,action,target) VALUES (?,?,?,?)",
                    (now, "scanner", f"scan.{state}", imageId),
                )
        if not updated:
            self.removeFiles(imageId)
        return True

    def maintenance(self):
        now = time.time()
        for image in self.database.rows(
            "SELECT id FROM images WHERE state IN ('pending','scan_error') AND created < ?", (now - 86400,)
        ):
            self.database.execute(
                "UPDATE images SET state='expired', reason='quarantine_expired' WHERE id=?", (image["id"],)
            )
            self.removeFiles(image["id"])
        self.database.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        self.database.execute("DELETE FROM rate_limits WHERE window < ?", (int(now // 60) - 2,))
        self.database.execute("DELETE FROM audit WHERE created < ?", (now - 90 * 86400,))

    def run(self):
        while not self.stopEvent.is_set():
            try:
                self.maintenance()
                if self.processOne():
                    continue
            except Exception:
                # Keep the durable queue recoverable even after an unexpected scanner fault.
                logger.exception("Image worker failed; quarantined content remains private")
                self.database.execute(
                    "UPDATE images SET state='scan_error', reason='worker_error', next_attempt=? WHERE state='scanning'",
                    (time.time() + 60,),
                )
            self.stopEvent.wait(3)
