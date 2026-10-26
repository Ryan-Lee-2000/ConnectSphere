"""SPL-123 real PostgreSQL races and notification rollback."""

from datetime import date

import pytest
import test_event_confirmation_postgres as base
from app import notifications
from app.models import EventChangeRequest, EventChangeRequestItem, EventRequest, Notification
from sqlalchemy import select
from sqlalchemy.orm import Session

pytestmark = base.pytestmark
pg_url = base.pg_url
engine = base.engine


def scenario(engine, pg_url):
    ids, organisation, venue, stock = base._seed_accounts(engine)
    event_id, _ = base._seed_ready_event(
        engine, ids, organisation, venue, stock, date(2030, 11, 20)
    )
    return base._app(pg_url, ids), ids, event_id


def organiser_notices(engine, event_id):
    with Session(engine) as session:
        return session.scalars(
            select(Notification.dedupe_key).where(
                Notification.event_request_id == event_id,
                Notification.dedupe_key.like("organiser_%"),
            )
        ).all()


# QA-SPL-123-070 | AC1 AC5 | WB concurrency
def test_qa_spl_123_070_concurrent_confirmation_notifies_once(engine, pg_url):
    app, ids, event_id = scenario(engine, pg_url)
    try:
        results = base._race(app, [base._confirm(event_id), base._confirm(event_id)])
        assert sorted(code for code, _ in results) == [200, 409], results
        [key] = organiser_notices(engine, event_id)
        assert key.startswith("organiser_event_confirmed:")
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-123-071 | AC3 AC5 | WB concurrency
def test_qa_spl_123_071_concurrent_cancellation_notifies_once(engine, pg_url):
    app, ids, event_id = scenario(engine, pg_url)
    try:

        def cancel(client):
            return client.post(
                f"/api/event-requests/{event_id}/cancel",
                headers={"Authorization": "Bearer coordinator"},
                json={"reason": "Venue unavailable."},
            )

        results = base._race(app, [cancel, cancel])
        assert sorted(code for code, _ in results) == [200, 409], results
        [key] = organiser_notices(engine, event_id)
        assert key.startswith("organiser_event_cancelled:")
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-123-072 | AC4 AC5 | WB concurrency
def test_qa_spl_123_072_concurrent_item_decisions_notifies_once(engine, pg_url):
    app, ids, event_id = scenario(engine, pg_url)
    try:
        with Session(engine) as session:
            request = EventChangeRequest(
                event_request_id=event_id,
                submitted_by_account_id=ids["organiser"],
                submitted_at=base.STAMP,
                status="pending",
                items=[
                    EventChangeRequestItem(
                        field="name",
                        current_value="Race event",
                        requested_value="New name",
                        reason="Updated programme",
                    )
                ],
            )
            request.items[0].current_value = session.get(EventRequest, event_id).name
            session.add(request)
            session.commit()
            request_id, item_id = request.id, request.items[0].id
        route = f"/api/event-requests/assigned/{event_id}/change-requests/{request_id}/decisions"
        payload = {"decisions": [{"item_id": item_id, "decision": "accepted"}]}
        headers = {"Authorization": "Bearer coordinator"}
        preview = app.test_client().post(route + "/preview", headers=headers, json=payload)
        assert preview.status_code == 200, preview.json
        payload["preview_token"] = preview.json["preview_token"]

        def save(client):
            return client.post(route, headers=headers, json=payload)

        results = base._race(app, [save, save])
        assert sorted(code for code, _ in results) == [200, 409], results
        assert organiser_notices(engine, event_id) == [f"organiser_change_item_decided:{item_id}"]
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-123-073 | AC2 AC5 | WB concurrency
def test_qa_spl_123_073_concurrent_significant_saves_notify_once(engine, pg_url):
    app, ids, event_id = scenario(engine, pg_url)
    try:
        with Session(engine) as session:
            session.get(EventRequest, event_id).status = "confirmed"
            session.commit()
        route = f"/api/event-requests/assigned/{event_id}/significant-changes"
        payload = {"values": {"expected_attendance": 101}}
        headers = {"Authorization": "Bearer coordinator"}
        preview = app.test_client().post(route + "/preview", headers=headers, json=payload)
        assert preview.status_code == 200, preview.json
        payload["preview_token"] = preview.json["preview_token"]

        def save(client):
            return client.patch(route, headers=headers, json=payload)

        results = base._race(app, [save, save])
        assert sorted(code for code, _ in results) == [200, 409], results
        [key] = organiser_notices(engine, event_id)
        assert key.startswith("organiser_returned_to_planning:")
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-123-074 | AC5 | WB rollback
def test_qa_spl_123_074_notice_failure_rolls_back_postgres_transaction(engine, pg_url, monkeypatch):
    app, ids, event_id = scenario(engine, pg_url)
    original = notifications.add_organiser_notice
    try:

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("SPL-123 injected PostgreSQL failure")

        monkeypatch.setattr(notifications, "add_organiser_notice", fail)
        with pytest.raises(RuntimeError, match="injected PostgreSQL failure"):
            base._confirm(event_id)(app.test_client())
        assert organiser_notices(engine, event_id) == []
        with Session(engine) as session:
            assert session.get(EventRequest, event_id).status == "planning"
    finally:
        app.extensions["engine"].dispose()
