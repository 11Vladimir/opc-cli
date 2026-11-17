"""API routes and enums."""

from enum import StrEnum


class Route(StrEnum):
    """OpenCode HTTP API endpoints."""

    SESSIONS = "/api/session"
    STATS = "/api/experimental/session/stats"
    LIMITS = "/api/experimental/usage/limits"
    PROJECTS = "/api/project"

    @classmethod
    def session(cls, session_id: str) -> str:
        return f"{cls.SESSIONS}/{session_id}"

    @classmethod
    def messages(cls, session_id: str) -> str:
        return f"{cls.session(session_id)}/message"

    @classmethod
    def fork(cls, session_id: str) -> str:
        return f"{cls.session(session_id)}/fork"

    @classmethod
    def move(cls, session_id: str) -> str:
        return f"{cls.session(session_id)}/move"

    @classmethod
    def export(cls, session_id: str) -> str:
        return f"/api/experimental/session/{session_id}/export"


class SortOrder(StrEnum):
    """Session sort order."""

    ASC = "asc"
    DESC = "desc"
