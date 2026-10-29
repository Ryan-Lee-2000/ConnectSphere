"""Remove only the disposable local SPL-132 evidence event, venues, bookings and blocks."""
# ruff: noqa: E501

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
load_dotenv(ROOT / ".env")

database_url = os.environ["DATABASE_URL"]
if urlparse(database_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("SPL-132 cleanup is local-only and refuses a non-local database.")

from prepare_e2e_spl132 import remove_existing  # noqa: E402

engine = create_engine(database_url)
try:
    with Session(engine) as session, session.begin():
        remove_existing(session)
finally:
    engine.dispose()
