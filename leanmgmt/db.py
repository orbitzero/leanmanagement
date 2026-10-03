import sqlite3
from datetime import datetime

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    team TEXT DEFAULT '',
    role TEXT NOT NULL DEFAULT 'requester'
);
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    ask TEXT NOT NULL,
    decision_supported TEXT NOT NULL,
    consumer TEXT NOT NULL,
    type TEXT NOT NULL,
    hard_deadline TEXT,
    deadline_consequence TEXT DEFAULT '',
    requester_priority TEXT NOT NULL DEFAULT 'medium',
    value_kind TEXT DEFAULT '',
    value_estimate TEXT DEFAULT '',
    data_sources TEXT DEFAULT '',
    tried TEXT DEFAULT '',
    can_wait TEXT DEFAULT '',
    sponsor TEXT DEFAULT '',
    source TEXT NOT NULL DEFAULT 'form',
    requester_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'new',
    size TEXT,
    impact INTEGER,
    confidence INTEGER,
    strategic_fit INTEGER NOT NULL DEFAULT 0,
    decision_reason TEXT DEFAULT '',
    scheduled_week TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    triaged_at TEXT,
    started_at TEXT,
    delivered_at TEXT,
    useful INTEGER,
    outcome_note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS initiatives (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    problem TEXT NOT NULL,
    value_hypothesis TEXT DEFAULT '',
    size TEXT,
    impact INTEGER,
    confidence INTEGER,
    strategic_fit INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'idea',
    reserved_hours INTEGER NOT NULL DEFAULT 0,
    start_date TEXT,
    target_date TEXT,
    outcome TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    request_id INTEGER NOT NULL REFERENCES requests(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    to_email TEXT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    delivery TEXT DEFAULT ''
);
"""

DEFAULT_SETTINGS = {
    "focus_hours": "30",   # real focused hours per week after meetings etc.
    "planned_pct": "55",   # initiatives / committed projects
    "reactive_pct": "25",  # ad-hoc requests
    "buffer_pct": "20",    # buffer, maintenance, learning (never allocated)
    "wip_limit": "3",
}


def now():
    return datetime.now().isoformat(timespec="seconds")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    db.commit()


def q(sql, args=()):
    return get_db().execute(sql, args).fetchall()


def q1(sql, args=()):
    return get_db().execute(sql, args).fetchone()


def run(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


def get_settings():
    return {r["key"]: r["value"] for r in q("SELECT key, value FROM settings")}


def int_setting(name):
    return int(get_settings().get(name, DEFAULT_SETTINGS[name]))
