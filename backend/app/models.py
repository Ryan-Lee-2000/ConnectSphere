"""Shared SQLAlchemy metadata for approved ConnectSphere product stories."""

from enum import StrEnum

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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


class Account(Base):
    """Application account keyed by the verified Supabase Auth user identifier."""

    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)


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
