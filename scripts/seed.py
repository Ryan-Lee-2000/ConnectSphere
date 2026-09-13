"""Create the local-only Auth fixture and its approved S2 role assignments."""

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
email = "developer@example.test"
with httpx.Client(base_url=api, headers=headers, timeout=15) as client:
    page = 1
    fixture_user = None
    while True:
        response = client.get("/auth/v1/admin/users", params={"page": page, "per_page": 100})
        response.raise_for_status()
        users = response.json()["users"]
        fixture_user = fixture_user or next(
            (user for user in users if user.get("email") == email), None
        )
        if len(users) < 100:
            break
        page += 1
    if fixture_user is None:
        response = client.post(
            "/auth/v1/admin/users",
            json={"email": email, "password": "LocalDemo123!", "email_confirm": True},
        )
        response.raise_for_status()
        fixture_user = response.json()

engine = create_engine(os.environ["DATABASE_URL"])
try:
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO accounts (id) VALUES (:id) ON CONFLICT (id) DO NOTHING"),
            {"id": fixture_user["id"]},
        )
        for role in ("event_organiser", "attendee"):
            connection.execute(
                text(
                    "INSERT INTO account_roles (account_id, role) VALUES (:id, :role) "
                    "ON CONFLICT (account_id, role) DO NOTHING"
                ),
                {"id": fixture_user["id"], "role": role},
            )
finally:
    engine.dispose()

print("Local Auth test fixture ready with event_organiser and attendee roles.")
