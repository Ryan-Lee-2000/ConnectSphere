"""Persist normalized venue-booking review findings (SPL-130)."""

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "s3_booking_review_findings"
down_revision = "s3_event_change_requests"
branch_labels = None
depends_on = None

TABLE = "venue_booking_review_findings"
SGT = timezone(timedelta(hours=8))
JSON_TYPE = sa.JSON().with_variant(JSONB(), "postgresql")
ACTIVE_STATUSES = ("requested", "approved")

# The migration owns a snapshot of every column and rule used by its data backfill. Importing live
# ORM models here would make a fresh upgrade fail as soon as a later migration changes those
# models to select a column that does not exist at this historical revision.
VENUES = sa.table(
    "venues",
    sa.column("id", sa.Integer()),
    sa.column("setup_minutes", sa.Integer()),
    sa.column("turnaround_minutes", sa.Integer()),
    sa.column("operating_intervals", JSON_TYPE),
    sa.column("timing_revision", sa.Integer()),
)
EVENTS = sa.table(
    "event_requests",
    sa.column("id", sa.Integer()),
    sa.column("name", sa.Text()),
    sa.column("proposed_date", sa.Date()),
    sa.column("start_time", sa.Time()),
    sa.column("end_time", sa.Time()),
)
BOOKINGS = sa.table(
    "venue_bookings",
    sa.column("id", sa.Integer()),
    sa.column("event_request_id", sa.Integer()),
    sa.column("venue_id", sa.Integer()),
    sa.column("status", sa.String()),
    sa.column("requires_review", sa.Boolean()),
    sa.column("review_marked_at", sa.DateTime(timezone=True)),
    sa.column("exact_timing", JSON_TYPE),
)
OCCUPANCY = sa.table(
    "venue_booking_occupancy",
    sa.column("id", sa.Integer()),
    sa.column("booking_id", sa.Integer()),
    sa.column("occupancy_date", sa.Date()),
    sa.column("slot", sa.String()),
    sa.column("kind", sa.String()),
)
BLOCKS = sa.table(
    "venue_operational_blocks",
    sa.column("id", sa.Integer()),
    sa.column("venue_id", sa.Integer()),
    sa.column("start_date", sa.Date()),
    sa.column("end_date", sa.Date()),
    sa.column("slots", JSON_TYPE),
    sa.column("reason", sa.Text()),
    sa.column("exact_start", sa.DateTime(timezone=True)),
    sa.column("exact_end", sa.DateTime(timezone=True)),
    sa.column("removed_at", sa.DateTime(timezone=True)),
)
FINDINGS = sa.table(
    TABLE,
    sa.column("booking_id", sa.Integer()),
    sa.column("finding_key", sa.String()),
    sa.column("reason_type", sa.String()),
    sa.column("detail", sa.Text()),
    sa.column("original_occupancy", JSON_TYPE),
    sa.column("current_occupancy", JSON_TYPE),
    sa.column("venue_timing_revision", sa.Integer()),
    sa.column("first_assessed_at", sa.DateTime(timezone=True)),
    sa.column("last_assessed_at", sa.DateTime(timezone=True)),
)


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime

    def overlaps(self, other: "Interval") -> bool:
        return self.start < other.end and other.start < self.end

    def serialize(self) -> dict[str, str]:
        return {
            "start": self.start.astimezone(SGT).isoformat(),
            "end": self.end.astimezone(SGT).isoformat(),
        }


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("finding_key", sa.String(length=120), nullable=False),
        sa.Column("reason_type", sa.String(length=40), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("original_occupancy", JSON_TYPE),
        sa.Column("current_occupancy", JSON_TYPE),
        sa.Column("venue_timing_revision", sa.Integer(), nullable=False),
        sa.Column("first_assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by_account_id", sa.Uuid(as_uuid=False)),
        sa.ForeignKeyConstraint(["booking_id"], ["venue_bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by_account_id"], ["accounts.id"]),
        sa.CheckConstraint(
            "reason_type in ('overlap', 'operational_block', 'outside_operating_hours', "
            "'unresolved_historical_timing')",
            name="ck_venue_booking_review_findings_known_reason",
        ),
        sa.UniqueConstraint(
            "booking_id", "finding_key", name="uq_venue_booking_review_findings_key"
        ),
    )
    op.create_index("ix_venue_booking_review_findings_active", TABLE, ["booking_id", "resolved_at"])

    # Backfill in the same Alembic transaction, using only the historical schema declared above.
    # Venues without exact timing are assessed as having no revised rule yet; their commitments
    # are first flagged when Venue Staff save a complete exact-timing configuration.
    bind = op.get_bind()
    _backfill(bind, datetime.now(timezone.utc))

    if bind.dialect.name == "postgresql":
        op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE {TABLE} FROM PUBLIC")
        op.execute(f"REVOKE ALL ON SEQUENCE {TABLE}_id_seq FROM PUBLIC")
        op.execute(
            f"""
            DO $$
            DECLARE role_name text;
            BEGIN
                FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                        EXECUTE format('REVOKE ALL ON TABLE {TABLE} FROM %I', role_name);
                        EXECUTE format('REVOKE ALL ON SEQUENCE {TABLE}_id_seq FROM %I', role_name);
                    END IF;
                END LOOP;
            END $$;
            """
        )


def _backfill(bind, assessed_at: datetime) -> None:
    venue_rows = {row["id"]: row for row in bind.execute(sa.select(VENUES)).mappings()}
    booking_rows = list(
        bind.execute(
            sa.select(BOOKINGS)
            .where(BOOKINGS.c.status.in_(ACTIVE_STATUSES))
            .order_by(BOOKINGS.c.id)
        ).mappings()
    )
    event_ids = {row["event_request_id"] for row in booking_rows}
    event_rows = {
        row["id"]: row
        for row in (
            bind.execute(sa.select(EVENTS).where(EVENTS.c.id.in_(event_ids))).mappings()
            if event_ids
            else []
        )
    }
    booking_ids = {row["id"] for row in booking_rows}
    claims_by_booking: dict[int, list[Any]] = {booking_id: [] for booking_id in booking_ids}
    if booking_ids:
        claims = bind.execute(
            sa.select(OCCUPANCY)
            .where(OCCUPANCY.c.booking_id.in_(booking_ids))
            .order_by(OCCUPANCY.c.id)
        ).mappings()
        for claim in claims:
            claims_by_booking[claim["booking_id"]].append(claim)
    blocks_by_venue: dict[int, list[Any]] = {}
    for block in bind.execute(
        sa.select(BLOCKS).where(BLOCKS.c.removed_at.is_(None)).order_by(BLOCKS.c.id)
    ).mappings():
        blocks_by_venue.setdefault(block["venue_id"], []).append(block)

    current: dict[int, Interval] = {}
    for booking in booking_rows:
        interval = _current_occupancy(
            venue_rows.get(booking["venue_id"]), event_rows.get(booking["event_request_id"])
        )
        if interval is not None:
            current[booking["id"]] = interval

    inserts = []
    for booking in booking_rows:
        venue = venue_rows.get(booking["venue_id"])
        event = event_rows.get(booking["event_request_id"])
        # No timing configuration means there is no revised preparation rule to assess yet.
        if not _configured(venue) or not _has_not_ended(
            booking, event, claims_by_booking[booking["id"]], assessed_at
        ):
            continue
        reasons = _reasons(
            booking,
            venue,
            current.get(booking["id"]),
            booking_rows,
            current,
            claims_by_booking,
            blocks_by_venue.get(booking["venue_id"], []),
            event_rows,
        )
        if not reasons:
            continue
        original = _original_occupancy(booking, claims_by_booking[booking["id"]])
        recalculated = current.get(booking["id"])
        for key, reason_type, detail in reasons:
            inserts.append(
                {
                    "booking_id": booking["id"],
                    "finding_key": key,
                    "reason_type": reason_type,
                    "detail": detail,
                    "original_occupancy": original,
                    "current_occupancy": recalculated.serialize() if recalculated else None,
                    "venue_timing_revision": venue["timing_revision"],
                    "first_assessed_at": assessed_at,
                    "last_assessed_at": assessed_at,
                }
            )
        bind.execute(
            sa.update(BOOKINGS)
            .where(BOOKINGS.c.id == booking["id"])
            .values(requires_review=True, review_marked_at=assessed_at)
        )
    if inserts:
        bind.execute(sa.insert(FINDINGS), inserts)


def _reasons(
    booking,
    venue,
    current: Interval | None,
    bookings,
    current_intervals: dict[int, Interval],
    claims_by_booking,
    blocks,
    event_rows,
) -> list[tuple[str, str, str]]:
    reasons: list[tuple[str, str, str]] = []
    if _json(booking["exact_timing"]) is None or current is None:
        reasons.append(
            (
                "historical-timing",
                "unresolved_historical_timing",
                "Exact occupied times must be supplied before this historical booking "
                "can be cleared.",
            )
        )
    if current is None:
        return reasons
    if not _opening_covers(current, _json(venue["operating_intervals"])):
        reasons.append(
            (
                "outside-operating-hours",
                "outside_operating_hours",
                "The revised occupied interval is outside the venue's operating hours.",
            )
        )
    for block in blocks:
        if _block_overlaps(block, current):
            reasons.append(
                (
                    f"operational-block:{block['id']}",
                    "operational_block",
                    f"Operational block: {block['reason']}",
                )
            )
    for peer in bookings:
        if peer["venue_id"] != booking["venue_id"] or peer["id"] == booking["id"]:
            continue
        peer_intervals = []
        if peer["id"] in current_intervals:
            peer_intervals.append(current_intervals[peer["id"]])
        elif _json(peer["exact_timing"]):
            peer_intervals.extend(_protected_intervals(peer, claims_by_booking[peer["id"]]))
        if any(current.overlaps(interval) for interval in peer_intervals):
            peer_event = event_rows.get(peer["event_request_id"])
            peer_name = peer_event["name"] if peer_event else f"event {peer['event_request_id']}"
            reasons.append(
                (
                    f"overlap:{peer['id']}",
                    "overlap",
                    f"The revised occupied interval overlaps {peer_name} (booking {peer['id']}).",
                )
            )
    return reasons


def _configured(venue) -> bool:
    return bool(
        venue
        and venue["setup_minutes"] is not None
        and venue["turnaround_minutes"] is not None
        and venue["operating_intervals"] is not None
    )


def _current_occupancy(venue, event) -> Interval | None:
    if not _configured(venue):
        return None
    advertised = _event_interval(event)
    if advertised is None:
        return None
    try:
        return Interval(
            advertised.start - timedelta(minutes=int(venue["setup_minutes"])),
            advertised.end + timedelta(minutes=int(venue["turnaround_minutes"])),
        )
    except (OverflowError, ValueError):
        return None


def _event_interval(event) -> Interval | None:
    if not event or not all(
        event[name] is not None for name in ("proposed_date", "start_time", "end_time")
    ):
        return None
    try:
        day = _date(event["proposed_date"])
        start = _time(event["start_time"])
        end = _time(event["end_time"])
        return Interval(datetime.combine(day, start, SGT), datetime.combine(day, end, SGT))
    except (TypeError, ValueError):
        return None


def _original_occupancy(booking, claims) -> dict[str, Any]:
    exact = _json(booking["exact_timing"])
    occupied = exact.get("occupied") if isinstance(exact, dict) else None
    if isinstance(occupied, dict) and {"start", "end"}.issubset(occupied):
        return {"start": occupied["start"], "end": occupied["end"]}
    return {
        "legacy_slots": [
            {
                "date": _date(claim["occupancy_date"]).isoformat(),
                "slot": claim["slot"],
                "kind": claim["kind"],
            }
            for claim in claims
        ]
    }


def _protected_intervals(booking, claims) -> list[Interval]:
    intervals = []
    exact = _json(booking["exact_timing"])
    if isinstance(exact, dict):
        parsed = _json_interval(exact.get("occupied"))
        if parsed:
            intervals.append(parsed)
    for claim in claims:
        interval = _legacy_slot_interval(_date(claim["occupancy_date"]), claim["slot"])
        if interval:
            intervals.append(interval)
    return intervals


def _has_not_ended(booking, event, claims, when: datetime) -> bool:
    intervals = _protected_intervals(booking, claims)
    advertised = _event_interval(event)
    if advertised:
        intervals.append(advertised)
    return not intervals or any(interval.end > when for interval in intervals)


def _opening_covers(interval: Interval, hours) -> bool:
    if not isinstance(hours, list):
        return False
    merged = []
    for pair in sorted(hours):
        if merged and merged[-1][1] == pair[0]:
            merged[-1][1] = pair[1]
        else:
            merged.append(list(pair))
    if merged == [[0, 1440]]:
        return True
    start, end = interval.start.astimezone(SGT), interval.end.astimezone(SGT)
    if end - start >= timedelta(days=1):
        return False

    def covers(begin, finish):
        return begin == finish or any(a <= begin and finish <= b for a, b in merged)

    begin = start.hour * 60 + start.minute + start.second / 60
    finish = end.hour * 60 + end.minute + end.second / 60
    if start.date() == end.date():
        return covers(begin, finish)
    return covers(begin, 1440) and covers(0, finish)


def _block_overlaps(block, interval: Interval) -> bool:
    if block["exact_start"] is not None and block["exact_end"] is not None:
        exact = Interval(_aware(block["exact_start"]), _aware(block["exact_end"]))
        return interval.overlaps(exact)
    first = max(_date(block["start_date"]), interval.start.astimezone(SGT).date())
    last = min(_date(block["end_date"]), interval.end.astimezone(SGT).date())
    if first > last:
        return False
    days = {first, last}
    if (last - first).days > 1:
        days.add(first + timedelta(days=1))
    return any(
        interval.overlaps(candidate)
        for day in days
        for slot in (_json(block["slots"]) or [])
        if (candidate := _legacy_slot_interval(day, slot)) is not None
    )


def _legacy_slot_interval(day: date, slot: str) -> Interval | None:
    boundaries = {"AM": (420, 720), "PM": (780, 1080), "NIGHT": (1140, 1440)}
    if slot not in boundaries:
        return None
    begin, end = boundaries[slot]
    base = datetime.combine(day, time(), SGT)
    try:
        return Interval(base + timedelta(minutes=begin), base + timedelta(minutes=end))
    except OverflowError:
        return None


def _json_interval(value) -> Interval | None:
    if not isinstance(value, dict) or not {"start", "end"}.issubset(value):
        return None
    try:
        return Interval(
            _aware(datetime.fromisoformat(value["start"])),
            _aware(datetime.fromisoformat(value["end"])),
        )
    except (TypeError, ValueError):
        return None


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _time(value) -> time:
    return value if isinstance(value, time) else time.fromisoformat(value)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def downgrade():
    op.drop_index("ix_venue_booking_review_findings_active", table_name=TABLE)
    op.drop_table(TABLE)
