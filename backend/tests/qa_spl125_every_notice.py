"""QA-SPL-125-007 | AC1 | WB: every notice any backend test creates has exactly one email.

A pytest plugin, not a test module. Run the whole backend suite with it so every notification
type on main is exercised by the suites that own it:

    PYTHONPATH=backend:backend/tests uv run --frozen pytest backend/tests -p qa_spl125_every_notice

After each test it checks the app databases that test created: each notice has exactly one
email_deliveries row. The notice kinds seen are written to SPL125_KINDS_FILE when it is set.
"""

import json
import os
from collections import Counter

import pytest
from app import email_delivery
from sqlalchemy import text

_kinds: Counter = Counter()
_checked = Counter()
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
            if not engine.dialect.has_table(connection, "email_deliveries"):
                continue
            rows = connection.execute(
                text(
                    "SELECT n.id, n.dedupe_key, count(e.id) FROM notifications n "
                    "LEFT JOIN email_deliveries e ON e.notification_id = n.id "
                    "GROUP BY n.id, n.dedupe_key"
                )
            ).all()
            orphans = connection.scalar(
                text(
                    "SELECT count(*) FROM email_deliveries e WHERE NOT EXISTS "
                    "(SELECT 1 FROM notifications n WHERE n.id = e.notification_id)"
                )
            )
        wrong = [(notice_id, key, count) for notice_id, key, count in rows if count != 1]
        assert not wrong, f"SPL-125 AC1: notices without exactly one email: {wrong[:5]}"
        assert orphans == 0
        for _notice_id, key, _count in rows:
            _kinds[key.split(":", 1)[0]] += 1
        _checked["tests"] += 1
        _checked["notices"] += len(rows)


def pytest_sessionfinish(session):
    target = os.getenv("SPL125_KINDS_FILE")
    if target:
        with open(target, "w") as handle:
            json.dump({"checked": dict(_checked), "kinds": dict(sorted(_kinds.items()))}, handle)
