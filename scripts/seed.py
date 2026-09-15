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
    "developer@example.test": ("Local Developer", ("event_organiser", "attendee")),
    "venue.staff@example.test": ("Local Venue Staff", ("venue_staff",)),
    "event.coordinator@example.test": ("Local Event Coordinator", ("event_coordinator",)),
    "operations.manager@example.test": (
        "Local Operations Manager",
        ("event_operations_manager",),
    ),
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
        for email, (display_name, roles) in fixtures.items():
            user_id = users_by_email[email]["id"]
            connection.execute(
                text(
                    "INSERT INTO accounts (id, display_name) VALUES (:id, :name) "
                    "ON CONFLICT (id) DO UPDATE "
                    "SET display_name = COALESCE(accounts.display_name, EXCLUDED.display_name)"
                ),
                {"id": user_id, "name": display_name},
            )
            for role in roles:
                connection.execute(
                    text(
                        "INSERT INTO account_roles (account_id, role) VALUES (:id, :role) "
                        "ON CONFLICT (account_id, role) DO NOTHING"
                    ),
                    {"id": user_id, "role": role},
                )
finally:
    engine.dispose()

print(
    "Local Auth fixtures ready for organiser, venue staff, event coordinator and "
    "operations manager roles."
)
