from datetime import datetime, timezone

from scripts.budget import assess

NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)


def snapshot(used=100):
    return {
        "owner": "team",
        "source": "owner billing dashboard",
        "verified_at": "2026-09-07T10:00:00Z",
        "month": "2026-09",
        "allowance_minutes": 2000,
        "used_minutes": used,
        "storage_limit_mb": 500,
        "storage_used_mb": 10,
    }


def test_thresholds():
    for used, status in [
        (100, "NORMAL"),
        (1400, "CONSERVE"),
        (1800, "CRITICAL"),
        (2000, "EXHAUSTED"),
    ]:
        assert assess(snapshot(used), NOW) == status


def test_unknown_and_stale():
    assert assess({}, NOW) == "UNKNOWN"
    data = snapshot()
    data["month"] = "2026-08"
    assert assess(data, NOW) == "UNKNOWN"
    data = snapshot()
    data["verified_at"] = "2026-09-01T10:00:00Z"
    assert assess(data, NOW) == "UNKNOWN"


def test_storage_and_future():
    data = snapshot()
    data["storage_used_mb"] = 460
    assert assess(data, NOW) == "CRITICAL"
    data["verified_at"] = "2026-09-08T10:00:00Z"
    assert assess(data, NOW) == "UNKNOWN"
