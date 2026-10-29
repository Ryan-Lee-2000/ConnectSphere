"""Prepare local-only real-Auth fixtures for the SPL-120 recorded QA walkthrough."""

import os
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

from app.models import (  # noqa: E402
    Account,
    AccountRole,
    EmailDelivery,
    EventCoordinatorAssignment,
    EventRegistration,
    EventRequest,
    Notification,
    Role,
)

database_url = os.environ["DATABASE_URL"]
api_url = os.environ["SUPABASE_URL"]
if urlparse(database_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("SPL-120 browser fixtures require a local database.")
if urlparse(api_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("SPL-120 browser fixtures require local Supabase Auth.")

auth_headers = {
    "apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    "Authorization": f"Bearer {os.environ['SUPABASE_SERVICE_ROLE_KEY']}",
}
auth_user_ids = {}
with httpx.Client(base_url=api_url, headers=auth_headers, timeout=15) as auth:
    page = 1
    while True:
        response = auth.get("/auth/v1/admin/users", params={"page": page, "per_page": 100})
        response.raise_for_status()
        users = response.json()["users"]
        auth_user_ids.update({user["email"]: user["id"] for user in users if user.get("email")})
        if len(users) < 100:
            break
        page += 1


def fixture_account(session: Session, email: str, role: Role) -> Account:
    account_id = auth_user_ids.get(email)
    account = session.get(Account, str(account_id)) if account_id is not None else None
    has_role = account and session.scalar(
        select(AccountRole.account_id).where(
            AccountRole.account_id == account.id,
            AccountRole.role == role.value,
        )
    )
    if account is None or not account.is_active or has_role is None:
        raise SystemExit(f"Run npm run setup first: the local {role.value} fixture is missing.")
    return account


engine = create_engine(database_url)
try:
    with Session(engine) as session, session.begin():
        # SPL-125: email records block deleting their notices, which the event delete cascades to.
        session.execute(
            delete(EmailDelivery).where(
                EmailDelivery.notification_id.in_(
                    select(Notification.id).where(
                        Notification.event_request_id.in_(
                            select(EventRequest.id).where(EventRequest.name.like("SPL-120 UAT %"))
                        )
                    )
                )
            )
        )
        for event in session.scalars(
            select(EventRequest).where(EventRequest.name.like("SPL-120 UAT %"))
        ).all():
            session.delete(event)
        session.flush()

        organiser = fixture_account(session, "developer@example.test", Role.EVENT_ORGANISER)
        manager = fixture_account(
            session, "operations.manager@example.test", Role.EVENT_OPERATIONS_MANAGER
        )
        coordinator = fixture_account(
            session, "event.coordinator@example.test", Role.EVENT_COORDINATOR
        )
        other_coordinator = fixture_account(
            session, "qa.coordinator.b@example.test", Role.EVENT_COORDINATOR
        )
        if organiser.organisation_id is None:
            raise SystemExit("The local Event Organiser fixture needs an organisation.")

        synthetic_accounts = [
            ("00000000-0000-0000-0000-000000001206", "Blake Ong"),
            ("00000000-0000-0000-0000-000000001207", "Cheryl Tan"),
        ]
        for account_id, display_name in synthetic_accounts:
            if session.get(Account, account_id) is None:
                session.add(Account(id=account_id, display_name=display_name))

        shared = {
            "organiser_account_id": organiser.id,
            "organisation_id": organiser.organisation_id,
            "proposed_date": date(2026, 11, 20),
            "start_time": time(14),
            "end_time": time(17),
            "expected_attendance": 80,
            "status": "planning",
        }
        visible = EventRequest(
            **shared,
            name="SPL-120 UAT Registration List",
            purpose="Recorded QA of coordinator registration visibility",
            registration_opens_at=datetime(2026, 10, 1, 9, tzinfo=timezone.utc),
            registration_closes_at=datetime(2026, 11, 19, 18, tzinfo=timezone.utc),
            registration_capacity=5,
        )
        disabled = EventRequest(
            **shared,
            name="SPL-120 UAT Registration Disabled",
            purpose="Recorded QA of the disabled-registration explanation",
        )
        protected = EventRequest(
            **shared,
            id=12_000_003,
            name="SPL-120 UAT Other Coordinator Event",
            purpose="Recorded QA of current-assignment access refusal",
            registration_opens_at=datetime(2026, 10, 1, 9, tzinfo=timezone.utc),
            registration_closes_at=datetime(2026, 11, 19, 18, tzinfo=timezone.utc),
            registration_capacity=10,
        )
        session.add_all([visible, disabled, protected])
        session.flush()

        assigned_at = datetime(2026, 10, 20, 9, tzinfo=timezone.utc)
        session.add_all(
            [
                EventCoordinatorAssignment(
                    event_request_id=visible.id,
                    coordinator_account_id=coordinator.id,
                    assigned_by_account_id=manager.id,
                    assigned_at=assigned_at,
                ),
                EventCoordinatorAssignment(
                    event_request_id=disabled.id,
                    coordinator_account_id=coordinator.id,
                    assigned_by_account_id=manager.id,
                    assigned_at=assigned_at,
                ),
                EventCoordinatorAssignment(
                    event_request_id=protected.id,
                    coordinator_account_id=other_coordinator.id,
                    assigned_by_account_id=manager.id,
                    assigned_at=assigned_at,
                ),
            ]
        )
        session.add_all(
            [
                EventRegistration(
                    event_request_id=visible.id,
                    attendee_account_id=synthetic_accounts[0][0],
                    status="registered",
                    name="Blake Ong",
                    email="blake@example.test",
                    contact_number="+65 9000 1206",
                    special_requirements="Vegetarian meal",
                    registered_at=datetime(2026, 10, 20, 12, tzinfo=timezone.utc),
                ),
                EventRegistration(
                    event_request_id=visible.id,
                    attendee_account_id=synthetic_accounts[1][0],
                    status="registered",
                    name="Cheryl Tan",
                    email="cheryl@example.test",
                    contact_number="+65 9000 1207",
                    special_requirements=None,
                    registered_at=datetime(2026, 10, 20, 13, tzinfo=timezone.utc),
                ),
                EventRegistration(
                    event_request_id=visible.id,
                    attendee_account_id=synthetic_accounts[0][0],
                    status="withdrawn",
                    name="Blake Ong (earlier registration)",
                    email="blake@example.test",
                    contact_number="+65 9000 1206",
                    special_requirements="Vegetarian meal",
                    registered_at=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
                    withdrawn_at=datetime(2026, 10, 20, 8, tzinfo=timezone.utc),
                ),
            ]
        )
        print(f"SPL120_EVENT_ID={visible.id}")
        print(f"SPL120_DISABLED_EVENT_ID={disabled.id}")
        print(f"SPL120_PROTECTED_EVENT_ID={protected.id}")
finally:
    engine.dispose()
