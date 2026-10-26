"""SPL-122 QA cases on real PostgreSQL: simultaneous actions and real rollback.

SQLite serialises writes, so it cannot show a race. These run only under `npm run integration`
(INTEGRATION_DATABASE_URL), reusing SPL-85's throw-away database, seeded event (a Planning event
with an Essential line reserved 4 of 4) and race harness.
"""

import os
import uuid
from datetime import date, timedelta

import pytest
import test_event_confirmation_postgres as spl85
from app import notifications as notifications_module
from app.models import Account, AccountRole, EquipmentRequirement, EventRequest, Notification, Role
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

RUNS = 3
pg_url, engine = spl85.pg_url, spl85.engine


def _second_technical(engine, ids):
    ids["technical-2"] = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(Account(id=ids["technical-2"], display_name="technical-2"))
        session.add(
            AccountRole(account_id=ids["technical-2"], role=Role.TECHNICAL_SUPPORT_STAFF.value)
        )
        session.commit()


def _per_recipient(engine, ids, event_id):
    with Session(engine) as session:
        rows = session.execute(
            select(Notification.recipient_account_id, func.count())
            .where(Notification.event_request_id == event_id)
            .group_by(Notification.recipient_account_id)
        ).all()
    names = {value: name for name, value in ids.items()}
    return {names[recipient]: total for recipient, total in rows}


def _remove(event_id, line_id):
    return lambda client: client.delete(
        f"/api/event-requests/{event_id}/equipment-requirements/{line_id}",
        headers={"Authorization": "Bearer coordinator"},
    )


def _change(event_id, line_id, quantity):
    return lambda client: client.patch(
        f"/api/event-requests/{event_id}/equipment-requirements/{line_id}",
        json={"quantity": quantity},
        headers={"Authorization": "Bearer coordinator"},
    )


def _cancel(event_id, reason="Called off by the client."):
    return lambda client: client.post(
        f"/api/event-requests/{event_id}/cancel",
        json={"reason": reason},
        headers={"Authorization": "Bearer coordinator"},
    )


# QA-SPL-122-070 | AC4 | WB concurrency
def test_qa_spl_122_070_simultaneous_removals_notify_once(engine, pg_url):
    ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
    _second_technical(engine, ids)
    app = spl85._app(pg_url, ids)
    try:
        for run in range(RUNS):
            day = date(2027, 4, 2) + timedelta(days=run)
            event_id, line_id = spl85._seed_ready_event(
                engine, ids, organisation_id, venue_id, type_id, day
            )
            results = spl85._race(app, [_remove(event_id, line_id), _remove(event_id, line_id)])
            assert sorted(status for status, _ in results) == [200, 409], results
            assert _per_recipient(engine, ids, event_id) == {"technical": 1, "technical-2": 1}
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-122-071 | AC2 AC4 | WB concurrency
def test_qa_spl_122_071_simultaneous_cancellations_notify_once(engine, pg_url):
    ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
    _second_technical(engine, ids)
    app = spl85._app(pg_url, ids)
    try:
        for run in range(RUNS):
            day = date(2027, 5, 2) + timedelta(days=run)
            event_id, _ = spl85._seed_ready_event(
                engine, ids, organisation_id, venue_id, type_id, day
            )
            results = spl85._race(app, [_cancel(event_id), _cancel(event_id, "Duplicate click.")])
            assert sorted(status for status, _ in results) == [200, 409], results
            assert _per_recipient(engine, ids, event_id) == {
                "technical": 1,
                "technical-2": 1,
                "organiser": 1,
            }
            with Session(engine) as session:
                [message] = session.scalars(
                    select(Notification.message).where(
                        Notification.event_request_id == event_id,
                        Notification.recipient_account_id == ids["technical"],
                    )
                ).all()
            assert message.endswith("4 reserved equipment unit(s) were released.")
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-122-072 | AC4 | WB concurrency
def test_qa_spl_122_072_the_same_change_sent_twice_at_once_notifies_once(engine, pg_url):
    ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
    app = spl85._app(pg_url, ids)
    try:
        for run in range(RUNS):
            day = date(2027, 6, 2) + timedelta(days=run)
            event_id, line_id = spl85._seed_ready_event(
                engine, ids, organisation_id, venue_id, type_id, day
            )
            results = spl85._race(
                app, [_change(event_id, line_id, 5), _change(event_id, line_id, 5)]
            )
            assert all(status == 200 for status, _ in results), results
            with Session(engine) as session:
                assert session.get(EquipmentRequirement, line_id).quantity == 5
            assert _per_recipient(engine, ids, event_id) == {"technical": 1}
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-122-073 | AC4 | WB
def test_qa_spl_122_073_a_failed_cancellation_rolls_the_notice_back(engine, pg_url, monkeypatch):
    ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
    app = spl85._app(pg_url, ids)
    real = notifications_module.add_technical_support_notices

    def fail(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("Injected failure after the notice was written")

    monkeypatch.setattr(notifications_module, "add_technical_support_notices", fail)
    try:
        event_id, _ = spl85._seed_ready_event(
            engine, ids, organisation_id, venue_id, type_id, date(2027, 7, 2)
        )
        with pytest.raises(RuntimeError, match="Injected"):
            _cancel(event_id)(app.test_client())
        with Session(engine) as session:
            assert session.get(EventRequest, event_id).status == "planning"
            assert session.scalar(select(func.count()).select_from(Notification)) == 0
    finally:
        app.extensions["engine"].dispose()


# Review round 1 (2026-10-22, Ryan on PR #96): a retried addition must not notify twice.


# QA-SPL-122-074 | AC4 | WB concurrency
def test_qa_spl_122_074_simultaneous_retries_of_one_addition_add_one_line(engine, pg_url):
    ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
    app = spl85._app(pg_url, ids)
    try:
        for run in range(RUNS):
            day = date(2027, 8, 2) + timedelta(days=run)
            event_id, _ = spl85._seed_ready_event(
                engine, ids, organisation_id, venue_id, type_id, day
            )
            body = {
                "equipment_type_id": type_id,
                "quantity": 2,
                "required_start_date": day.isoformat(),
                "required_end_date": day.isoformat(),
                "essentiality": "undecided",
                "request_id": str(uuid.uuid4()),
            }

            def call(client, body=body, event_id=event_id):
                return client.post(
                    f"/api/event-requests/{event_id}/equipment-requirements",
                    json=body,
                    headers={"Authorization": "Bearer coordinator"},
                )

            results = spl85._race(app, [call, call])
            assert sorted(status for status, _ in results) == [200, 201], results
            assert len({body["requirement"]["id"] for _, body in results}) == 1
            with Session(engine) as session:
                added = session.scalar(
                    select(func.count())
                    .select_from(EquipmentRequirement)
                    .where(
                        EquipmentRequirement.event_request_id == event_id,
                        EquipmentRequirement.request_id == body["request_id"],
                    )
                )
            assert added == 1
            assert _per_recipient(engine, ids, event_id) == {"technical": 1}
    finally:
        app.extensions["engine"].dispose()
