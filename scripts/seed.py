"""Create local-only Auth fixtures with trusted application role assignments."""

import os
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
api = os.environ["SUPABASE_URL"]
if urlparse(api).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("Seed is local-only")
secret = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
fixtures = {
    "developer@example.test": {
        "display_name": "Devon Lee",
        "organisation": "Northstar Community Partners",
        "roles": ("event_organiser", "attendee"),
    },
    "venue.staff@example.test": {
        "display_name": "Valerie Tan",
        "organisation": None,
        "roles": ("venue_staff",),
    },
    "event.coordinator@example.test": {
        "display_name": "Casey Lim",
        "organisation": None,
        "roles": ("event_coordinator",),
    },
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

engine = create_engine(os.environ["DATABASE_URL"])
try:
    with engine.begin() as connection:
        for email, fixture in fixtures.items():
            user_id = users_by_email[email]["id"]
            organisation_id = None
            if fixture["organisation"]:
                organisation_id = connection.execute(
                    text(
                        "INSERT INTO organisations (name) VALUES (:name) "
                        "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"
                    ),
                    {"name": fixture["organisation"]},
                ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO accounts (id, display_name, organisation_id) "
                    "VALUES (:id, :display_name, :organisation_id) "
                    "ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name, "
                    "organisation_id = EXCLUDED.organisation_id"
                ),
                {
                    "id": user_id,
                    "display_name": fixture["display_name"],
                    "organisation_id": organisation_id,
                },
            )
            for role in fixture["roles"]:
                connection.execute(
                    text(
                        "INSERT INTO account_roles (account_id, role) VALUES (:id, :role) "
                        "ON CONFLICT (account_id, role) DO NOTHING"
                    ),
                    {"id": user_id, "role": role},
                )
finally:
    engine.dispose()

print("Local Auth fixtures ready for organiser, venue staff and event coordinator roles.")
