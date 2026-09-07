"""Create one local-only Auth fixture for infrastructure checks, without business roles."""

import os
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()
api = os.environ["SUPABASE_URL"]
if urlparse(api).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("Seed is local-only")
secret = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
email = "developer@example.test"
with httpx.Client(base_url=api, headers=headers, timeout=15) as client:
    page = 1
    found = False
    while True:
        response = client.get("/auth/v1/admin/users", params={"page": page, "per_page": 100})
        response.raise_for_status()
        users = response.json()["users"]
        found = found or any(user.get("email") == email for user in users)
        if len(users) < 100:
            break
        page += 1
    if not found:
        response = client.post(
            "/auth/v1/admin/users",
            json={"email": email, "password": "LocalDemo123!", "email_confirm": True},
        )
        response.raise_for_status()
print("Local Auth test fixture ready. No business records or roles seeded.")
