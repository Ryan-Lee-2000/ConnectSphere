"""Shared SQLAlchemy metadata for approved ConnectSphere product stories."""

from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.event_statuses import INITIAL_STATUS, status_check_constraint


class Base(DeclarativeBase):
    pass


class Role(StrEnum):
    EVENT_ORGANISER = "event_organiser"
    EVENT_OPERATIONS_MANAGER = "event_operations_manager"
    EVENT_COORDINATOR = "event_coordinator"
    VENUE_STAFF = "venue_staff"
    TECHNICAL_SUPPORT_STAFF = "technical_support_staff"
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
    organiser: Mapped[Account] = relationship(
        back_populates="event_requests", foreign_keys=[organiser_account_id]
    )
    approver: Mapped[Account | None] = relationship(foreign_keys=[approved_by_account_id])
    rejecter: Mapped[Account | None] = relationship(foreign_keys=[rejected_by_account_id])
    withdrawer: Mapped[Account | None] = relationship(foreign_keys=[withdrawn_by_account_id])
    venue: Mapped["Venue | None"] = relationship()
    organisation: Mapped[Organisation] = relationship(back_populates="event_requests")
    equipment_requirements: Mapped[list["EquipmentRequirement"]] = relationship(
        back_populates="event_request",
        cascade="all, delete-orphan",
        order_by="EquipmentRequirement.id",
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
    expected_attendance: Mapped[int | None] = mapped_column(Integer)
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
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"), nullable=False
    )
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
    event_request: Mapped[EventRequest] = relationship(back_populates="equipment_requirements")
    catalogue_type: Mapped["EquipmentType | None"] = relationship(foreign_keys=[equipment_type_id])
    consulted_technical_support: Mapped["Account | None"] = relationship(
        foreign_keys=[consulted_technical_support_account_id]
    )
    essentiality_decider: Mapped["Account | None"] = relationship(
        foreign_keys=[essentiality_decided_by_account_id]
    )


class EquipmentType(Base):
    """A pooled equipment type managed by Technical Support Staff."""

    __tablename__ = "equipment_types"
    __table_args__ = (
        CheckConstraint("total_stock >= 0", name="ck_equipment_types_non_negative_stock"),
        UniqueConstraint("normalised_name", name="uq_equipment_types_normalised_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalised_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    total_stock: Mapped[int] = mapped_column(Integer, nullable=False)


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
