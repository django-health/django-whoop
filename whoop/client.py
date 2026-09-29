"""HTTP client for the WHOOP REST API (v2).

Sync-only wrapper around ``httpx.Client``, built from a
:class:`~whoop.models.WhoopConnection`.

Responsibilities:

* Authorization: inject ``Bearer <access_token>``.
* Token freshness: refresh proactively when the stored expiry is within the
  connection's leeway, and retry once on a 401 to absorb clock skew or external
  token invalidation.
* Resilience: retry 3× with exponential backoff on 429 and 5xx; honor
  ``Retry-After``.
* Pagination: the ``iter_*`` methods walk ``next_token`` and yield raw
  records one at a time.

Collection endpoints filter by the record's own time range: ``start`` is
inclusive, ``end`` is exclusive-ish ("intersects this time or ended before"),
and both are RFC3339 timestamps. Pages are capped at 25 records.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx

from . import oauth
from .constants import API_BASE_URL, MAX_PAGE_SIZE

if TYPE_CHECKING:
    from .models import WhoopConnection


DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0


def _rfc3339(dt: datetime) -> str:
    """Serialize a datetime the way WHOOP's examples do: milliseconds + ``Z``."""
    return (
        dt.astimezone(timezone.utc)
        .replace(tzinfo=None)
        .isoformat(timespec="milliseconds")
        + "Z"
    )


class WhoopAPIError(Exception):
    """Non-retryable error returned by the WHOOP API."""

    def __init__(self, status_code: int, message: str, payload: Any = None):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.payload = payload


class WhoopClient:
    """Thin REST client. Use as a context manager so the underlying httpx
    session is closed deterministically.
    """

    def __init__(
        self,
        connection: WhoopConnection,
        *,
        base_url: str = API_BASE_URL,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        backoff_seconds: float = BASE_BACKOFF_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.connection = connection
        self._base = base_url.rstrip("/")
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._sleep = sleep
        self._http = httpx.Client(timeout=timeout)

    # context manager ------------------------------------------------------

    def __enter__(self) -> WhoopClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # core request loop ----------------------------------------------------

    def _ensure_fresh_token(self) -> None:
        if self.connection.is_token_expired():
            oauth.refresh_access_token(self.connection)

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.connection.access_token}"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        self._ensure_fresh_token()
        url = f"{self._base}/{path.lstrip('/')}"
        retried_after_401 = False
        attempt = 0

        while True:
            response = self._http.request(
                method,
                url,
                params=params,
                headers=self._auth_headers(),
            )

            if response.status_code == 401 and not retried_after_401:
                # Either clock skew or the token was invalidated externally
                # (WHOOP kills the old access token whenever the refresh
                # token is used) — force a refresh and retry once.
                oauth.refresh_access_token(self.connection)
                retried_after_401 = True
                continue

            if response.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                self._sleep(self._compute_backoff(response, attempt))
                attempt += 1
                continue

            if response.status_code >= 400:
                payload = _safe_json(response)
                message = _extract_error_message(payload, response.text)
                raise WhoopAPIError(response.status_code, message, payload)

            if not response.content:
                return None
            return response.json()

    def _compute_backoff(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return self._backoff * (2**attempt)

    # user resources -------------------------------------------------------

    def get_profile(self) -> dict[str, Any]:
        """``GET /v2/user/profile/basic`` (scope ``read:profile``)."""
        return self._request("GET", "v2/user/profile/basic") or {}

    def get_body_measurement(self) -> dict[str, Any]:
        """``GET /v2/user/measurement/body`` (scope ``read:body_measurement``)."""
        return self._request("GET", "v2/user/measurement/body") or {}

    def revoke_access(self) -> None:
        """``DELETE /v2/user/access`` — remove this app's OAuth access at WHOOP."""
        self._request("DELETE", "v2/user/access")

    # single records -------------------------------------------------------

    def get_cycle(self, cycle_id: int | str) -> dict[str, Any]:
        return self._request("GET", f"v2/cycle/{cycle_id}") or {}

    def get_cycle_recovery(self, cycle_id: int | str) -> dict[str, Any]:
        """``GET /v2/cycle/{cycleId}/recovery`` — the recovery scored for a cycle."""
        return self._request("GET", f"v2/cycle/{cycle_id}/recovery") or {}

    def get_sleep(self, sleep_id: str) -> dict[str, Any]:
        """``GET /v2/activity/sleep/{sleepId}``. Sleep ids are UUIDs in v2."""
        return self._request("GET", f"v2/activity/sleep/{sleep_id}") or {}

    def get_workout(self, workout_id: str) -> dict[str, Any]:
        """``GET /v2/activity/workout/{workoutId}``. Workout ids are UUIDs in v2."""
        return self._request("GET", f"v2/activity/workout/{workout_id}") or {}

    # collections ----------------------------------------------------------

    def _iter_collection(
        self,
        path: str,
        *,
        start: datetime | None,
        end: datetime | None,
        page_size: int,
    ) -> Iterator[dict[str, Any]]:
        params: dict[str, Any] = {"limit": min(page_size, MAX_PAGE_SIZE)}
        if start is not None:
            params["start"] = _rfc3339(start)
        if end is not None:
            params["end"] = _rfc3339(end)
        while True:
            page = self._request("GET", path, params=params) or {}
            yield from page.get("records", [])
            next_token = page.get("next_token") or None
            if not next_token:
                return
            params = {**params, "nextToken": next_token}

    def iter_cycles(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        page_size: int = MAX_PAGE_SIZE,
    ) -> Iterator[dict[str, Any]]:
        """Iterate ``GET /v2/cycle`` across pages (scope ``read:cycles``)."""
        yield from self._iter_collection(
            "v2/cycle", start=start, end=end, page_size=page_size
        )

    def iter_sleeps(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        page_size: int = MAX_PAGE_SIZE,
    ) -> Iterator[dict[str, Any]]:
        """Iterate ``GET /v2/activity/sleep`` across pages (scope ``read:sleep``)."""
        yield from self._iter_collection(
            "v2/activity/sleep", start=start, end=end, page_size=page_size
        )

    def iter_recoveries(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        page_size: int = MAX_PAGE_SIZE,
    ) -> Iterator[dict[str, Any]]:
        """Iterate ``GET /v2/recovery`` across pages (scope ``read:recovery``)."""
        yield from self._iter_collection(
            "v2/recovery", start=start, end=end, page_size=page_size
        )

    def iter_workouts(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        page_size: int = MAX_PAGE_SIZE,
    ) -> Iterator[dict[str, Any]]:
        """Iterate ``GET /v2/activity/workout`` across pages (scope ``read:workout``)."""
        yield from self._iter_collection(
            "v2/activity/workout", start=start, end=end, page_size=page_size
        )


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _extract_error_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            if key in payload:
                return str(payload[key])
    return fallback or "(no body)"
