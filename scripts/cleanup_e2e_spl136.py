"""Remove only the disposable local SPL-136 UAT events."""

import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
load_dotenv(ROOT / ".env")

from app.models import EmailDelivery, EventRequest, Notification  # noqa: E402

database_url = os.environ["DATABASE_URL"]
if urlparse(database_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("SPL-136 cleanup is local-only and refuses a non-local database.")
try:
    run_id = str(uuid.UUID(os.environ["SPL136_E2E_RUN_ID"]))
except (KeyError, ValueError):
    raise SystemExit("A valid SPL136_E2E_RUN_ID is required for isolated cleanup.") from None

engine = create_engine(database_url)
try:
    with Session(engine) as session, session.begin():
        run_events = EventRequest.name.like(f"E2E SPL-136 {run_id} %")
        # SPL-125: email records block deleting their notices, which the event delete cascades to.
        session.execute(
            delete(EmailDelivery).where(
                EmailDelivery.notification_id.in_(
                    select(Notification.id)
                    .join(EventRequest, Notification.event_request_id == EventRequest.id)
                    .where(run_events)
                )
            )
        )
        for event in session.scalars(select(EventRequest).where(run_events)).all():
            session.delete(event)
finally:
    engine.dispose()
