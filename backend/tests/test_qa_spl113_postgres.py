"""SPL-113 history and current membership against the migrated PostgreSQL schema."""

import test_qa_spl112 as decisions
import test_qa_spl112_postgres as pg
from app.models import Account, EventRequest, Organisation
from sqlalchemy.orm import Session

pytestmark = pg.pytestmark
pg_url = pg.pg_url
scenario = pg.scenario
prepared = pg.prepared


# QA-SPL-113-060 | AC1-4 | WB
def test_qa_spl_113_060_durable_outcome_and_membership(prepared):
    app, engine, event, request = prepared
    client = app.test_client()
    result = decisions.save(client, event, request, decisions.choices(request))
    assert result.status_code == 200
    with Session(engine) as session:
        stored = session.get(EventRequest, event)
        stored.status = "completed"
        owner = stored.organiser_account_id
        session.commit()
    fresh = app.test_client()
    history = decisions.base.read(fresh, event)
    assert history.status_code == 200
    assert history.json["change_requests"][0]["status"] == "closed"
    assert history.json["change_requests"][0]["items"][0]["decision"] == "accepted"
    current = fresh.get(f"/api/organisation/events/{event}", headers=decisions.base.headers())
    assert current.status_code == 200
    assert current.json["event"]["name"] == "Revised gala"
    with Session(engine) as session:
        other = Organisation(name="New client")
        session.add(other)
        session.flush()
        session.get(Account, owner).organisation_id = other.id
        session.commit()
    assert decisions.base.read(fresh, event).status_code == 404
    assert (
        fresh.get(f"/api/organisation/events/{event}", headers=decisions.base.headers()).status_code
        == 404
    )
    assert decisions.base.read(fresh, event, "coordinator").status_code == 200
