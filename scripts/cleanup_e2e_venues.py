"""Remove disposable browser-test venues from the local development database only."""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, delete, or_, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

database_url = os.environ["DATABASE_URL"]
if urlparse(database_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("E2E cleanup is local-only and refuses a non-local database.")

from app.models import Venue  # noqa: E402

engine = create_engine(database_url)
try:
    with Session(engine) as session:
        test_venues = session.scalars(
            select(Venue).where(
                or_(Venue.name.like("E2E %"), Venue.location == "E2E Test Location")
            )
        ).all()
        if test_venues:
            names = ", ".join(venue.name for venue in test_venues)
            session.execute(delete(Venue).where(Venue.id.in_([venue.id for venue in test_venues])))
            session.commit()
            print(f"Removed {len(test_venues)} local E2E venue(s): {names}")
        else:
            print("No local E2E venues required cleanup.")
finally:
    engine.dispose()
