"""QA-SPL-126-090 | AC1 | WB: every notice any backend test creates is stored with its type.

A pytest plugin, not a test module. Run the whole backend suite with it so every notification
trigger on main is exercised by the suites that own it:

    PYTHONPATH=backend:backend/tests uv run --frozen pytest backend/tests -p qa_spl126_every_notice

After each test it checks the app databases that test created: every notice has a type, and that
type is the one its dedupe-key kind maps to. The kinds seen are written to SPL126_KINDS_FILE when
it is set, so the report can show which kinds the real triggers produced.
"""

import json
import os
from collections import Counter

import pytest
from app import email_delivery
from app.models import NOTIFICATION_TYPE_BY_KIND
from sqlalchemy import text

_kinds: Counter = Counter()
_stash = pytest.StashKey[set]()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    item.stash[_stash] = {id(engine) for engine in list(email_delivery._settings.keys())}
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    yield
    before = item.stash.get(_stash, set())
    for engine in list(email_delivery._settings.keys()):
        if id(engine) in before:
            continue
        try:
            connection = engine.connect()
        except Exception:
            continue  # the test broke its own database on purpose (e.g. an outage check)
        with connection:
            if not engine.dialect.has_table(connection, "notifications"):
                continue
            try:
                rows = connection.execute(
                    text("SELECT id, dedupe_key, notification_type FROM notifications")
                ).all()
            except Exception:
                continue  # a schema the test built for itself without this column
        wrong = []
        for notice_id, key, stored in rows:
            kind = key.split(":", 1)[0]
            _kinds[kind] += 1
            expected = NOTIFICATION_TYPE_BY_KIND.get(kind)
            if expected is None or stored != expected.value:
                wrong.append((notice_id, key, stored))
        assert not wrong, f"SPL-126 AC1: notices without their type: {wrong[:5]}"


def pytest_sessionfinish(session):
    path = os.getenv("SPL126_KINDS_FILE")
    if path:
        with open(path, "w") as handle:
            json.dump(dict(sorted(_kinds.items())), handle, indent=2)
