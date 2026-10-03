"""Notifications: always recorded in the outbox; also pushed to Teams / email when configured.

Env vars (all optional):
  TEAMS_WEBHOOK_URL            Teams Workflows / incoming-webhook URL
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM   e.g. smtp.office365.com:587
"""
import json
import logging
import os
import smtplib
import urllib.request
from email.message import EmailMessage

from .db import now, run

log = logging.getLogger("leanmgmt.notify")


def _teams(text):
    url = os.environ.get("TEAMS_WEBHOOK_URL")
    if not url:
        return ""
    try:
        req = urllib.request.Request(
            url, data=json.dumps({"text": text}).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
        return "teams:ok "
    except Exception as exc:  # never break the user's action over a notification
        log.warning("Teams notification failed: %s", exc)
        return "teams:failed "


def _email(to, subject, body):
    host = os.environ.get("SMTP_HOST")
    if not host or not to:
        return ""
    try:
        msg = EmailMessage()
        msg["From"] = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "leanmgmt@localhost"))
        msg["To"], msg["Subject"] = to, subject
        msg.set_content(body)
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=8) as s:
            s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            s.send_message(msg)
        return "email:ok "
    except Exception as exc:
        log.warning("Email to %s failed: %s", to, exc)
        return "email:failed "


def notify(to_email, subject, body, teams=False):
    delivery = _email(to_email, subject, body)
    if teams:
        delivery += _teams(f"**{subject}**\n\n{body}")
    run("INSERT INTO outbox(to_email, subject, body, created_at, delivery) VALUES (?,?,?,?,?)",
        (to_email, subject, body, now(), delivery.strip() or "outbox only"))
