"""Remove only the disposable local SPL-136 UAT events."""

import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
load_dotenv(ROOT / ".env")

from app.models import EventRequest  # noqa: E402

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
        for event in session.scalars(
            select(EventRequest).where(EventRequest.name.like(f"E2E SPL-136 {run_id} %"))
        ).all():
            session.delete(event)
finally:
    engine.dispose()
