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
    event_requests: Mapped[list["EventRequest"]] = relationship(back_populates="organiser")


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
    layouts: Mapped[list["VenueLayout"]] = relationship(
        back_populates="venue", cascade="all, delete-orphan", order_by="VenueLayout.id"
    )
    operational_blocks: Mapped[list["VenueOperationalBlock"]] = relationship(
        back_populates="venue", cascade="all, delete-orphan", order_by="VenueOperationalBlock.id"
    )


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
    __table_args__ = (CheckConstraint("end_date >= start_date", name="ck_venue_blocks_date_order"),)

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
    accessibility_needs: Mapped[str | None] = mapped_column(Text)
    location_preference: Mapped[str | None] = mapped_column(Text)
    venue_notes: Mapped[str | None] = mapped_column(Text)
    venue_id: Mapped[int | None] = mapped_column(
        ForeignKey("venues.id", ondelete="SET NULL"), nullable=True
    )
    registration_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    registration_notes: Mapped[str | None] = mapped_column(Text)
    organiser: Mapped[Account] = relationship(back_populates="event_requests")
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


class EquipmentRequirement(Base):
    """One free-text equipment line requested for an event."""

    __tablename__ = "equipment_requirements"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_equipment_requirements_positive_quantity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_request_id: Mapped[int] = mapped_column(
        ForeignKey("event_requests.id", ondelete="CASCADE"), nullable=False
    )
    equipment_type: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    event_request: Mapped[EventRequest] = relationship(back_populates="equipment_requirements")


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
