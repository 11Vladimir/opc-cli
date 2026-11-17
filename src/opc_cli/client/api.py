"""HTTP client bound to an OpenCode service."""

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Self, cast

import httpx
import orjson

from .config import Endpoint, service_file
from .constants import (
    DEFAULT_TIMEOUT,
    EXPORT_TIMEOUT,
    MAX_SESSIONS,
    PAGE_SIZE,
    RETRY_ATTEMPTS,
    RETRY_DELAY,
    RETRY_METHODS,
    RETRYABLE_ERRORS,
    SESSION_ID_LENGTH,
)
from .errors import HttpStatusError, OpenCodeError
from .routes import Route, SortOrder


class OpenCodeClient:
    """Thin wrapper over httpx.Client bound to an OpenCode service."""

    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    @classmethod
    def _discover_endpoint(cls) -> Endpoint:
        """Discover the running OpenCode service endpoint."""
        return Endpoint.from_file(service_file())

    @classmethod
    def connect(cls, endpoint: Endpoint | None = None) -> Self:
        """Create an authenticated client for the running service."""
        ep = endpoint or cls._discover_endpoint()

        http = httpx.Client(
            base_url=ep.url,
            auth=httpx.BasicAuth(
                username="opencode",
                password=ep.password,
            ),
            timeout=DEFAULT_TIMEOUT,
        )
        return cls(http)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self._http.close()

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """Extract a short error message from a failed HTTP response."""
        if not response.content:
            return ""

        try:
            payload = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            return response.text.strip()[:200]

        if isinstance(payload, dict):
            for key in ("message", "error", "detail"):
                val = payload.get(key)
                if isinstance(val, str) and val:
                    return val
                if isinstance(val, dict) and isinstance(val.get("message"), str):
                    return val["message"]

            errors = payload.get("errors")
            if isinstance(errors, list) and errors:
                first = errors[0]
                if isinstance(first, str) and first:
                    return first
                if isinstance(first, dict) and isinstance(first.get("message"), str):
                    return first["message"]
        return ""

    @staticmethod
    def _session_params(
        *,
        directory: str | None,
        search: str | None,
        project: str | None,
        roots_only: bool,
        limit: int,
        order: SortOrder,
        include_archived: bool,
    ) -> dict[str, str | int]:
        """Translate high-level filters into query parameters."""
        params: dict[str, str | int] = {"limit": limit, "order": order}
        if directory:
            params["directory"] = str(Path(directory).expanduser().resolve())
        if search:
            params["search"] = search
        if roots_only:
            params["parentID"] = "null"
        if project:
            params["project"] = project
        if not include_archived:
            params["archived"] = "false"
        return params

    @staticmethod
    def is_empty_session(session: dict[str, Any]) -> bool:
        """Return True if a session is idle, untitled, and has zero tokens."""
        time = session.get("time", {})
        if "busy" in time and "idle" not in time:
            return False
        tokens = session.get("tokens", {})
        total = tokens.get("input", 0) + tokens.get("output", 0)
        return not session.get("title") and total == 0

    def list_sessions_page(
        self,
        *,
        directory: str | None = None,
        search: str | None = None,
        project: str | None = None,
        roots_only: bool = False,
        limit: int = 30,
        order: SortOrder = SortOrder.ASC,
        include_archived: bool = False,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Fetch a single page of sessions and report whether more exist.

        The service returns a ``next`` cursor even on the last page, so the page
        is fetched with ``limit + 1`` and the extra row signals "more".
        """
        params = self._session_params(
            directory=directory,
            search=search,
            project=project,
            roots_only=roots_only,
            limit=limit + 1,
            order=order,
            include_archived=include_archived,
        )
        payload = self._json(method="GET", path=Route.SESSIONS, params=params)
        data = payload["data"]
        return data[:limit], len(data) > limit

    def _iter_sessions(
        self,
        *,
        directory: str | None = None,
        search: str | None = None,
        project: str | None = None,
        roots_only: bool = False,
        order: SortOrder = SortOrder.ASC,
        include_archived: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Yield sessions across every cursor page returned by the service."""
        cursor: str | None = None
        seen: set[str] = set()

        while True:
            params = self._session_params(
                directory=directory,
                search=search,
                project=project,
                roots_only=roots_only,
                limit=PAGE_SIZE,
                order=order,
                include_archived=include_archived,
            )
            if cursor:
                params["cursor"] = cursor

            payload = self._json(method="GET", path=Route.SESSIONS, params=params)
            data = payload["data"]
            yield from data

            # The service returns a non-null cursor even on the last page, so a
            # short page is treated as the end marker. This assumes the server
            # honours the requested PAGE_SIZE (verified with limits up to 1000
            # on OpenCode 2.2.x); if a future cap is lower, switch to following
            # the cursor until it yields an empty page.
            if len(data) < PAGE_SIZE:
                return

            cursor = (payload.get("cursor") or {}).get("next")
            if not cursor or cursor in seen:
                return
            seen.add(cursor)

    def list_all_sessions(
        self,
        *,
        directory: str | None = None,
        search: str | None = None,
        project: str | None = None,
        roots_only: bool = False,
        order: SortOrder = SortOrder.ASC,
        include_archived: bool = False,
        max_sessions: int = MAX_SESSIONS,
    ) -> list[dict[str, Any]]:
        """Fetch sessions across all pages, stopping at *max_sessions*."""
        sessions: list[dict[str, Any]] = []
        for session in self._iter_sessions(
            directory=directory,
            search=search,
            project=project,
            roots_only=roots_only,
            order=order,
            include_archived=include_archived,
        ):
            sessions.append(session)
            if len(sessions) >= max_sessions:
                break
        return sessions

    def _all_sessions(self) -> list[dict[str, Any]]:
        """Fetch the full session list used for prefix resolution and cleanup."""
        return self.list_all_sessions(include_archived=True)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Send an HTTP request and return decoded JSON (or None on empty body)."""
        content = orjson.dumps(json) if json is not None else None
        headers = {"Content-Type": "application/json"} if content is not None else None
        attempts = RETRY_ATTEMPTS if method.upper() in RETRY_METHODS else 1

        response: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                response = self._http.request(
                    method,
                    path,
                    params=params,
                    content=content,
                    headers=headers,
                    timeout=timeout,
                )
                break
            except RETRYABLE_ERRORS as exc:
                if attempt + 1 >= attempts:
                    raise OpenCodeError(f"Cannot reach the OpenCode service: {exc}") from exc
                time.sleep(RETRY_DELAY * (attempt + 1))
            except httpx.HTTPError as exc:
                raise OpenCodeError(f"Cannot reach the OpenCode service: {exc}") from exc

        if response is None:
            raise OpenCodeError(f"Request to {path} produced no response.")

        if response.status_code >= 400:
            detail = self._error_detail(response)
            suffix = f" — {detail}" if detail else ""
            message = f"{response.status_code} {response.reason_phrase}: {path}{suffix}"
            raise HttpStatusError(response.status_code, message)

        if not response.content:
            return None

        try:
            payload = orjson.loads(response.content)
        except orjson.JSONDecodeError as exc:
            raise OpenCodeError(f"Invalid JSON response from {path}: {exc}") from exc

        if not isinstance(payload, (dict, list)):
            raise OpenCodeError(f"Unexpected response from {path}: expected a JSON object or array")

        return payload

    def _json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Like `_request`, but require a non-empty JSON object body."""
        payload = self._request(method, path, params=params, json=json, timeout=timeout)

        if payload is None:
            raise OpenCodeError(f"Empty response from {path}; expected JSON.")

        if not isinstance(payload, dict):
            raise OpenCodeError(f"Unexpected response from {path}: expected a JSON object")

        return payload

    def _json_list(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json: dict[str, Any] | None = None,
    ) -> list[Any]:
        """Like `_request`, but require a JSON array body."""
        payload = self._request(method, path, params=params, json=json)

        if not isinstance(payload, list):
            raise OpenCodeError(f"Unexpected response from {path}: expected a JSON array")

        return payload

    def list_sessions(
        self,
        *,
        directory: str | None = None,
        search: str | None = None,
        project: str | None = None,
        roots_only: bool = False,
        limit: int = 30,
        order: SortOrder = SortOrder.ASC,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch sessions matching the given filters."""
        params = self._session_params(
            directory=directory,
            search=search,
            project=project,
            roots_only=roots_only,
            limit=limit,
            order=order,
            include_archived=include_archived,
        )
        return self._json(method="GET", path=Route.SESSIONS, params=params)["data"]

    def get_session(self, session_id: str) -> dict[str, Any]:
        """Fetch details of a single session."""
        return self._json(method="GET", path=Route.session(session_id))["data"]

    def get_messages(self, session_id: str, *, limit: int = 6) -> list[dict[str, Any]]:
        """Fetch the latest messages of a session in chronological order."""
        messages = self._json(
            method="GET",
            path=Route.messages(session_id),
            params={"limit": limit, "order": "desc"},
        )["data"]
        return list(reversed(messages))

    def get_stats(
        self,
        *,
        since: int | None = None,
        until: int | None = None,
        project: str | None = None,
    ) -> dict[str, Any]:
        """Fetch aggregate usage statistics, optionally limited by time or project."""
        params: dict[str, str | int] = {}
        if since is not None:
            params["from"] = since
        if until is not None:
            params["to"] = until
        if project:
            params["project"] = project
        return self._json(method="GET", path=Route.STATS, params=params or None)["data"]

    def get_limits(self) -> dict[str, Any]:
        """Fetch workspace quota and budget limits."""
        return self._json(method="GET", path=Route.LIMITS)["data"]

    def get_projects(self) -> list[dict[str, Any]]:
        """List registered OpenCode projects."""
        return cast(list[dict[str, Any]], self._json_list(method="GET", path=Route.PROJECTS))

    def resolve_project(self, ref: str) -> str:
        """Resolve a project id, id prefix, or canonical path to a project id."""
        ref = ref.strip()
        target: Path | None = None
        if ref == "." or "/" in ref or ref.startswith("~"):
            target = Path(ref).expanduser().resolve()

        matches: list[str] = []
        for project in self.get_projects():
            project_id = str(project.get("id", ""))
            if not project_id:
                continue
            if project_id == ref or project_id.startswith(ref):
                matches.append(project_id)
                continue
            canonical = project.get("canonical")
            if target is not None and isinstance(canonical, str):
                try:
                    if Path(canonical).resolve() == target:
                        matches.append(project_id)
                except OSError:
                    continue

        matches = list(dict.fromkeys(matches))
        if not matches:
            raise OpenCodeError(f"No project matches {ref!r}.")
        if len(matches) > 1:
            listing = "\n".join(f"  {match}" for match in matches[:8])
            raise OpenCodeError(f"{ref!r} is ambiguous:\n{listing}")
        return matches[0]

    def rename_session(self, session_id: str, title: str) -> None:
        """Update a session title."""
        self._request(method="PATCH", path=Route.session(session_id), json={"title": title})

    def set_archived(self, session_id: str, *, archived: bool) -> None:
        """Archive or restore a session."""
        self._request(
            method="PATCH",
            path=Route.session(session_id),
            json={"archived": archived},
        )

    def move_session(self, session_id: str, directory: str | Path) -> None:
        """Move a session to another working directory."""
        target = Path(directory).expanduser().resolve()
        self._request(method="POST", path=Route.move(session_id), json={"directory": str(target)})

    def fork_session(self, session_id: str, *, before: str | None = None) -> dict[str, Any]:
        """Fork a session and return the newly created session."""
        body = {"before": before} if before else {}
        return self._json(method="POST", path=Route.fork(session_id), json=body)["data"]

    def export_session(self, session_id: str, *, sanitize: bool = False) -> dict[str, Any]:
        """Export a session transfer containing its info and messages."""
        return self._json(
            method="GET",
            path=Route.export(session_id),
            params={"sanitize": "true" if sanitize else "false"},
            timeout=EXPORT_TIMEOUT,
        )["data"]

    def resolve_sessions(self, refs: list[str]) -> list[str]:
        """Resolve one or more session ids or unique prefixes in a single fetch."""
        all_ids: list[str] | None = None
        resolved: list[str] = []

        for raw in refs:
            ref = raw.strip()
            if ref.startswith("ses_") and len(ref) >= SESSION_ID_LENGTH:
                resolved.append(ref)
                continue

            if all_ids is None:
                all_ids = sorted(session["id"] for session in self._all_sessions())

            matches = [sid for sid in all_ids if sid.startswith(ref)]

            if not matches:
                raise OpenCodeError(f"No session id starts with {ref!r}.")

            if len(matches) > 1:
                listing = "\n".join(f"  {match}" for match in matches[:8])
                raise OpenCodeError(f"{ref!r} is ambiguous:\n{listing}")
            resolved.append(matches[0])

        return list(dict.fromkeys(resolved))

    def resolve_session(self, ref: str) -> str:
        """Turn a full session id or a unique prefix into a full id."""
        return self.resolve_sessions([ref])[0]

    def delete_session(self, session_id: str) -> None:
        """Delete a session permanently."""
        self._request(method="DELETE", path=Route.session(session_id))

    def list_empty_sessions(self) -> list[dict[str, Any]]:
        """Return all idle, untitled sessions with zero tokens."""
        return [
            session for session in self._all_sessions() if self.is_empty_session(session=session)
        ]
