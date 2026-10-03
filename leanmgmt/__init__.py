import os
import secrets
from datetime import date, timedelta

from flask import Flask, abort, request, session

from . import logic
from .db import close_db, init_db


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.path.join(app.instance_path, "leanmgmt.sqlite"),
        # comma separated emails that get the admin (data scientist / manager) role.
        # If empty, the first person to sign in becomes admin.
        ADMIN_EMAILS=[e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()],
    )
    if config:
        app.config.update(config)

    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()

    from .views import bp
    app.register_blueprint(bp)

    @app.before_request
    def csrf_protect():
        if request.method == "POST":
            token = session.get("csrf")
            if not token or token != request.form.get("csrf"):
                abort(400, "Invalid or missing CSRF token")

    @app.context_processor
    def inject():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return {
            "csrf": session["csrf"], "logic": logic, "today": date.today(), "timedelta": timedelta,
            "status_label": lambda s: logic.STATUS_LABELS.get(s, s),
        }

    return app
