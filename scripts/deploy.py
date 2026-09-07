"""Deploy exact checked commit and verify liveness; no migration in app startup."""

import os
import time
from urllib.parse import urlparse

import httpx

service = os.environ["RENDER_SERVICE_ID"]
sha = os.environ["GITHUB_SHA"]
url = os.environ["DEMO_URL"].rstrip("/")
if urlparse(url).scheme != "https":
    raise SystemExit("DEMO_URL must use HTTPS")
with httpx.Client(
    base_url="https://api.render.com/v1",
    headers={"Authorization": "Bearer " + os.environ["RENDER_API_KEY"]},
    timeout=30,
) as client:
    response = client.post(
        f"/services/{service}/deploys", json={"commitId": sha, "clearCache": "do_not_clear"}
    )
    if response.status_code not in (200, 201, 202):
        raise SystemExit(f"Render trigger failed: HTTP {response.status_code}")
    deployment = response.json()["id"]
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        response = client.get(f"/services/{service}/deploys/{deployment}")
        if response.status_code != 200:
            raise SystemExit(f"Render status failed: HTTP {response.status_code}")
        data = response.json()
        status = data["status"]
        if status == "live":
            if data.get("commit", {}).get("id") != sha:
                raise SystemExit("Live deploy commit mismatch")
            break
        if status in ("build_failed", "update_failed", "canceled", "deactivated"):
            raise SystemExit(f"Render deployment failed: {status}")
        time.sleep(10)
    else:
        raise SystemExit("Render deployment timed out")
# Never send the Render credential to the application's URL.
for attempt in range(12):
    try:
        response = httpx.get(url + "/api/health", timeout=15)
        if response.status_code == 200 and response.json().get("status") == "ok":
            if response.json().get("commit") == sha:
                break
    except (httpx.RequestError, ValueError):
        pass
    time.sleep(10)
else:
    raise SystemExit("Deployed application health/commit check failed")
message = f"Deployed successfully\n\nDemo: {url}\n\nCommit: {sha}\n\nHealth: passed\n"
print(message)
if os.getenv("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as output:
        output.write(message)
