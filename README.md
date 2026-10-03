# Lean Work Intake

A small web app for a solo data scientist (or any lean team) to turn ad-hoc requests into a
prioritised, capacity-aware queue - and to protect time for long-term strategic work.

**Flow:** teammates submit a structured request -> you triage (size, impact, confidence, fit) ->
weekly review with your manager against a capacity budget -> every request gets a decision *with a reason*.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
ADMIN_EMAILS=you@company.com .venv/bin/python run.py     # http://127.0.0.1:5000
.venv/bin/python -m pytest                                # tests
```

Sign in with an email + name (no password - local test mode). People in `ADMIN_EMAILS`
(comma-separated; you and your manager) get the triage/review/capacity/metrics views; everyone
else is a requester. If `ADMIN_EMAILS` is empty, the first person to sign in becomes admin.
Data lives in `instance/leanmgmt.sqlite` (delete the file to reset).

## How prioritisation works

`score = impact x confidence x (1 + 0.25 x strategic fit) / sqrt(effort days)`

Sizes: S ~4h, M ~16h, L ~56h, XL ~120h. Real deadlines are a separate constraint (flagged, not multiplied in).
Default capacity model (Settings): 30 focused h/week = **55% planned initiatives / 25% ad-hoc requests / 20% buffer**,
WIP limit 3. Ad-hoc work competes only for the 25%; when it's full, the capacity view shows the overload and
something has to be deferred - that's the conversation to have with your manager.

## Notifications

Everything is recorded in the in-app **Outbox**. Optionally also send to:
- **Teams**: set `TEAMS_WEBHOOK_URL` (a Teams Workflows / incoming webhook URL) - admins are pinged on new requests/replies.
- **Email**: set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (e.g. `smtp.office365.com`, 587).

Failures to deliver never block the user's action. Teams/SMTP delivery is untested against real services.

## Moving to the work environment

- **Sign-in:** the local email sign-in (`login()` in `leanmgmt/views.py`) is intentionally the only auth seam.
  Replace it with Microsoft Entra ID (OIDC, e.g. via `authlib`) - ask IT for an app registration - and
  keep `find_or_create_user()` to map the verified email to a user. **Do not deploy the dev sign-in to a shared network.**
- Set a real `SECRET_KEY`, serve behind HTTPS with a production server (e.g. `gunicorn 'leanmgmt:create_app()'`),
  and back up `instance/leanmgmt.sqlite`.
- Not yet built: Entra sign-in, Teams slash-command intake, duplicate detection, file attachments.
