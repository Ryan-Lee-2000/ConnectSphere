"""Create local-only Auth fixtures with trusted application role assignments."""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

load_dotenv()
api = os.environ["SUPABASE_URL"]
if urlparse(api).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("Seed is local-only")
secret = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
fixtures = {
    "developer@example.test": ("event_organiser", "attendee"),
    "venue.staff@example.test": ("venue_staff",),
    "event.coordinator@example.test": ("event_coordinator",),
}
with httpx.Client(base_url=api, headers=headers, timeout=15) as client:
    page = 1
    users_by_email = {}
    while True:
        response = client.get("/auth/v1/admin/users", params={"page": page, "per_page": 100})
        response.raise_for_status()
        users = response.json()["users"]
        users_by_email.update(
            {user["email"]: user for user in users if user.get("email") in fixtures}
        )
        if len(users) < 100:
            break
        page += 1
    for email in fixtures:
        if email not in users_by_email:
            response = client.post(
                "/auth/v1/admin/users",
                json={"email": email, "password": "LocalDemo123!", "email_confirm": True},
            )
            response.raise_for_status()
            users_by_email[email] = response.json()

from app.models import Venue, VenueLayout  # noqa: E402

DUMMY_VENUES = [
    {
        "name": "Harbour Hall",
        "location": "Level 3, Marina Centre",
        "description": "A large flexible hall suited to full-day events.",
        "facilities": ["Projector", "PA system", "Stage"],
        "accessibility_features": ["Step-free access", "Accessible restroom"],
        "operating_slots": ["AM", "PM", "NIGHT"],
        "setup_buffer_slots": 1,
        "turnaround_buffer_slots": 1,
        "layouts": [
            {"layout": "theatre", "capacity": 200},
            {"layout": "classroom", "capacity": 120},
        ],
    },
    {
        "name": "Riverside Room",
        "location": "Level 1, Riverside Annex",
        "description": "A quiet daytime meeting room.",
        "facilities": ["Whiteboard", "Video conferencing"],
        "accessibility_features": ["Step-free access"],
        "operating_slots": ["AM", "PM"],
        "setup_buffer_slots": 0,
        "turnaround_buffer_slots": 0,
        "layouts": [
            {"layout": "boardroom", "capacity": 20},
            {"layout": "classroom", "capacity": 40},
        ],
    },
    {
        "name": "Skyline Terrace",
        "location": "Rooftop, Marina Centre",
        "description": "An open-air terrace popular for evening receptions.",
        "facilities": ["PA system", "String lighting"],
        "accessibility_features": ["Step-free access"],
        "operating_slots": ["NIGHT"],
        "setup_buffer_slots": 1,
        "turnaround_buffer_slots": 0,
        "layouts": [{"layout": "banquet", "capacity": 150}],
    },
    {
        "name": "The Annex",
        "location": "Level 2, Riverside Annex",
        "description": "A compact space for morning workshops and exhibitions.",
        "facilities": ["Projector"],
        "accessibility_features": [],
        "operating_slots": ["AM"],
        "setup_buffer_slots": 0,
        "turnaround_buffer_slots": 0,
        "layouts": [{"layout": "exhibition", "capacity": 80}],
    },
    {
        "name": "Grand Ballroom",
        "location": "Level 5, Marina Centre",
        "description": "The largest venue, suited to conferences and galas.",
        "facilities": ["Projector", "PA system", "Stage", "Video conferencing"],
        "accessibility_features": ["Step-free access", "Accessible restroom", "Hearing loop"],
        "operating_slots": ["AM", "PM", "NIGHT"],
        "setup_buffer_slots": 1,
        "turnaround_buffer_slots": 1,
        "layouts": [{"layout": "banquet", "capacity": 400}, {"layout": "theatre", "capacity": 500}],
    },
]

engine = create_engine(os.environ["DATABASE_URL"])
try:
    with engine.begin() as connection:
        for email, roles in fixtures.items():
            user_id = users_by_email[email]["id"]
            connection.execute(
                text("INSERT INTO accounts (id) VALUES (:id) ON CONFLICT (id) DO NOTHING"),
                {"id": user_id},
            )
            for role in roles:
                connection.execute(
                    text(
                        "INSERT INTO account_roles (account_id, role) VALUES (:id, :role) "
                        "ON CONFLICT (account_id, role) DO NOTHING"
                    ),
                    {"id": user_id, "role": role},
                )

    with Session(engine) as session:
        if session.scalar(select(func.count()).select_from(Venue)) == 0:
            for entry in DUMMY_VENUES:
                layouts = entry.pop("layouts")
                venue = Venue(**entry)
                venue.layouts = [VenueLayout(**layout) for layout in layouts]
                session.add(venue)
            session.commit()
            print(f"Seeded {len(DUMMY_VENUES)} dummy venue(s).")
        else:
            print("Venues table is not empty; skipped dummy venue seeding.")
finally:
    engine.dispose()

print("Local Auth fixtures ready for organiser, venue staff and event coordinator roles.")
