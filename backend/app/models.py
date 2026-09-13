"""Shared SQLAlchemy metadata for approved ConnectSphere product stories."""

from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
