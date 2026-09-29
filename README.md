# django-whoop

[![CI](https://github.com/django-health/django-whoop/actions/workflows/ci.yml/badge.svg)](https://github.com/django-health/django-whoop/actions/workflows/ci.yml)

A reusable Django app for the official [WHOOP API](https://developer.whoop.com/) (v2). Handles the WHOOP OAuth 2.0 flow, fetches cycles, sleep, recovery, and workouts from `api.prod.whoop.com`, and persists them through [`django-healthdatamodel`](https://github.com/django-health/django-healthdatamodel) so the same storage and query layer serves Apple Health, Fitbit, Google Health, Garmin, Oura, and WHOOP side-by-side.

> **v0.2.0 is a ground-up rewrite.** Versions ≤ 0.1.3 used WHOOP's unofficial
> password-grant API (`api-7.whoop.com`), which no longer works, and stored
> data in their own tables. There is no migration path from the old models —
> uninstall the old app, delete its tables, and start fresh.

## Install

```
pip install django-whoop
```

Add both this app and `django-healthdatamodel` to `INSTALLED_APPS`, then run migrations:

```python
INSTALLED_APPS = [
    ...
    "healthdatamodel",
    "whoop",
]
```

```
python manage.py migrate
```

The model uses `settings.AUTH_USER_MODEL` so it works with any custom user model.

Include the URLs:

```python
(path("whoop/", include("whoop.urls")),)
```

## Configuration

```python
WHOOP_CLIENT_ID = "..."  # from the WHOOP developer dashboard
WHOOP_CLIENT_SECRET = "..."
WHOOP_REDIRECT_URI = "https://your-app.example.com/whoop/callback/"

# Optional:
WHOOP_DEFAULT_SCOPES = [...]  # default: all read scopes + offline
WHOOP_CONNECT_SUCCESS_URL = "/"  # default: /admin/
```

Create the app at the [WHOOP developer dashboard](https://developer-dashboard.whoop.com/) (any WHOOP member can). See `docs/whoop/oauth.md` for the flow details — notably, the `offline` scope is what makes WHOOP issue a refresh token, and WHOOP rotates the refresh token on every refresh.

## Storage

This app does **not** define `Record` / `Workout` tables — those live in `django-healthdatamodel`. The `whoop.ingest` module maps WHOOP API responses to `healthdatamodel.schemas.RecordInput` and `WorkoutInput`, then persists them via `healthdatamodel.ingest`. Read the data back with `healthdatamodel.query.*`.

The only model defined here is `WhoopConnection`: per-user OAuth tokens, granted scopes, connection status, and last sync timestamp.

What maps where (details + caveats in the `whoop/ingest.py` docstring):

| WHOOP | healthdatamodel |
|---|---|
| Cycle strain | `Record` type `WHOOPStrain` |
| Cycle kilojoules (total energy) | `Record` ACTIVE_CALORIES (kcal) |
| Sleep stage totals | `Record` sleep-analysis entries (synthetic sequential intervals) |
| Sleep respiratory rate | `Record` HK respiratory rate |
| Recovery score / RHR / HRV / SpO2 / skin temp | `Record` (`WHOOPRecoveryScore` + HK types) |
| Workout (sport, energy, distance, HR zones) | `Workout` + metadata entries |
| Body measurement (height, weight) | `Record` HK height / body mass |

## Webhooks

Point the webhook URL in the developer dashboard at `/whoop/webhooks/`. Every delivery is HMAC-verified against `WHOOP_CLIENT_SECRET`; authenticated events emit the `whoop.signals.event_received` signal. Wire a handler to `whoop.webhooks.process_event` (inline or via a queue) to fetch + ingest the changed resource:

```python
from django.dispatch import receiver
from whoop.signals import event_received
from whoop.webhooks import process_event


@receiver(event_received)
def on_event(sender, payload, **kwargs):
    process_event(payload)
```

## Documentation

The WHOOP API documentation is summarized as Markdown under `docs/whoop/` so it's grep-able offline: `oauth.md`, `api.md` (endpoints + payload shapes from the OpenAPI spec), `webhooks.md`.

## Try it on your own data

The repo includes a runnable demo Django project at `demo/` that takes you
through the full OAuth flow and syncs your WHOOP data into `healthdatamodel`.

### 1. Set up a WHOOP developer app (one-time)

At <https://developer-dashboard.whoop.com/> create a team, then an app:

- **Redirect URL:** `http://localhost:8000/whoop/callback/` (exact match,
  trailing slash included).
- **Scopes:** enable all the read scopes plus `offline`
  (`read:recovery`, `read:cycles`, `read:sleep`, `read:workout`,
  `read:profile`, `read:body_measurement`, `offline`).
- Copy the Client ID and Client Secret.

You'll authenticate as your own WHOOP account — no review process needed for
personal use.

### 2. Run the demo

```
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser
export WHOOP_CLIENT_ID=...
export WHOOP_CLIENT_SECRET=...
uv run python manage.py runserver
```

Open <http://localhost:8000/>, sign in with the superuser you just created,
then:

- Click **Connect WHOOP** → consent at WHOOP → land back on the homepage
  with a `WhoopConnection` saved for your user.
- Pick a window and click **Sync now** to fetch and persist records.
- Browse the resulting rows at `/admin/healthdatamodel/record/`
  (and `.../workout/`).

If you'd rather drive sync from the terminal:

```
uv run python manage.py sync_whoop --user <your-username> --days 7
```

## Development

```
uv sync --group dev
uv run pytest tests/ -v
uv run pre-commit run --all-files
```
