"""Client exceptions."""


class OpenCodeError(RuntimeError):
    """Raised when the OpenCode service cannot be reached or rejects a request."""


class HttpStatusError(OpenCodeError):
    """Raised when the service answers with an HTTP error status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
