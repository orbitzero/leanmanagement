from datetime import date, timedelta

import pytest

from leanmgmt import create_app, logic


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.sqlite"), "ADMIN_EMAILS": ["ds@co.com"]})


class Client:
    def __init__(self, app):
        self.c = app.test_client()
        self.c.get("/login")

    def post(self, url, **data):
        with self.c.session_transaction() as s:
            data["csrf"] = s["csrf"]
        return self.c.post(url, data=data, follow_redirects=True)

    def get(self, url):
        return self.c.get(url, follow_redirects=True)

    def login(self, email, name="Someone", team="Ops"):
        self.post("/login", email=email, name=name, team=team)
        return self


REQ = dict(title="Churn by cohort", ask="Churn rate by signup cohort", decision_supported="Whether to change onboarding",
           consumer="CS lead, weekly review", type="analysis", requester_priority="high")


def test_score_prefers_cheap_high_impact():
    quick = {"impact": 4, "confidence": 100, "size": "S", "strategic_fit": 0}
    big = {"impact": 4, "confidence": 100, "size": "XL", "strategic_fit": 0}
    assert logic.score(quick) > logic.score(big)
    assert logic.score({"impact": None, "confidence": 80, "size": "S", "strategic_fit": 0}) is None
    assert logic.score({**big, "strategic_fit": 2}) > logic.score(big)


def test_roles_and_access(app):
    ds = Client(app).login("ds@co.com", "DS")
    ana = Client(app).login("ana@co.com", "Ana", "Sales")
    assert b"Triage inbox" in ds.get("/triage").data
    assert ana.c.get("/triage").status_code == 403
    assert ana.c.get("/settings").status_code == 403


def test_csrf_required(app):
    c = app.test_client()
    assert c.post("/login", data={"email": "a@b.com", "name": "A"}).status_code == 400


def test_submit_validation_and_flow(app):
    ds = Client(app).login("ds@co.com", "DS")
    ana = Client(app).login("ana@co.com", "Ana", "Sales")

    r = ana.post("/requests/new", **{**REQ, "decision_supported": ""})
    assert b"Please complete" in r.data

    r = ana.post("/requests/new", **{**REQ, "hard_deadline": "2030-01-01"})
    assert b"What happens if the deadline is missed" in r.data

    r = ana.post("/requests/new", **REQ)
    assert b"Your request has been submitted" in r.data and b"Churn by cohort" in r.data
    assert b"Churn by cohort" in ds.get("/triage").data

    # someone else can't see it
    bob = Client(app).login("bob@co.com", "Bob")
    assert bob.c.get("/requests/1").status_code == 404

    # reason required for decline; sizing required for scheduling
    assert b"add a reason" in ds.post("/requests/1/triage", status="declined").data
    assert b"size, impact and confidence" in ds.post("/requests/1/triage", status="triaged").data
    wk = (date.today() + timedelta(days=9)).isoformat()
    r = ds.post("/requests/1/triage", status="scheduled", size="M", impact="4", confidence="80",
                strategic_fit="1", scheduled_week=wk, decision_reason="Supports Q4 retention goal")
    assert b"Decision saved" in r.data
    assert b"Supports Q4 retention goal" in ana.get("/my").data
    assert b"Churn by cohort" in ds.get("/review").data
    assert b"Churn by cohort" in ds.get("/roadmap").data

    ds.post("/requests/1/triage", status="in_progress", size="M", impact="4", confidence="80")
    ds.post("/requests/1/triage", status="delivered", size="M", impact="4", confidence="80")
    r = ana.post("/requests/1/feedback", useful="5", outcome_note="Changed onboarding email")
    assert b"feedback has been recorded" in r.data
    assert b"Changed onboarding email" in ds.get("/requests/1").data
    m = ds.get("/metrics").data
    assert b"5.0" in m or b">5<" in m

    outbox = ds.get("/outbox").data
    assert b"New request" in outbox and b"Delivered: Churn by cohort" in outbox


def test_needs_info_roundtrip(app):
    ds = Client(app).login("ds@co.com", "DS")
    ana = Client(app).login("ana@co.com", "Ana")
    ana.post("/requests/new", **REQ)
    ds.post("/requests/1/triage", status="needs_info", decision_reason="Which cohort definition?")
    assert b"Needs info" in ana.get("/my").data
    ana.post("/requests/1/comment", body="Monthly signup cohorts")
    assert b"New" in ana.get("/my").data


def test_wip_limit_and_override(app):
    ds = Client(app).login("ds@co.com", "DS")
    ana = Client(app).login("ana@co.com", "Ana")
    for _ in range(4):
        ana.post("/requests/new", **REQ)
    sized = dict(size="S", impact="3", confidence="100")
    for rid in (1, 2, 3):
        assert b"Decision saved" in ds.post(f"/requests/{rid}/triage", status="in_progress", **sized).data
    assert b"WIP limit reached" in ds.post("/requests/4/triage", status="in_progress", **sized).data
    assert b"Decision saved" in ds.post("/requests/4/triage", status="in_progress", wip_override="on", **sized).data


def test_capacity_flags_overload(app):
    ds = Client(app).login("ds@co.com", "DS")
    ana = Client(app).login("ana@co.com", "Ana")
    ana.post("/requests/new", **REQ)
    ds.post("/requests/1/triage", status="scheduled", size="XL", impact="3", confidence="80",
            scheduled_week=date.today().isoformat(), decision_reason="x")
    assert b"over by" in ds.get("/capacity").data


def test_initiative_reserves_capacity_and_settings_validation(app):
    ds = Client(app).login("ds@co.com", "DS")
    r = ds.post("/initiatives/new", title="Churn model", problem="Predict churn", status="active", reserved_hours="12",
                size="XL", impact="5", confidence="50", strategic_fit="2")
    assert b"Churn model" in r.data
    assert b"12" in ds.get("/capacity").data
    assert b"must add up to 100" in ds.post("/settings", focus_hours="30", planned_pct="50", reactive_pct="25",
                                            buffer_pct="20", wip_limit="3").data
    assert b"Settings saved" in ds.post("/settings", focus_hours="32", planned_pct="60", reactive_pct="20",
                                        buffer_pct="20", wip_limit="2").data


def test_login_requires_email(app):
    c = Client(app)
    assert b"valid email" in c.post("/login", email="nope", name="x").data
    assert c.c.get("/my").status_code == 302
