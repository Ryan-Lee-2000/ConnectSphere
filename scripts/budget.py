"""Account-wide manually verified snapshot until a real owner/API is configured."""

import json
from datetime import datetime, timezone
from pathlib import Path


def assess(data, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        if not data.get("owner") or not data.get("source"):
            return "UNKNOWN"
        stamp = datetime.fromisoformat(data["verified_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None or not 0 <= (now - stamp).total_seconds() <= 86400:
            return "UNKNOWN"
        if data["month"] != now.strftime("%Y-%m"):
            return "UNKNOWN"
        allowance, used = data["allowance_minutes"], data["used_minutes"]
        storage_limit, storage = data["storage_limit_mb"], data["storage_used_mb"]
        numbers = (allowance, used, storage_limit, storage)
        if any(type(v) not in (int, float) for v in numbers):
            return "UNKNOWN"
        if allowance <= 0 or storage_limit <= 0 or used < 0 or storage < 0:
            return "UNKNOWN"
        ratio = max(used / allowance, storage / storage_limit)
        return (
            "EXHAUSTED"
            if ratio >= 1
            else ("CRITICAL" if ratio >= 0.9 else "CONSERVE" if ratio >= 0.7 else "NORMAL")
        )
    except (KeyError, TypeError, ValueError):
        return "UNKNOWN"


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "docs/ci-budget.json"
    data = json.loads(path.read_text())
    print(f"Actions budget: {assess(data)}")
    print(json.dumps(data, indent=2))
    print(
        "Snapshot, not live telemetry. UNKNOWN never means zero usage. "
        "Billing settings, not this script, enforce the $0 limit."
    )
