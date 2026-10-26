"""Shared SQLAlchemy metadata for approved ConnectSphere product stories."""

from datetime import date, datetime, time
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.event_statuses import INITIAL_STATUS, status_check_constraint


class Base(DeclarativeBase):
    pass


# CS-E19-S1 (SPL-114) database rules for attendee registration settings. The migration imports
# these same strings, so the model and the real database enforce identical rules. They are a
# second line of defence behind the route's own checks in app/registration_settings.py:
# - complete: the three settings are either all empty (registration off) or all set, never half.
# - period: registration opens strictly before it closes.
# - capacity: at least one place.
REGISTRATION_SETTINGS_COMPLETE = (
    "(registration_opens_at is null and registration_closes_at is null"
    " and registration_capacity is null)"
    " or (registration_opens_at is not null and registration_closes_at is not null"
    " and registration_capacity is not null)"
)
REGISTRATION_PERIOD_ORDER = (
    "registration_opens_at is null or registration_opens_at < registration_closes_at"
)
REGISTRATION_CAPACITY_POSITIVE = "registration_capacity is null or registration_capacity >= 1"
# CS-E07-S3 (SPL-85). Who confirmed the event and when are recorded together or not at all.
CONFIRMATION_COMPLETE = (
    "(confirmed_by_account_id is null and confirmed_at is null)"
    " or (confirmed_by_account_id is not null and confirmed_at is not null)"
)
# CS-E07-S5 (SPL-86). Who cancelled the event, when and why are recorded together or not at all.
CANCELLATION_COMPLETE = (
    "(cancelled_by_account_id is null and cancelled_at is null and cancellation_reason is null)"
    " or (cancelled_by_account_id is not null and cancelled_at is not null"
    " and cancellation_reason is not null)"
)
# SPL-105. Who completed the event and when are recorded together; the optional closing note is
# never stored without them.
COMPLETION_RECORDED = (
    "(completed_by_account_id is null and completed_at is null and completion_note is null)"
    " or (completed_by_account_id is not null and completed_at is not null)"
)


class Role(StrEnum):
    EVENT_ORGANISER = "event_organiser"
    EVENT_OPERATIONS_MANAGER = "event_operations_manager"
    EVENT_COORDINATOR = "event_coordinator"
    VENUE_STAFF = "venue_staff"
    TECHNICAL_SUPPORT_STAFF = "technical_support_staff"
    SAFETY_OFFICER = "safety_officer"
    ATTENDEE = "attendee"


ROLE_VALUES = tuple(role.value for role in Role)


class Organisation(Base):
    """A client organisation whose event information is isolated from other clients."""

    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    accounts: Mapped[list["Account"]] = relationship(back_populates="organisation")
    event_requests: Mapped[list["EventRequest"]] = relationship(back_populates="organisation")


class Account(Base):
    """Application account keyed by the verified Supabase Auth user identifier."""

    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False, default="Unnamed account")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    organisation_id: Mapped[int | None] = mapped_column(
        ForeignKey("organisations.id"), nullable=True, index=True
    )
    organisation: Mapped[Organisation | None] = relationship(back_populates="accounts")
    event_requests: Mapped[list["EventRequest"]] = relationship(
        back_populates="organiser", foreign_keys="EventRequest.organiser_account_id"
    )


class AccountRole(Base):
    """One trusted role assignment; an account may hold several rows."""

    __tablename__ = "account_roles"
    __table_args__ = (
        CheckConstraint(
            "role in (" + ", ".join(repr(role) for role in ROLE_VALUES) + ")",
            name="ck_account_roles_known_role",
        ),
    )

    account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(40), primary_key=True)


class Venue(Base):
    """A venue catalogue record managed by authorised Venue Staff."""

    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    facilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    accessibility_features: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    operating_slots: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    setup_buffer_slots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    turnaround_buffer_slots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    setup_minutes: Mapped[int | None] = mapped_column(Integer)
    turnaround_minutes: Mapped[int | None] = mapped_column(Integer)
    operating_intervals: Mapped[list[list[int]] | None] = mapped_column(JSON)
    timing_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    layouts: Mapped[list["VenueLayout"]] = relationship(
        back_populates="venue", cascade="all, delete-orphan", order_by="VenueLayout.id"
    )
    operational_blocks: Mapped[list["VenueOperationalBlock"]] = relationship(
        back_populates="venue", cascade="all, delete-orphan", order_by="VenueOperationalBlock.id"
    )
    bookings: Mapped[list["VenueBooking"]] = relationship(back_populates="venue")


class VenueLayout(Base):
    """One supported layout and its stated capacity for a venue."""

    __tablename__ = "venue_layouts"
    __table_args__ = (UniqueConstraint("venue_id", "layout", name="uq_venue_layouts_venue_layout"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(
        ForeignKey("venues.id", ondelete="CASCADE"), nullable=False
    )
    layout: Mapped[str] = mapped_column(Text, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    venue: Mapped[Venue] = relationship(back_populates="layouts")


class VenueOperationalBlock(Base):
    """A Venue Staff record that removes dated operating slots from availability."""

    __tablename__ = "venue_operational_blocks"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_venue_blocks_date_order"),
        CheckConstraint(
            "(exact_start is null and exact_end is null) or "
            "(exact_start is not null and exact_end is not null and exact_end > exact_start)",
            name="ck_venue_blocks_exact_order",
        ),
    )
    exact_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exact_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(
        ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    slots: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    removed_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    venue: Mapped[Venue] = relationship(back_populates="operational_blocks")


class EventRequest(Base):
    """An organiser request, including an incomplete draft when not yet submitted."""

    __tablename__ = "event_requests"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="ck_event_requests_time_order"),
        CheckConstraint(
            "expected_attendance > 0",
            name="ck_event_requests_positive_attendance",
        ),
        CheckConstraint(
            status_check_constraint(),
            name="ck_event_requests_known_status",
        ),
        CheckConstraint(
            "(rejected_by_account_id is null and rejected_at is null and rejection_reason is null)"
            " or (rejected_by_account_id is not null and rejected_at is not null"
            " and rejection_reason is not null)",
            name="ck_event_requests_rejection_complete",
        ),
        CheckConstraint(
            "(withdrawn_by_account_id is null and withdrawn_at is null and withdrawal_note is null)"
            " or (withdrawn_by_account_id is not null and withdrawn_at is not null)",
            name="ck_event_requests_withdrawal_complete",
        ),
        CheckConstraint(
            "status <> 'submitted' or (purpose is not null "
            "and proposed_date is not null "
            "and start_time is not null "
            "and end_time is not null "
            "and expected_attendance is not null)",
            name="ck_event_requests_submitted_fields",
        ),
        CheckConstraint(
            REGISTRATION_SETTINGS_COMPLETE, name="ck_event_requests_registration_complete"
        ),
        CheckConstraint(REGISTRATION_PERIOD_ORDER, name="ck_event_requests_registration_period"),
        CheckConstraint(
            REGISTRATION_CAPACITY_POSITIVE, name="ck_event_requests_registration_capacity"
        ),
        CheckConstraint(CONFIRMATION_COMPLETE, name="ck_event_requests_confirmation_complete"),
        CheckConstraint(CANCELLATION_COMPLETE, name="ck_event_requests_cancellation_complete"),
        CheckConstraint(COMPLETION_RECORDED, name="ck_event_requests_completion_recorded"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organiser_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # SPL-108: coordinator-maintained ordinary event information. These fields deliberately sit
    # outside venue, equipment and registration configuration, whose changes have separate rules.
    event_notes: Mapped[str | None] = mapped_column(Text)
    event_contact_name: Mapped[str | None] = mapped_column(Text)
    event_contact_email: Mapped[str | None] = mapped_column(Text)
    event_contact_phone: Mapped[str | None] = mapped_column(Text)
    proposed_date: Mapped[date | None] = mapped_column(Date)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    expected_attendance: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=INITIAL_STATUS,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preferred_room_layout: Mapped[str | None] = mapped_column(Text)
    required_facilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    facilities_notes: Mapped[str | None] = mapped_column(Text)
    accessibility_needs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    location_preference: Mapped[str | None] = mapped_column(Text)
    venue_notes: Mapped[str | None] = mapped_column(Text)
    venue_id: Mapped[int | None] = mapped_column(
        ForeignKey("venues.id", ondelete="SET NULL"), nullable=True
    )
    registration_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    registration_notes: Mapped[str | None] = mapped_column(Text)
    # CS-E06-S4. Who approved the request and when; both stay null until it is approved.
    approved_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # CS-E06-S5. Who rejected the request, when and why; all three stay null unless it is rejected.
    rejected_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    # CS-E06-S6. Withdrawal keeps its actor and time; the accompanying note is optional.
    withdrawn_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawal_note: Mapped[str | None] = mapped_column(Text)
    # CS-E19-S1 (SPL-114). Attendee registration settings, set by the assigned coordinator. All
    # three stay null until registration is enabled, which is how "off by default" (AC5) is stored.
    # They live on the event so SPL-115/116 can read them without another table.
    registration_opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_capacity: Mapped[int | None] = mapped_column(Integer)
    # CS-E07-S3 (SPL-85). Who confirmed the event and when; both stay null until it is confirmed.
    confirmed_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # CS-E07-S5 (SPL-86). Who cancelled the event, when and why; all three stay null until then.
    cancelled_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    # SPL-105. Who completed the event and when, with the optional closing note.
    completed_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completion_note: Mapped[str | None] = mapped_column(Text)
    organiser: Mapped[Account] = relationship(
        back_populates="event_requests", foreign_keys=[organiser_account_id]
    )
    approver: Mapped[Account | None] = relationship(foreign_keys=[approved_by_account_id])
    rejecter: Mapped[Account | None] = relationship(foreign_keys=[rejected_by_account_id])
    withdrawer: Mapped[Account | None] = relationship(foreign_keys=[withdrawn_by_account_id])
    confirmer: Mapped[Account | None] = relationship(foreign_keys=[confirmed_by_account_id])
    canceller: Mapped[Account | None] = relationship(foreign_keys=[cancelled_by_account_id])
    completer: Mapped[Account | None] = relationship(foreign_keys=[completed_by_account_id])
    venue: Mapped["Venue | None"] = relationship()
    organisation: Mapped[Organisation] = relationship(back_populates="event_requests")
    equipment_requirements: Mapped[list["EquipmentRequirement"]] = relationship(
        back_populates="event_request",
        cascade="all, delete-orphan",
        order_by="EquipmentRequirement.id",
    )
    # SPL-97 records each committed equipment quantity separately.  The rows are retained so
    # availability can account for every overlapping commitment, rather than trusting a cached
    # number on the requirement.
    equipment_reservations: Mapped[list["EquipmentReservation"]] = relationship(
        back_populates="event_request", cascade="all, delete-orphan"
    )
    # CS-E05-S2. At most one coordinator is responsible at a time; the organiser is shown who.
    coordinator_assignment: Mapped["EventCoordinatorAssignment | None"] = relationship(
        back_populates="event_request", cascade="all, delete-orphan", uselist=False
    )
    venue_bookings: Mapped[list["VenueBooking"]] = relationship(
        back_populates="event_request", cascade="all, delete-orphan"
    )
    # CS-E06-S2. Newest first, so the latest question is the one shown and older ones remain.
    clarification_requests: Mapped[list["ClarificationRequest"]] = relationship(
        order_by="desc(ClarificationRequest.created_at), desc(ClarificationRequest.id)",
        cascade="all, delete-orphan",
    )
    safety_reviews: Mapped[list["SafetyReview"]] = relationship(
        back_populates="event_request", cascade="all, delete-orphan", order_by="SafetyReview.id"
    )


BOOKING_STATUSES = ("requested", "approved", "rejected", "withdrawn", "cancelled")
ACTIVE_BOOKING_STATUSES = ("requested", "approved")


class VenueBooking(Base):
    """Minimal booking aggregate shared by conflict-policy consumers."""

    __tablename__ = "venue_bookings"
    __table_args__ = (
        CheckConstraint(
            "status in (" + ", ".join(repr(status) for status in BOOKING_STATUSES) + ")",
            name="ck_venue_bookings_known_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    venue_id: Mapped[int] = mapped_column(
        ForeignKey("venues.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    requires_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    review_trigger_block_id: Mapped[int | None] = mapped_column(
        ForeignKey("venue_operational_blocks.id", ondelete="SET NULL")
    )
    review_marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_marked_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    # SPL-137 immutable request evidence; status controls whether this interval is active.
    exact_timing: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    reviewed_requirements: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    # SPL-77. The request as submitted, kept on the booking so it survives released occupancy.
    # Nullable because SPL-83/SPL-89 fixtures create bookings without a request.
    layout: Mapped[str | None] = mapped_column(Text)
    # SPL-131: how many of the event's attendees use this space (never more than the event's
    # expected attendance, Q119), and the facilities this space needs. Null facilities means the
    # booking recorded none of its own, so the event's required facilities apply (AC9).
    expected_attendance: Mapped[int | None] = mapped_column(Integer)
    required_facilities: Mapped[list[str] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    booking_date: Mapped[date | None] = mapped_column(Date)
    # jsonb, not json: SPL-89 selects DISTINCT bookings and json has no equality operator.
    event_slots: Mapped[list[str] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    setup_date: Mapped[date | None] = mapped_column(Date)
    setup_slot: Mapped[str | None] = mapped_column(String(10))
    turnaround_date: Mapped[date | None] = mapped_column(Date)
    turnaround_slot: Mapped[str | None] = mapped_column(String(10))
    requested_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # SPL-78. Who withdrew a Requested booking and when; both stay null unless withdrawn.
    withdrawn_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # SPL-81. Who approved a Requested booking, when, and the optional note; null unless approved.
    approved_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_note: Mapped[str | None] = mapped_column(Text)
    # SPL-82. Who rejected a Requested booking, when, the required reason and the optional
    # alternative suggestion; all four stay null unless rejected.
    rejected_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    rejection_alternative_suggestion: Mapped[str | None] = mapped_column(Text)
    event_request: Mapped[EventRequest] = relationship(back_populates="venue_bookings")
    venue: Mapped[Venue] = relationship(back_populates="bookings")
    occupancy: Mapped[list["VenueBookingOccupancy"]] = relationship(
        back_populates="booking",
        cascade="all, delete-orphan",
        order_by="VenueBookingOccupancy.id",
    )
    review_findings: Mapped[list["VenueBookingReviewFinding"]] = relationship(
        back_populates="booking",
        cascade="all, delete-orphan",
        order_by="VenueBookingReviewFinding.id",
    )


BOOKING_REVIEW_REASON_TYPES = (
    "overlap",
    "operational_block",
    "outside_operating_hours",
    "unresolved_historical_timing",
    "layout_capacity",
    "facilities",
    "accessibility",
    "location",
    "attendance",
    "event_times",
)


class VenueBookingReviewFinding(Base):
    """One persisted reason an active booking needs timing review (SPL-130).

    ``finding_key`` is stable for the underlying cause. Reassessment updates that row instead of
    duplicating it, while the resolution fields make every explicit clearance auditable.
    """

    __tablename__ = "venue_booking_review_findings"
    __table_args__ = (
        CheckConstraint(
            "reason_type in ("
            + ", ".join(repr(reason) for reason in BOOKING_REVIEW_REASON_TYPES)
            + ")",
            name="ck_venue_booking_review_findings_known_reason",
        ),
        UniqueConstraint("booking_id", "finding_key", name="uq_venue_booking_review_findings_key"),
        Index(
            "ix_venue_booking_review_findings_active",
            "booking_id",
            "resolved_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("venue_bookings.id", ondelete="CASCADE"), nullable=False
    )
    finding_key: Mapped[str] = mapped_column(String(120), nullable=False)
    reason_type: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    original_occupancy: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    current_occupancy: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    venue_timing_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    first_assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    booking: Mapped[VenueBooking] = relationship(back_populates="review_findings")


class VenueBookingStatusHistory(Base):
    """One venue-booking status change and who made it (SPL-79); rows are never edited."""

    __tablename__ = "venue_booking_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("venue_bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(40))
    resulting_status: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The reason (rejection) or note (approval) recorded with this action, if any.
    note: Mapped[str | None] = mapped_column(Text)


class VenueBookingOccupancy(Base):
    """One active event or preparation slot claimed by a venue booking."""

    __tablename__ = "venue_booking_occupancy"
    __table_args__ = (
        CheckConstraint(
            "slot in ('AM', 'PM', 'NIGHT')", name="ck_venue_booking_occupancy_known_slot"
        ),
        CheckConstraint(
            "kind in ('event', 'setup', 'turnaround')",
            name="ck_venue_booking_occupancy_known_kind",
        ),
        UniqueConstraint(
            "venue_id",
            "occupancy_date",
            "slot",
            name="uq_venue_booking_occupancy_venue_date_slot",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("venue_bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    venue_id: Mapped[int] = mapped_column(
        ForeignKey("venues.id", ondelete="RESTRICT"), nullable=False
    )
    day: Mapped[date] = mapped_column("occupancy_date", Date, nullable=False)
    slot: Mapped[str] = mapped_column(String(10), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    booking: Mapped[VenueBooking] = relationship(back_populates="occupancy")


class EquipmentRequirement(Base):
    """One retained organiser line or mapped coordinator equipment requirement."""

    __tablename__ = "equipment_requirements"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_equipment_requirements_positive_quantity"),
        CheckConstraint(
            "status in ('unmapped', 'requested', 'partially_reserved', 'reserved', "
            "'review_required', 'unavailable', 'removed')",
            name="ck_equipment_requirements_known_status",
        ),
        CheckConstraint(
            "essentiality in ('undecided', 'essential', 'non_essential')",
            name="ck_equipment_requirements_known_essentiality",
        ),
        # SPL-122 AC4: one line per add request, so a retried request cannot add a second line.
        UniqueConstraint(
            "event_request_id", "request_id", name="uq_equipment_requirements_request"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"), nullable=False
    )
    # The id the Add form sends with every attempt of one addition; null for older lines.
    request_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False))
    equipment_type: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    # The original organiser wording stays in ``equipment_type`` even after the line is mapped.
    # Catalogue identity, reservation state and dates are separate so later equipment stories do
    # not have to infer an inventory item from mutable free text.
    equipment_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("equipment_types.id", ondelete="RESTRICT"), index=True
    )
    required_start_date: Mapped[date | None] = mapped_column(Date)
    required_end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="unmapped", server_default="unmapped"
    )
    essentiality: Mapped[str] = mapped_column(
        String(20), nullable=False, default="undecided", server_default="undecided"
    )
    consulted_technical_support_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    essentiality_decision_note: Mapped[str | None] = mapped_column(Text)
    essentiality_decided_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    essentiality_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # SPL-96 AC3/AC4: why this line was marked Review Required, and when. The status itself lives
    # in ``status``; these two carry the explanation the coordinator and the review queue show.
    # Both are cleared together when SPL-97's revalidation clears the status, so a stale reason
    # can never outlive the flag.
    review_reason: Mapped[str | None] = mapped_column(Text)
    review_flagged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_request: Mapped[EventRequest] = relationship(back_populates="equipment_requirements")
    catalogue_type: Mapped["EquipmentType | None"] = relationship(foreign_keys=[equipment_type_id])
    consulted_technical_support: Mapped["Account | None"] = relationship(
        foreign_keys=[consulted_technical_support_account_id]
    )
    essentiality_decider: Mapped["Account | None"] = relationship(
        foreign_keys=[essentiality_decided_by_account_id]
    )
    reservations: Mapped[list["EquipmentReservation"]] = relationship(
        back_populates="equipment_requirement", cascade="all, delete-orphan"
    )
    review_notes: Mapped[list["EquipmentReviewNote"]] = relationship(
        back_populates="equipment_requirement",
        cascade="all, delete-orphan",
        order_by="EquipmentReviewNote.id",
    )
    # SPL-93 keeps a separate, append-only record of a line being unavailable and later restored.
    # The current status remains on this aggregate; the records preserve who made each decision
    # and why without overloading a stock-reservation or review-note history.
    unavailability_records: Mapped[list["EquipmentRequirementUnavailabilityRecord"]] = relationship(
        back_populates="equipment_requirement",
        cascade="all, delete-orphan",
        order_by="EquipmentRequirementUnavailabilityRecord.id",
    )


# SPL-96 AC1: the unavailable total can never exceed total stock or fall below zero. The rule
# lives here, as a database constraint, because two routes can move the two numbers it relates:
# SPL-96 changes ``unavailable_units`` and SPL-94's edit route changes ``total_stock``. A single
# constraint cannot be satisfied by one route and forgotten by the other.
UNAVAILABLE_WITHIN_STOCK = "unavailable_units >= 0 AND unavailable_units <= total_stock"


class EquipmentType(Base):
    """A pooled equipment type managed by Technical Support Staff."""

    __tablename__ = "equipment_types"
    __table_args__ = (
        CheckConstraint("total_stock >= 0", name="ck_equipment_types_non_negative_stock"),
        CheckConstraint(UNAVAILABLE_WITHIN_STOCK, name="ck_equipment_types_unavailable_in_stock"),
        UniqueConstraint("normalised_name", name="uq_equipment_types_normalised_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalised_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    total_stock: Mapped[int] = mapped_column(Integer, nullable=False)
    # SPL-96. Current state, not a schedule: units stay unavailable from when they are recorded
    # until they are restored, so this one figure applies to every day SPL-95 assesses.
    unavailable_units: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class EquipmentUnavailabilityRecord(Base):
    """One SPL-96 entry: units marked unavailable, or units restored, and why.

    The running total lives on ``EquipmentType.unavailable_units`` so the AC1 bounds can be a
    database constraint. This table is the history behind that number: AC1 asks for the reason,
    who and when on every change, including restorations.
    """

    __tablename__ = "equipment_unavailability_records"
    __table_args__ = (
        CheckConstraint(
            "quantity > 0", name="ck_equipment_unavailability_records_positive_quantity"
        ),
        CheckConstraint(
            "action in ('marked_unavailable', 'restored')",
            name="ck_equipment_unavailability_records_known_action",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_type_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_types.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_by_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    equipment_type: Mapped[EquipmentType] = relationship()


class EquipmentRequirementUnavailabilityRecord(Base):
    """One Technical Support decision to make an event requirement unavailable or restore it.

    This is deliberately distinct from ``EquipmentUnavailabilityRecord``. That table records
    physical stock taken out of service (SPL-96); this one records a workflow decision on one
    event line (SPL-93), and must never change the stock pool or a reservation.
    """

    __tablename__ = "equipment_requirement_unavailability_records"
    __table_args__ = (
        CheckConstraint(
            "action in ('marked_unavailable', 'restored_to_requested')",
            name="ck_equipment_requirement_unavailability_records_known_action",
        ),
        CheckConstraint(
            "action != 'marked_unavailable' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_equipment_requirement_unavailability_records_mark_reason",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_requirement_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    alternative_suggestion: Mapped[str | None] = mapped_column(Text)
    recorded_by_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    equipment_requirement: Mapped[EquipmentRequirement] = relationship(
        back_populates="unavailability_records"
    )
    recorded_by: Mapped[Account] = relationship(foreign_keys=[recorded_by_account_id])


class EquipmentReservation(Base):
    """One Technical Support stock commitment for a mapped event requirement (SPL-97)."""

    __tablename__ = "equipment_reservations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_equipment_reservations_positive_quantity"),
        CheckConstraint(
            "commitment_start_date <= commitment_end_date",
            name="ck_equipment_reservations_date_order",
        ),
        Index(
            "ix_equipment_reservations_type_commitment",
            "equipment_type_id",
            "commitment_start_date",
            "commitment_end_date",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    equipment_requirement_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    equipment_type_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    commitment_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    commitment_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_by_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # SPL-100 AC3: who last moved the planned return date, and when. The date itself is
    # ``commitment_end_date``, which SPL-97 already defaults to the requirement's required end
    # date (AC1); these two record only that someone changed it, so a reservation nobody has
    # edited reads as untouched rather than as edited by whoever reserved it.
    return_date_changed_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    return_date_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_request: Mapped[EventRequest] = relationship(back_populates="equipment_reservations")
    equipment_requirement: Mapped[EquipmentRequirement] = relationship(
        back_populates="reservations"
    )
    equipment_type: Mapped[EquipmentType] = relationship()
    reserved_by: Mapped[Account] = relationship(foreign_keys=[reserved_by_account_id])
    # SPL-98 keeps the original reservation immutable. Each later release is an appended audit
    # record, so availability can use the remaining quantity without losing who reserved it.
    releases: Mapped[list["EquipmentReservationRelease"]] = relationship(
        back_populates="reservation",
        cascade="all, delete-orphan",
        order_by="EquipmentReservationRelease.id",
    )


class EquipmentReservationRelease(Base):
    """One auditable partial or full release from an equipment reservation (SPL-98)."""

    __tablename__ = "equipment_reservation_releases"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_equipment_reservation_releases_positive_quantity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reservation_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_reservations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    released_by_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reservation: Mapped[EquipmentReservation] = relationship(back_populates="releases")
    released_by: Mapped[Account] = relationship(foreign_keys=[released_by_account_id])


class EquipmentRequirementChange(Base):
    """One coordinator change or removal of a requirement line, and what it released (SPL-91).

    AC4 asks for "the old and new values, who made it and when" on every change or removal. The
    values are stored as JSON because a change touches whichever fields the coordinator edited,
    and a fixed column per field would make most of each row empty.

    ``released_quantity`` records how many units this action gave back. The release rows
    themselves live in SPL-98's ``equipment_reservation_releases``, which stays the only place
    units are released; this column is the cross-reference that lets a reader see, from the line's
    own history, that a change cost it its reservation.
    """

    __tablename__ = "equipment_requirement_changes"
    __table_args__ = (
        CheckConstraint(
            "action in ('changed', 'removed')",
            name="ck_equipment_requirement_changes_known_action",
        ),
        CheckConstraint(
            "released_quantity >= 0",
            name="ck_equipment_requirement_changes_released_not_negative",
        ),
        Index(
            "ix_equipment_requirement_changes_requirement_changed",
            "equipment_requirement_id",
            "changed_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_requirement_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    old_values: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    new_values: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    released_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_by_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    changed_by: Mapped[Account] = relationship(foreign_keys=[changed_by_account_id])


# SPL-92 AC3: a note is saved with its author and time. The longest a reviewer may write; the
# same limit SPL-90 puts on a coordinator's technical notes, so the two read alike.
MAX_REVIEW_NOTE_LENGTH = 2_000


class EquipmentReviewNote(Base):
    """One Technical Support note or clarification question on a requirement line (SPL-92).

    Notes are additive and never edited or deleted: AC3 asks for the author and time, and the
    assigned coordinator reads them as a record of what was asked. A line's note history is
    therefore append-only, which is also why there is no status on this table.
    """

    __tablename__ = "equipment_review_notes"
    __table_args__ = (
        CheckConstraint("length(trim(note)) > 0", name="ck_equipment_review_notes_note_not_blank"),
        Index(
            "ix_equipment_review_notes_requirement_created",
            "equipment_requirement_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_requirement_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    author_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    equipment_requirement: Mapped[EquipmentRequirement] = relationship(
        back_populates="review_notes"
    )
    author: Mapped[Account] = relationship(foreign_keys=[author_account_id])


class EventCoordinatorAssignment(Base):
    """The single Event Coordinator currently responsible for an event request."""

    __tablename__ = "event_coordinator_assignments"

    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    coordinator_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    assigned_by_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_request: Mapped[EventRequest] = relationship(
        back_populates="coordinator_assignment", foreign_keys=[event_request_id]
    )
    coordinator: Mapped[Account] = relationship(foreign_keys=[coordinator_account_id])


class EventCoordinatorHistory(Base):
    """One assignment or reassignment, kept so the manager can audit responsibility changes."""

    __tablename__ = "event_coordinator_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    previous_coordinator_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    new_coordinator_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    changed_by_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EventStatusHistory(Base):
    """One server-authorised event status transition and its audit evidence."""

    __tablename__ = "event_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(40), nullable=False)
    resulting_status: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SafetyReview(Base):
    """An immutable Safety Officer decision over one confirmed arrangement snapshot.

    The plan belongs to the review submission rather than an untracked browser draft.  Its
    arrangement fingerprint prevents an old approval from unlocking Preparation after venue,
    attendance, or equipment details have changed.
    """

    __tablename__ = "safety_reviews"
    __table_args__ = (
        CheckConstraint(
            "status in ('submitted', 'approved', 'changes_requested', 'rejected')",
            name="ck_safety_reviews_known_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Four operational statements, each either has a value or a justified not-applicable choice.
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    arrangement_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="submitted")
    submitted_by_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    event_request: Mapped[EventRequest] = relationship(back_populates="safety_reviews")
    submitter: Mapped[Account] = relationship(foreign_keys=[submitted_by_account_id])
    decider: Mapped[Account | None] = relationship(foreign_keys=[decided_by_account_id])


class EventDetailChange(Base):
    """One atomic coordinator event edit; rows are append-only audit evidence."""

    __tablename__ = "event_detail_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Only fields whose normalized value changed are recorded. Each entry contains the prior and
    # resulting value, preserving an intelligible audit without snapshotting unrelated data.
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    changed_by_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    changed_by: Mapped[Account] = relationship(foreign_keys=[changed_by_account_id])


class RegistrationSettingsChange(Base):
    """One enabling or change of an event's registration settings (CS-E19-S1); never edited."""

    __tablename__ = "registration_settings_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # All three previous values are null for the first enabling.
    previous_opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_capacity: Mapped[int | None] = mapped_column(Integer)
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_by_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    changed_by: Mapped[Account] = relationship(foreign_keys=[changed_by_account_id])


# CS-E19-S3 (SPL-116). A registration is Registered until the attendee withdraws (SPL-118).
REGISTRATION_STATUSES = ("registered", "withdrawn")
# The database's own guarantee for SPL-116 AC5: at most one Registered row per attendee per event.
# It is a *partial* unique index (only rows WHERE status = 'registered'), so a Withdrawn row stays
# as history and the attendee can register again. Shared with the migration.
ONE_ACTIVE_REGISTRATION = "status = 'registered'"
# SPL-118: a Registered registration never carries a withdrawal time. The opposite direction (every
# Withdrawn row has a time) is guaranteed by the withdraw route, not here, because Withdrawn rows
# written before SPL-118 existed (fixtures and test data) have no time to record. Shared with the
# migration so the model and the database cannot drift apart.
REGISTERED_HAS_NO_WITHDRAWAL = "status = 'withdrawn' OR withdrawn_at IS NULL"


class EventRegistration(Base):
    """One attendee's registration for one event (CS-E19-S3). Rows are kept after withdrawal."""

    __tablename__ = "event_registrations"
    __table_args__ = (
        CheckConstraint(
            "status in (" + ", ".join(repr(status) for status in REGISTRATION_STATUSES) + ")",
            name="ck_event_registrations_known_status",
        ),
        CheckConstraint(
            REGISTERED_HAS_NO_WITHDRAWAL, name="ck_event_registrations_withdrawal_time"
        ),
        Index(
            "uq_event_registrations_one_active",
            "event_request_id",
            "attendee_account_id",
            unique=True,
            postgresql_where=text(ONE_ACTIVE_REGISTRATION),
            sqlite_where=text(ONE_ACTIVE_REGISTRATION),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Always the signed-in account; the browser never chooses whose registration this is.
    attendee_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="registered")
    # The details the attendee submitted (the team's proposed set, Q22).
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    contact_number: Mapped[str] = mapped_column(Text, nullable=False)
    special_requirements: Mapped[str | None] = mapped_column(Text)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # SPL-118 AC2: when the attendee withdrew. Empty while the registration is Registered.
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # SPL-117: lets "my registrations" load each event with its registration in one query.
    # Read-only navigation over the existing foreign key; no schema change.
    event_request: Mapped[EventRequest] = relationship()


class ClarificationRequest(Base):
    """One coordinator question and, once supplied, its organiser response evidence."""

    __table_args__ = (
        CheckConstraint(
            "(response is null and respondent_account_id is null and responded_at is null) or "
            "(response is not null and respondent_account_id is not null "
            "and responded_at is not null)",
            name="ck_clarification_requests_response_complete",
        ),
    )

    __tablename__ = "clarification_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    author_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    author: Mapped[Account] = relationship(foreign_keys=[author_account_id])
    response: Mapped[str | None] = mapped_column(Text)
    respondent_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    respondent: Mapped[Account | None] = relationship(foreign_keys=[respondent_account_id])


class Notification(Base):
    """One in-app notice for a single account (SPL-101); only its recipient may read it."""

    __tablename__ = "notifications"
    __table_args__ = (
        # One notice per recipient per triggering change, so a retry cannot add a duplicate.
        UniqueConstraint("recipient_account_id", "dedupe_key", name="uq_notifications_dedupe"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False, index=True
    )
    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Null means unread.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_request: Mapped[EventRequest] = relationship()


# SPL-111 (CS-E18-S1): a change request is Pending until a later story resolves it. Shared with the
# migration so the model and the database cannot drift apart.
CHANGE_REQUEST_STATUSES = ("pending", "closed")
ONE_PENDING_CHANGE_REQUEST = "status = 'pending'"


class EventChangeRequest(Base):
    """An organiser's request to change an event they already submitted (SPL-111).

    A request holds one or more items (``EventChangeRequestItem``). At most one request per event
    may be Pending at a time; the partial unique index enforces that even if two submissions race.
    """

    __tablename__ = "event_change_requests"
    __table_args__ = (
        CheckConstraint(
            "status in (" + ", ".join(repr(status) for status in CHANGE_REQUEST_STATUSES) + ")",
            name="ck_event_change_requests_known_status",
        ),
        Index(
            "uq_event_change_requests_one_pending",
            "event_request_id",
            unique=True,
            postgresql_where=text(ONE_PENDING_CHANGE_REQUEST),
            sqlite_where=text(ONE_PENDING_CHANGE_REQUEST),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # Always the signed-in organiser; the browser never chooses who submitted.
    submitted_by_account_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id"), nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    items: Mapped[list["EventChangeRequestItem"]] = relationship(
        back_populates="change_request",
        order_by="EventChangeRequestItem.id",
        cascade="all, delete-orphan",
    )


class EventChangeRequestItem(Base):
    """One field an organiser wants changed: its value when asked, the new value and why."""

    __tablename__ = "event_change_request_items"
    __table_args__ = (
        UniqueConstraint("change_request_id", "field", name="uq_event_change_request_items_field"),
        CheckConstraint(
            "(decision IS NULL AND decline_reason IS NULL AND decided_by_account_id IS NULL "
            "AND decided_at IS NULL) OR (decision IS NOT NULL AND "
            "decision IN ('accepted', 'declined') AND decided_by_account_id IS NOT NULL "
            "AND decided_at IS NOT NULL AND ((decision = 'accepted' AND decline_reason IS NULL) "
            "OR (decision = 'declined' AND decline_reason IS NOT NULL "
            "AND length(trim(decline_reason)) > 0)))",
            name="ck_change_request_item_decision",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    change_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_change_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field: Mapped[str] = mapped_column(String(40), nullable=False)
    # The event's value at submission, so the coordinator sees what is being replaced even if the
    # event is edited afterwards.
    current_value: Mapped[Any] = mapped_column(JSON)
    requested_value: Mapped[Any] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str | None] = mapped_column(String(20))
    decline_reason: Mapped[str | None] = mapped_column(Text)
    decided_by_account_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("accounts.id")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped["Account | None"] = relationship(foreign_keys=[decided_by_account_id])
    change_request: Mapped[EventChangeRequest] = relationship(back_populates="items")
