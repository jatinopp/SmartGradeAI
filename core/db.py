"""SQLite persistence for AquaLoop. Each operation opens its own connection for thread safety."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(os.getenv("AQUALOOP_DB_PATH", "data/aqualoop.db"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                device_id TEXT NOT NULL,
                zone_id TEXT NOT NULL,
                moisture_raw REAL,
                moisture_pct REAL NOT NULL,
                flow_lpm REAL NOT NULL DEFAULT 0,
                temp_c REAL,
                humidity_pct REAL,
                rainfall_mm REAL NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                notes TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(timestamp);
            CREATE INDEX IF NOT EXISTS idx_readings_zone_ts ON readings(zone_id, timestamp);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                zone_id TEXT,
                message TEXT NOT NULL,
                details_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp);
            """
        )


def _normalize_timestamp(value: Any) -> str:
    """Normalize known timestamps to UTC ISO strings so chronology is sortable."""
    if not value:
        return utc_now_iso()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (ValueError, TypeError):
        # Preserve unparseable timestamps for later data-quality diagnostics.
        return str(value)


def add_reading(reading: dict[str, Any]) -> int:
    timestamp = _normalize_timestamp(reading.get("timestamp"))
    values = (
        timestamp,
        str(reading.get("device_id") or "aqualoop_01"),
        str(reading.get("zone_id") or "zone_1"),
        _float_or_none(reading.get("moisture_raw")),
        float(reading.get("moisture_pct", 0)),
        float(reading.get("flow_lpm", 0) or 0),
        _float_or_none(reading.get("temp_c")),
        _float_or_none(reading.get("humidity_pct")),
        float(reading.get("rainfall_mm", 0) or 0),
        str(reading.get("source") or "manual"),
        str(reading.get("notes") or ""),
    )
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO readings
            (timestamp, device_id, zone_id, moisture_raw, moisture_pct, flow_lpm,
             temp_c, humidity_pct, rainfall_mm, source, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )
        return int(cur.lastrowid)


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def get_readings(limit: int = 1000, zone_id: str | None = None, source: str | None = None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if zone_id and zone_id != "All zones":
        clauses.append("zone_id = ?")
        params.append(zone_id)
    if source and source != "All sources":
        clauses.append("source = ?")
        params.append(source)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(max(1, min(int(limit), 100000)))
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM readings{where} ORDER BY timestamp DESC, id DESC LIMIT ?", params
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def get_latest_reading(zone_id: str | None = None) -> dict[str, Any] | None:
    with _connect() as conn:
        if zone_id and zone_id != "All zones":
            row = conn.execute(
                "SELECT * FROM readings WHERE zone_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1", (zone_id,)
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM readings ORDER BY timestamp DESC, id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def add_event(event_type: str, message: str, severity: str = "info", zone_id: str | None = None,
              details: dict[str, Any] | None = None) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO events(timestamp,event_type,severity,zone_id,message,details_json) VALUES(?,?,?,?,?,?)",
            (utc_now_iso(), event_type, severity, zone_id, message, json.dumps(details or {}, default=str)),
        )
        return int(cur.lastrowid)


def get_events(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (max(1, min(limit, 10000)),)).fetchall()
    return [dict(row) for row in rows]


def count_readings() -> int:
    with _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0])


def seed_demo_history() -> None:
    """Add labelled synthetic history once, so the UI is useful before hardware arrives."""
    with _connect() as conn:
        exists = conn.execute("SELECT COUNT(*) FROM readings WHERE source = 'demo_history'").fetchone()[0]
    if exists:
        return
    import math
    import random
    from datetime import timedelta

    rng = random.Random(19)
    now = datetime.now(timezone.utc)
    initial = 47.0
    batch = []
    for i in range(96):
        ts = now - timedelta(minutes=(95 - i) * 15)
        daily = 4.8 * math.sin((i / 96) * 2 * math.pi - 0.7)
        moisture = max(18.0, min(68.0, initial + daily - (i * 0.10) + rng.uniform(-1.4, 1.4)))
        if i in (24, 56, 79):
            moisture += 7.0
        flow = 1.4 if i in (24, 56, 79) else 0.0
        batch.append((ts.isoformat(timespec="seconds"), "aqualoop_demo_01", "zone_1", None,
                      round(moisture, 1), flow, round(27 + 3 * math.sin(i / 96 * 2 * math.pi), 1),
                      round(65 - 8 * math.sin(i / 96 * 2 * math.pi), 1), 0.0, "demo_history",
                      "Synthetic demonstration history; not physical sensor measurements."))
    with _connect() as conn:
        conn.executemany(
            """INSERT INTO readings
            (timestamp,device_id,zone_id,moisture_raw,moisture_pct,flow_lpm,temp_c,humidity_pct,rainfall_mm,source,notes)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""", batch
        )
    add_event("system", "Synthetic demonstration history created. Connect real sensors to replace it with field measurements.", "info", "zone_1")
