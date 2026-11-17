"""Constants shared by the HTTP client."""

import httpx

DEFAULT_TIMEOUT = 10.0
EXPORT_TIMEOUT = 60.0
PAGE_SIZE = 100
MAX_SESSIONS = 10_000
SESSION_ID_LENGTH = 30
RETRY_ATTEMPTS = 3
RETRY_DELAY = 0.15
RETRYABLE_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)
RETRY_METHODS = frozenset({"GET", "HEAD"})
