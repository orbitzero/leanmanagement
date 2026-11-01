"""Prioritisation and capacity maths. Pure functions where possible."""
from datetime import date, timedelta
from math import sqrt

# size -> (label, effort in days, focused hours)
SIZES = {
    "S": ("S  - up to half a day", 0.5, 4),
    "M": ("M  - 1 to 3 days", 2, 16),
    "L": ("L  - 1 to 2 weeks", 7, 56),
    "XL": ("XL - a project (2+ weeks)", 15, 120),
}
SIZE_LABELS = {k: v[0] for k, v in SIZES.items()}
CONFIDENCE = {50: "50% - unsure it will be used / answerable",
              80: "80% - likely", 100: "100% - certain"}
FIT = {0: "None", 1: "Supports a priority", 2: "Drives a top priority"}
IMPACT = {1: "1 - minor", 2: "2 - small", 3: "3 - moderate", 4: "4 - high", 5: "5 - critical"}

REQUEST_TYPES = {
    "quick_answer": "Quick answer / data pull",
    "analysis": "Analysis",
    "report": "Recurring report / dashboard",
    "model": "Model or experiment",
    "other": "Other",
}
PRIORITIES = ["low", "medium", "high", "critical"]
VALUE_KINDS = ["", "revenue", "cost savings", "risk reduction", "time saved", "customer experience", "other"]

OPEN_STATUSES = ("new", "needs_info", "triaged", "scheduled", "in_progress")
CLOSED_STATUSES = ("delivered", "deferred", "declined", "redirected")
STATUS_LABELS = {
    "new": "New", "needs_info": "Needs info", "triaged": "Triaged",
    "scheduled": "Scheduled", "in_progress": "In progress", "delivered": "Delivered",
    "deferred": "Deferred", "declined": "Declined", "redirected": "Redirected",
}
# statuses where the decision should carry an explanation for the requester
NEEDS_REASON = ("deferred", "declined", "redirected", "needs_info")


def score(item):
    """value = impact x confidence x (1 + 0.25 x fit); score = value / sqrt(effort days).

    The square root keeps big projects competitive with quick wins while still
    rewarding cheap, high-impact work. Returns None until the item is sized.
    """
    try:
        if not (item["impact"] and item["confidence"] and item["size"]):
            return None
    except (KeyError, IndexError):
        return None
    value = item["impact"] * (item["confidence"] / 100) * (1 + 0.25 * (item["strategic_fit"] or 0))
    return round(value / sqrt(SIZES[item["size"]][1]), 2)


def size_hours(size):
    return SIZES[size][2] if size in SIZES else 0


def monday(d):
    return d - timedelta(days=d.weekday())


def parse_date(s):
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def days_to_deadline(item, today=None):
    d = parse_date(item["hard_deadline"])
    return None if d is None else (d - (today or date.today())).days


def capacity_budget(settings):
    focus = int(settings["focus_hours"])
    return {
        "planned": focus * int(settings["planned_pct"]) / 100,
        "reactive": focus * int(settings["reactive_pct"]) / 100,
        "buffer": focus * int(settings["buffer_pct"]) / 100,
    }


def weekly_load(weeks, requests, initiatives, today=None):
    """Hours committed per week. Requests fill the reactive bucket, initiatives the planned one.

    In-progress requests with no week count against the current week.
    """
    today = today or date.today()
    this_week = monday(today)
    out = []
    for wk in weeks:
        reactive = 0
        for r in requests:
            if r["status"] not in ("scheduled", "in_progress"):
                continue
            rw = parse_date(r["scheduled_week"]) or this_week
            if monday(rw) == wk or (r["status"] == "in_progress" and wk == this_week and monday(rw) < this_week):
                reactive += size_hours(r["size"])
        planned = 0
        for i in initiatives:
            if i["status"] != "active":
                continue
            start, end = parse_date(i["start_date"]), parse_date(i["target_date"])
            if (start is None or monday(start) <= wk) and (end is None or end >= wk):
                planned += i["reserved_hours"]
        out.append({"week": wk, "reactive": reactive, "planned": planned})
    return out
