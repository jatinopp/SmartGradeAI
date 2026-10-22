from datetime import datetime, timedelta, timezone

from core import db


def test_reading_storage_normalizes_time_and_returns_chronological_order(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "aqualoop_test.db")
    db.init_db()
    now = datetime.now(timezone.utc)
    db.add_reading({"timestamp": (now + timedelta(minutes=1)).isoformat(), "device_id": "test", "zone_id": "z1", "moisture_pct": 45, "source": "manual"})
    db.add_reading({"timestamp": now.isoformat(), "device_id": "test", "zone_id": "z1", "moisture_pct": 40, "source": "manual"})
    rows = db.get_readings(limit=10)
    assert len(rows) == 2
    assert rows[0]["moisture_pct"] == 40
    assert rows[1]["moisture_pct"] == 45
    assert rows[-1]["timestamp"].endswith("+00:00")
