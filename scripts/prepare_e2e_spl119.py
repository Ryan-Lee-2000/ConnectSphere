"""Prepare local-only real-Auth browser fixtures for SPL-119 recorded QA."""

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
    EventRegistration,
    EventRequest,
    Notification,
    Organisation,
    Role,
)

database_url = os.environ["DATABASE_URL"]
api_url = os.environ["SUPABASE_URL"]
if urlparse(database_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("SPL-119 browser fixtures require a local database.")
if urlparse(api_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("SPL-119 browser fixtures require local Supabase Auth.")

secret = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
auth_headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
fixture_password = "LocalDemo123!"


def auth_user_id(client: httpx.Client, email: str) -> str:
    page = 1
    while True:
        response = client.get("/auth/v1/admin/users", params={"page": page, "per_page": 100})
        response.raise_for_status()
        users = response.json()["users"]
        for user in users:
            if user.get("email") == email:
                return user["id"]
        if len(users) < 100:
            break
        page += 1
    response = client.post(
        "/auth/v1/admin/users",
        json={"email": email, "password": fixture_password, "email_confirm": True},
    )
    response.raise_for_status()
    return response.json()["id"]


with httpx.Client(base_url=api_url, headers=auth_headers, timeout=15) as auth:
    organiser_id = auth_user_id(auth, "developer@example.test")
    outsider_id = auth_user_id(auth, "qa.spl119.other-organiser@example.test")

engine = create_engine(database_url)
try:
    with Session(engine) as session, session.begin():
        # SPL-125: email records block deleting their notices, which the event delete cascades to.
        session.execute(
            delete(EmailDelivery).where(
                EmailDelivery.notification_id.in_(
                    select(Notification.id).where(
                        Notification.event_request_id.in_(
                            select(EventRequest.id).where(EventRequest.name.like("SPL-119 UAT %"))
                        )
                    )
                )
            )
        )
        for event in session.scalars(
            select(EventRequest).where(EventRequest.name.like("SPL-119 UAT %"))
        ).all():
            session.delete(event)
        session.flush()

        organiser = session.get(Account, organiser_id)
        if organiser is None or organiser.organisation_id is None:
            raise SystemExit(
                "Run npm run setup first: the organiser fixture needs an organisation."
            )

        other_org = session.scalar(
            select(Organisation).where(Organisation.name == "SPL-119 Other Client")
        )
        if other_org is None:
            other_org = Organisation(name="SPL-119 Other Client")
            session.add(other_org)
            session.flush()
        outsider = session.get(Account, outsider_id)
        if outsider is None:
            outsider = Account(
                id=outsider_id,
                display_name="Oscar Other Organiser",
                organisation_id=other_org.id,
            )
            session.add(outsider)
        else:
            outsider.display_name = "Oscar Other Organiser"
            outsider.organisation_id = other_org.id
            outsider.is_active = True
        session.execute(delete(AccountRole).where(AccountRole.account_id == outsider_id))
        session.add(AccountRole(account_id=outsider_id, role=Role.EVENT_ORGANISER.value))

        synthetic_accounts = [
            ("00000000-0000-0000-0000-000000001196", "Blake Ong"),
            ("00000000-0000-0000-0000-000000001197", "Cheryl Tan"),
        ]
        for account_id, display_name in synthetic_accounts:
            account = session.get(Account, account_id)
            if account is None:
                session.add(Account(id=account_id, display_name=display_name))

        event = EventRequest(
            organiser_account_id=organiser.id,
            organisation_id=organiser.organisation_id,
            name="SPL-119 UAT Registration List",
            purpose="Recorded QA of organiser registration visibility",
            proposed_date=date(2026, 11, 20),
            start_time=time(14),
            end_time=time(17),
            expected_attendance=100,
            status="submitted",
            registration_opens_at=datetime(2026, 10, 1, 9, tzinfo=timezone.utc),
            registration_closes_at=datetime(2026, 11, 19, 18, tzinfo=timezone.utc),
            registration_capacity=5,
        )
        disabled = EventRequest(
            organiser_account_id=organiser.id,
            organisation_id=organiser.organisation_id,
            name="SPL-119 UAT Registration Disabled",
            purpose="Recorded QA of the disabled-registration explanation",
            proposed_date=date(2026, 11, 21),
            start_time=time(9),
            end_time=time(12),
            expected_attendance=40,
            status="submitted",
        )
        session.add_all([event, disabled])
        session.flush()
        signed_up = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        session.add_all(
            [
                EventRegistration(
                    event_request_id=event.id,
                    attendee_account_id="00000000-0000-0000-0000-000000001196",
                    status="registered",
                    name="Blake Ong",
                    email="blake@example.test",
                    contact_number="+65 9000 1196",
                    special_requirements="Vegetarian meal",
                    registered_at=signed_up,
                ),
                EventRegistration(
                    event_request_id=event.id,
                    attendee_account_id="00000000-0000-0000-0000-000000001197",
                    status="registered",
                    name="Cheryl Tan",
                    email="cheryl@example.test",
                    contact_number="+65 9000 1197",
                    special_requirements=None,
                    registered_at=signed_up,
                ),
                EventRegistration(
                    event_request_id=event.id,
                    attendee_account_id="00000000-0000-0000-0000-000000001196",
                    status="withdrawn",
                    name="Blake Ong (earlier registration)",
                    email="blake@example.test",
                    contact_number="+65 9000 1196",
                    special_requirements="Vegetarian meal",
                    registered_at=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
                    withdrawn_at=datetime(2026, 10, 20, 8, tzinfo=timezone.utc),
                ),
            ]
        )
        print(f"SPL119_EVENT_ID={event.id}")
        print(f"SPL119_DISABLED_EVENT_ID={disabled.id}")
finally:
    engine.dispose()
