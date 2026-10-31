import sqlite3
from contextlib import contextmanager


class Database:
    def __init__(self, path):
        self.path = path
        with self.connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
                    prefix TEXT NOT NULL, scopes TEXT NOT NULL, created REAL NOT NULL,
                    expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    digest TEXT PRIMARY KEY, expires REAL NOT NULL, password_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                    created REAL NOT NULL, state TEXT NOT NULL, public INTEGER NOT NULL,
                    size INTEGER NOT NULL, original_size INTEGER NOT NULL,
                    width INTEGER NOT NULL, height INTEGER NOT NULL,
                    sha256 TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt REAL NOT NULL DEFAULT 0, reason TEXT,
                    views INTEGER NOT NULL DEFAULT 0, bytes_served INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS image_owner ON images(owner, created);
                CREATE INDEX IF NOT EXISTS image_queue ON images(state, next_attempt);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, created REAL NOT NULL,
                    actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rate_limits (
                    bucket TEXT PRIMARY KEY, window INTEGER NOT NULL, count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS usage_daily (
                    day TEXT NOT NULL, owner TEXT NOT NULL, uploads INTEGER NOT NULL DEFAULT 0,
                    views INTEGER NOT NULL DEFAULT 0, bytes_served INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(day, owner)
                );
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def rows(self, sql, args=()):
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, args)]

    def execute(self, sql, args=()):
        with self.connect() as connection:
            return connection.execute(sql, args).rowcount
