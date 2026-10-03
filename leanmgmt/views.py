from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   session, url_for)

from . import logic
from .db import get_settings, int_setting, now, q, q1, run
from .notify import notify

bp = Blueprint("main", __name__)


# ---------------------------------------------------------------- auth
# Local "dev" sign-in: email + name, no password. This is the single seam to swap for
# Microsoft Entra ID (OIDC) when moving to the work environment - see README.
@bp.before_app_request
def load_user():
    uid = session.get("uid")
    g.user = q1("SELECT * FROM users WHERE id = ?", (uid,)) if uid else None


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            return redirect(url_for("main.login", next=request.path))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            return redirect(url_for("main.login", next=request.path))
        if g.user["role"] != "admin":
            abort(403)
        return view(*a, **kw)
    return wrapped


def is_admin():
    return g.user is not None and g.user["role"] == "admin"


def admin_emails():
    return [r["email"] for r in q("SELECT email FROM users WHERE role = 'admin'")]


def find_or_create_user(email, name, team=""):
    email = email.strip().lower()
    user = q1("SELECT * FROM users WHERE email = ?", (email,))
    if user:
        return user
    configured = current_app.config["ADMIN_EMAILS"]
    if configured:
        role = "admin" if email in configured else "requester"
    else:  # nothing configured: first person in is the admin
        role = "requester" if q1("SELECT 1 FROM users WHERE role = 'admin'") else "admin"
    uid = run("INSERT INTO users(email, name, team, role) VALUES (?,?,?,?)", (email, name.strip(), team.strip(), role))
    return q1("SELECT * FROM users WHERE id = ?", (uid,))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email, name = request.form.get("email", "").strip(), request.form.get("name", "").strip()
        if "@" not in email:
            flash("Enter a valid email address.", "error")
        else:
            existing = q1("SELECT * FROM users WHERE email = ?", (email.lower(),))
            if not existing and not name:
                flash("First time here? Please add your name too.", "error")
            else:
                user = find_or_create_user(email, name, request.form.get("team", ""))
                session.clear()
                session["uid"] = user["id"]
                nxt = request.args.get("next", "")
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("main.home"))
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("main.login"))


@bp.route("/")
@login_required
def home():
    return redirect(url_for("main.triage" if is_admin() else "main.my_requests"))


# ---------------------------------------------------------------- requests
def _clean(name, maxlen=4000):
    return request.form.get(name, "").strip()[:maxlen]


def _can_view(req):
    return is_admin() or req["requester_id"] == g.user["id"]


def _get_request(rid):
    req = q1("SELECT r.*, u.name AS requester_name, u.email AS requester_email, u.team AS team "
             "FROM requests r JOIN users u ON u.id = r.requester_id WHERE r.id = ?", (rid,))
    if req is None or not _can_view(req):
        abort(404)
    return req


@bp.route("/requests/new", methods=["GET", "POST"])
@login_required
def new_request():
    form = request.form if request.method == "POST" else {}
    if request.method == "POST":
        required = {"title": "Title", "ask": "What you need", "decision_supported": "The decision or outcome this supports",
                    "consumer": "Who will use the result"}
        missing = [label for k, label in required.items() if not _clean(k)]
        deadline = _clean("hard_deadline")
        if request.form.get("type") not in logic.REQUEST_TYPES:
            missing.append("Type of work")
        if deadline and logic.parse_date(deadline) is None:
            missing.append("A valid deadline date")
        if deadline and not _clean("deadline_consequence"):
            missing.append("What happens if the deadline is missed")
        if missing:
            flash("Please complete: " + "; ".join(missing), "error")
        else:
            requester, source = g.user, "form"
            if is_admin() and _clean("on_behalf_email"):  # log a direct ask so interrupts are measured
                requester = find_or_create_user(_clean("on_behalf_email"), _clean("on_behalf_name") or _clean("on_behalf_email"))
                source = "direct"
            pr = request.form.get("requester_priority")
            rid = run(
                """INSERT INTO requests(title, ask, decision_supported, consumer, type, hard_deadline, deadline_consequence,
                   requester_priority, value_kind, value_estimate, data_sources, tried, can_wait, sponsor, source,
                   requester_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (_clean("title", 200), _clean("ask"), _clean("decision_supported"), _clean("consumer"),
                 request.form["type"], deadline or None, _clean("deadline_consequence"),
                 pr if pr in logic.PRIORITIES else "medium",
                 _clean("value_kind"), _clean("value_estimate"), _clean("data_sources"), _clean("tried"),
                 _clean("can_wait"), _clean("sponsor"), source, requester["id"], now(), now()))
            link = url_for("main.view_request", rid=rid, _external=True)
            for email in admin_emails():
                notify(email, f"New request: {_clean('title', 200)}",
                       f"From {requester['name']} ({requester['team'] or 'no team'}). Priority: {pr}. "
                       f"Deadline: {deadline or 'none'}.\n{link}", teams=True)
            notify(requester["email"], f"We received your request: {_clean('title', 200)}",
                   "Thanks - it's in the triage queue. You'll get a decision with the reasoning after the weekly "
                   f"prioritisation review. Track it here: {link}")
            flash("Request submitted. You'll be notified when it's triaged.", "ok")
            return redirect(url_for("main.view_request", rid=rid))
    return render_template("request_new.html", form=form, logic=logic)


@bp.route("/my")
@login_required
def my_requests():
    rows = q("SELECT * FROM requests WHERE requester_id = ? ORDER BY created_at DESC", (g.user["id"],))
    return render_template("my_requests.html", rows=rows)


@bp.route("/requests/<int:rid>")
@login_required
def view_request(rid):
    req = _get_request(rid)
    comments = q("SELECT c.*, u.name, u.role FROM comments c JOIN users u ON u.id = c.user_id "
                 "WHERE request_id = ? ORDER BY c.id", (rid,))
    return render_template("request_detail.html", r=req, comments=comments, score=logic.score(req),
                           wip=len(q("SELECT 1 FROM requests WHERE status='in_progress'")), wip_limit=int_setting("wip_limit"))


@bp.route("/requests/<int:rid>/comment", methods=["POST"])
@login_required
def comment(rid):
    req = _get_request(rid)
    body = _clean("body")
    if body:
        run("INSERT INTO comments(request_id, user_id, body, created_at) VALUES (?,?,?,?)", (rid, g.user["id"], body, now()))
        link = url_for("main.view_request", rid=rid, _external=True)
        if is_admin():
            notify(req["requester_email"], f"Update on your request: {req['title']}", f"{g.user['name']}: {body}\n{link}")
        else:
            if req["status"] == "needs_info":
                run("UPDATE requests SET status='new', updated_at=? WHERE id=?", (now(), rid))
            for email in admin_emails():
                notify(email, f"Reply on: {req['title']}", f"{g.user['name']}: {body}\n{link}", teams=True)
    return redirect(url_for("main.view_request", rid=rid))


@bp.route("/requests/<int:rid>/triage", methods=["POST"])
@admin_required
def triage_update(rid):
    req = _get_request(rid)
    status = request.form.get("status")
    if status not in logic.STATUS_LABELS:
        abort(400)
    size = request.form.get("size") or None
    impact = request.form.get("impact", type=int)
    conf = request.form.get("confidence", type=int)
    fit = request.form.get("strategic_fit", type=int) or 0
    reason = _clean("decision_reason")
    week = logic.parse_date(request.form.get("scheduled_week"))

    problems = []
    if size and size not in logic.SIZES: problems.append("invalid size")
    if impact is not None and impact not in logic.IMPACT: problems.append("invalid impact")
    if conf is not None and conf not in logic.CONFIDENCE: problems.append("invalid confidence")
    if fit not in logic.FIT: problems.append("invalid strategic fit")
    if status in ("triaged", "scheduled", "in_progress") and not (size and impact and conf):
        problems.append("size, impact and confidence are needed before a request can be triaged or scheduled")
    if status in logic.NEEDS_REASON and not reason:
        problems.append("add a reason - the requester sees it")
    if status == "scheduled" and not week:
        problems.append("pick the week it's scheduled for")
    wip_limit = int_setting("wip_limit")
    in_prog = q1("SELECT COUNT(*) c FROM requests WHERE status='in_progress' AND id != ?", (rid,))["c"]
    if status == "in_progress" and in_prog >= wip_limit and not request.form.get("wip_override"):
        problems.append(f"WIP limit reached ({in_prog}/{wip_limit} in progress) - finish something or tick the override")
    if problems:
        flash("Not saved: " + "; ".join(problems), "error")
        return redirect(url_for("main.view_request", rid=rid))

    ts = now()
    sets = {"status": status, "size": size, "impact": impact, "confidence": conf, "strategic_fit": fit,
            "decision_reason": reason, "scheduled_week": logic.monday(week).isoformat() if week else None, "updated_at": ts}
    if req["triaged_at"] is None and status != "new":
        sets["triaged_at"] = ts
    if status == "in_progress" and req["started_at"] is None:
        sets["started_at"] = ts
    if status == "delivered" and req["delivered_at"] is None:
        sets["delivered_at"] = ts
    run(f"UPDATE requests SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), rid))

    if status != req["status"] or reason != req["decision_reason"]:
        link = url_for("main.view_request", rid=rid, _external=True)
        extra = ""
        if status == "scheduled":
            extra = f" for the week of {sets['scheduled_week']}"
        if status == "delivered":
            extra = ". Please tell us whether it was useful - it takes 10 seconds"
        notify(req["requester_email"], f"{logic.STATUS_LABELS[status]}: {req['title']}",
               f"Status: {logic.STATUS_LABELS[status]}{extra}.\nReason: {reason or '-'}\n{link}")
    flash("Saved.", "ok")
    nxt = request.form.get("next")
    return redirect(nxt if nxt in ("/triage", "/review") else url_for("main.view_request", rid=rid))


@bp.route("/requests/<int:rid>/feedback", methods=["POST"])
@login_required
def feedback(rid):
    req = _get_request(rid)
    if req["requester_id"] != g.user["id"] or req["status"] != "delivered":
        abort(403)
    useful = request.form.get("useful", type=int)
    if useful in (1, 2, 3, 4, 5):
        run("UPDATE requests SET useful=?, outcome_note=?, updated_at=? WHERE id=?", (useful, _clean("outcome_note"), now(), rid))
        flash("Thanks for the feedback.", "ok")
    return redirect(url_for("main.view_request", rid=rid))


# ---------------------------------------------------------------- admin views
def _sorted_by_score(rows):
    def key(r):
        s = logic.score(r)
        d = logic.parse_date(r["hard_deadline"])
        return (-(s if s is not None else -1), d or date.max)
    return sorted(rows, key=key)


@bp.route("/triage")
@admin_required
def triage():
    inbox = q("SELECT r.*, u.name AS requester_name, u.team AS team FROM requests r JOIN users u ON u.id = r.requester_id "
              "WHERE status IN ('new','needs_info') ORDER BY (hard_deadline IS NULL), hard_deadline, created_at")
    return render_template("triage.html", inbox=inbox)


@bp.route("/review")
@admin_required
def review():
    settings = get_settings()
    this_week = logic.monday(date.today())
    weeks = [this_week + timedelta(weeks=i) for i in range(2)]
    open_rows = q("SELECT r.*, u.name AS requester_name, u.team AS team FROM requests r JOIN users u ON u.id = r.requester_id "
                  "WHERE status IN ('triaged','scheduled','in_progress')")
    inits = q("SELECT * FROM initiatives")
    load = logic.weekly_load(weeks, open_rows, inits)
    groups = {s: _sorted_by_score([r for r in open_rows if r["status"] == s]) for s in ("in_progress", "scheduled", "triaged")}
    urgent = [r for r in open_rows if (d := logic.days_to_deadline(r)) is not None and d <= 7]
    return render_template("review.html", groups=groups, load=load, budget=logic.capacity_budget(settings), urgent=urgent,
                           active_inits=[i for i in inits if i["status"] == "active"], settings=settings,
                           wip=len(groups["in_progress"]))


@bp.route("/capacity")
@admin_required
def capacity():
    settings = get_settings()
    weeks = [logic.monday(date.today()) + timedelta(weeks=i) for i in range(6)]
    reqs = q("SELECT * FROM requests WHERE status IN ('scheduled','in_progress')")
    return render_template("capacity.html", load=logic.weekly_load(weeks, reqs, q("SELECT * FROM initiatives")),
                           budget=logic.capacity_budget(settings), settings=settings)


# ---------------------------------------------------------------- initiatives
INIT_STATUSES = ["idea", "planned", "active", "paused", "done", "killed"]


@bp.route("/initiatives")
@admin_required
def initiatives():
    rows = q("SELECT * FROM initiatives")
    order = {s: i for i, s in enumerate(["active", "planned", "idea", "paused", "done", "killed"])}
    rows = sorted(rows, key=lambda r: (order[r["status"]], -(logic.score(r) or 0)))
    return render_template("initiatives.html", rows=rows, score=logic.score)


@bp.route("/initiatives/new", methods=["GET", "POST"])
@bp.route("/initiatives/<int:iid>", methods=["GET", "POST"])
@admin_required
def initiative(iid=None):
    row = q1("SELECT * FROM initiatives WHERE id = ?", (iid,)) if iid else None
    if iid and row is None:
        abort(404)
    if request.method == "POST":
        title, problem = _clean("title", 200), _clean("problem")
        size = request.form.get("size") or None
        status = request.form.get("status", "idea")
        hours = request.form.get("reserved_hours", type=int) or 0
        errs = []
        if not title or not problem: errs.append("title and problem are required")
        if size and size not in logic.SIZES: errs.append("invalid size")
        if status not in INIT_STATUSES: errs.append("invalid status")
        if hours < 0 or hours > 168: errs.append("reserved hours must be between 0 and 168")
        start, end = _clean("start_date"), _clean("target_date")
        if (start and not logic.parse_date(start)) or (end and not logic.parse_date(end)): errs.append("invalid date")
        if errs:
            flash("Not saved: " + "; ".join(errs), "error")
        else:
            vals = (title, problem, _clean("value_hypothesis"), size, request.form.get("impact", type=int),
                    request.form.get("confidence", type=int), request.form.get("strategic_fit", type=int) or 0,
                    status, hours, start or None, end or None, _clean("outcome"), now())
            if row:
                run("UPDATE initiatives SET title=?, problem=?, value_hypothesis=?, size=?, impact=?, confidence=?, "
                    "strategic_fit=?, status=?, reserved_hours=?, start_date=?, target_date=?, outcome=?, updated_at=? WHERE id=?",
                    (*vals, iid))
            else:
                run("INSERT INTO initiatives(title, problem, value_hypothesis, size, impact, confidence, strategic_fit, status, "
                    "reserved_hours, start_date, target_date, outcome, updated_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (*vals, now()))
            flash("Saved.", "ok")
            return redirect(url_for("main.initiatives"))
    return render_template("initiative_form.html", i=row, statuses=INIT_STATUSES, logic=logic)


# ---------------------------------------------------------------- roadmap, metrics, settings
@bp.route("/roadmap")
@login_required
def roadmap():
    rows = q("SELECT r.id, r.title, r.status, r.scheduled_week, r.size, u.team FROM requests r JOIN users u ON u.id = r.requester_id "
             "WHERE status IN ('scheduled','in_progress','triaged') ORDER BY scheduled_week")
    this_week = logic.monday(date.today())
    horizon = this_week + timedelta(weeks=4)
    now_, next_, later = [], [], []
    for r in rows:
        wk = logic.parse_date(r["scheduled_week"])
        if r["status"] == "in_progress" or (wk and wk <= this_week):
            now_.append(r)
        elif wk and wk < horizon:
            next_.append(r)
        else:
            later.append(r)
    inits = q("SELECT * FROM initiatives WHERE status IN ('active','planned') ORDER BY status")
    return render_template("roadmap.html", now_=now_, next_=next_, later=later, inits=inits)


@bp.route("/metrics")
@admin_required
def metrics():
    by_status = {r["status"]: r["c"] for r in q("SELECT status, COUNT(*) c FROM requests GROUP BY status")}
    by_team = q("""SELECT COALESCE(NULLIF(u.team,''),'(none)') team, COUNT(*) total,
                   SUM(status='delivered') delivered, SUM(status IN ('deferred','declined','redirected')) not_done
                   FROM requests r JOIN users u ON u.id = r.requester_id GROUP BY 1 ORDER BY total DESC""")
    rows = q("SELECT * FROM requests")
    def days(a, b):
        return [(datetime.fromisoformat(r[b]) - datetime.fromisoformat(r[a])).total_seconds() / 86400
                for r in rows if r[a] and r[b]]
    def avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else None
    cycle = {}
    for size in logic.SIZES:
        xs = [(datetime.fromisoformat(r["delivered_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds() / 86400
              for r in rows if r["size"] == size and r["delivered_at"]]
        cycle[size] = (avg(xs), len(xs))
    useful = [r["useful"] for r in rows if r["useful"]]
    settings = get_settings()
    month_ago = (datetime.now() - timedelta(days=30)).isoformat()
    delivered_hours = sum(logic.size_hours(r["size"]) for r in rows if r["status"] == "delivered" and (r["delivered_at"] or "") >= month_ago)
    direct = sum(1 for r in rows if r["source"] == "direct")
    return render_template("metrics.html", by_status=by_status, by_team=by_team, queue_days=avg(days("created_at", "triaged_at")),
                           cycle=cycle, useful_avg=avg(useful), useful_n=len(useful), delivered_hours=delivered_hours,
                           direct=direct, total=len(rows), budget=logic.capacity_budget(settings),
                           initiative_hours=sum(i["reserved_hours"] for i in q("SELECT * FROM initiatives WHERE status='active'")))


@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        try:
            vals = {k: int(request.form[k]) for k in ("focus_hours", "planned_pct", "reactive_pct", "buffer_pct", "wip_limit")}
        except (KeyError, ValueError):
            flash("All fields must be whole numbers.", "error")
            return redirect(url_for("main.settings"))
        if vals["planned_pct"] + vals["reactive_pct"] + vals["buffer_pct"] != 100:
            flash("Planned + reactive + buffer must add up to 100%.", "error")
        elif not (1 <= vals["focus_hours"] <= 80) or not (1 <= vals["wip_limit"] <= 20) or min(vals.values()) < 0:
            flash("Values out of range.", "error")
        else:
            for k, v in vals.items():
                run("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
            flash("Settings saved.", "ok")
        return redirect(url_for("main.settings"))
    return render_template("settings.html", s=get_settings(), users=q("SELECT * FROM users ORDER BY role, name"))


@bp.route("/outbox")
@admin_required
def outbox():
    return render_template("outbox.html", rows=q("SELECT * FROM outbox ORDER BY id DESC LIMIT 100"))
