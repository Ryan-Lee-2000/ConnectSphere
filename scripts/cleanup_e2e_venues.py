"""Remove disposable browser-test records from the local development database only."""

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

from app.models import EquipmentRequirement, EquipmentType, EventRequest, Venue  # noqa: E402

engine = create_engine(database_url)
try:
    with Session(engine) as session:
        # SPL-97 creates three named fixture events to demonstrate successful and refused
        # revalidation. Delete their parent records first so database cascades remove each
        # requirement and reservation before the matching catalogue types are removed.
        equipment_events = session.scalars(
            select(EventRequest).where(EventRequest.name.like("E2E SPL-97 %"))
        ).all()
        if equipment_events:
            session.execute(
                delete(EventRequest).where(
                    EventRequest.id.in_([event.id for event in equipment_events])
                )
            )
            session.commit()
            print(f"Removed {len(equipment_events)} local SPL-97 evidence event(s).")

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

        test_equipment = session.scalars(
            select(EquipmentType).where(EquipmentType.name.like("E2E %"))
        ).all()
        if test_equipment:
            names = ", ".join(item.name for item in test_equipment)
            equipment_ids = [item.id for item in test_equipment]
            session.execute(delete(EquipmentType).where(EquipmentType.id.in_(equipment_ids)))
            session.commit()
            print(f"Removed {len(test_equipment)} local E2E equipment type(s): {names}")
        else:
            print("No local E2E equipment types required cleanup.")

        # SPL-90 recorded UAT adds then soft-removes a line to demonstrate retained history.
        # Delete only its clearly marked local evidence records after the browser run.
        evidence_requirements = session.scalars(
            select(EquipmentRequirement).where(
                EquipmentRequirement.notes.like("E2E UAT equipment requirement %")
            )
        ).all()
        if evidence_requirements:
            session.execute(
                delete(EquipmentRequirement).where(
                    EquipmentRequirement.id.in_([item.id for item in evidence_requirements])
                )
            )
            session.commit()
            print(f"Removed {len(evidence_requirements)} local E2E equipment requirement(s).")
        else:
            print("No local E2E equipment requirements required cleanup.")
finally:
    engine.dispose()
