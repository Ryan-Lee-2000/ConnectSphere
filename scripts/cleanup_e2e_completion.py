"""Remove only the disposable local SPL-105 evidence events."""
# ruff: noqa: E501

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
load_dotenv(ROOT / ".env")

from app.models import EmailDelivery, EventRequest, EventStatusHistory, Notification  # noqa: E402

database_url = os.environ["DATABASE_URL"]
if urlparse(database_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("SPL-105 cleanup is local-only and refuses a non-local database.")

engine = create_engine(database_url)
try:
    with Session(engine) as session, session.begin():
        ids = session.scalars(
            select(EventRequest.id).where(EventRequest.name.like("E2E SPL-105 %"))
        ).all()
        if ids:
            session.execute(
                delete(EventStatusHistory).where(EventStatusHistory.event_request_id.in_(ids))
            )
            # SPL-125: email records block deleting their notices, which the event delete cascades to.
            session.execute(
                delete(EmailDelivery).where(
                    EmailDelivery.notification_id.in_(
                        select(Notification.id).where(Notification.event_request_id.in_(ids))
                    )
                )
            )
            for event in session.scalars(select(EventRequest).where(EventRequest.id.in_(ids))):
                session.delete(event)
finally:
    engine.dispose()
