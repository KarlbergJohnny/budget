"""SQLite-lagring. En fil, inga extra beroenden."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    gateway TEXT NOT NULL,
    mac TEXT NOT NULL,
    corner_reported INTEGER,
    seq INTEGER NOT NULL,
    distance_mm REAL NOT NULL,
    battery_mv INTEGER,
    temp_c INTEGER,
    flags INTEGER NOT NULL DEFAULT 0,
    rssi INTEGER
);
CREATE INDEX IF NOT EXISTS readings_mac_ts ON readings (mac, ts);

CREATE TABLE IF NOT EXISTS gateways (
    id TEXT PRIMARY KEY,
    last_seen REAL NOT NULL,
    fw TEXT,
    wifi_rssi INTEGER,
    uptime_s INTEGER
);

CREATE TABLE IF NOT EXISTS devices (
    mac TEXT PRIMARY KEY,
    wagon TEXT NOT NULL,
    corner TEXT NOT NULL,
    registered_at REAL NOT NULL,
    UNIQUE (wagon, corner)
);

CREATE TABLE IF NOT EXISTS wagons (
    id TEXT PRIMARY KEY,
    tare_kg REAL,
    max_total_kg REAL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS calibration (
    wagon TEXT NOT NULL,
    corner TEXT NOT NULL,
    zero_mm REAL,
    kg_per_mm REAL,
    points_json TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (wagon, corner)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    wagon TEXT NOT NULL,
    kind TEXT NOT NULL,
    who TEXT,
    detail_json TEXT
);
"""


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, args))

    def close(self) -> None:
        self._conn.close()

    # ---- hjälpfunktioner ----

    def add_event(self, conn: sqlite3.Connection, wagon: str, kind: str, who: str | None,
                  detail: dict) -> None:
        conn.execute(
            "INSERT INTO events (ts, wagon, kind, who, detail_json) VALUES (?, ?, ?, ?, ?)",
            (time.time(), wagon, kind, who, json.dumps(detail, ensure_ascii=False)),
        )

    def ensure_wagon(self, conn: sqlite3.Connection, wagon: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO wagons (id, created_at) VALUES (?, ?)", (wagon, time.time())
        )
