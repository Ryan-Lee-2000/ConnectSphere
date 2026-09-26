"""PostgreSQL transaction locks for cross-table venue availability changes."""

from datetime import date
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.slots import OPERATING_SLOTS


def lock_venue_slots(
    session: Session,
    venue_id: int,
    slots: Iterable[tuple[date, str]],
) -> None:
    """Serialize changes that affect the same venue/date/slot.

    Booking occupancy and operational blocks live in different tables, so a
    constraint on either table cannot prevent a write-skew race between them.
    PostgreSQL transaction-scoped advisory locks provide one shared boundary.
    SQLite remains a no-op because it already serializes writes and is used
    only by the fast unit/API test suite.
    """

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return

    ordered_slots = sorted(set(slots), key=lambda value: (value[0], value[1]))
    for day, slot in ordered_slots:
        if slot not in OPERATING_SLOTS:
            raise ValueError("Unsupported operating slot.")
        slot_key = day.toordinal() * len(OPERATING_SLOTS) + OPERATING_SLOTS.index(slot)
        session.execute(
            text("SELECT pg_advisory_xact_lock(:venue_id, :slot_key)"),
            {"venue_id": venue_id, "slot_key": slot_key},
        )
