"""Service discovery and connection parameters."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import orjson

from .errors import OpenCodeError

type PathResolver = Callable[[], Path | None]


def _env_override() -> Path | None:
    val = os.environ.get("OPC_SERVICE_FILE")
    return Path(val).expanduser() if val else None


def _xdg_state() -> Path | None:
    val = os.environ.get("XDG_STATE_HOME")
    return Path(val) / "opencode" / "service.json" if val else None


def _default_state() -> Path:
    return Path.home() / ".local" / "state" / "opencode" / "service.json"


RESOLVERS: tuple[PathResolver, ...] = (_env_override, _xdg_state, _default_state)


def service_file() -> Path:
    """Return the path of the service registration file."""

    for resolve in RESOLVERS:
        if (path := resolve()) is not None:
            return path

    raise AssertionError("unreachable")


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Connection parameters for the OpenCode background service."""

    url: str
    password: str

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Load service connection info from a registration JSON file."""

        try:
            info = orjson.loads(path.read_bytes())
        except FileNotFoundError:
            msg = f"OpenCode is not running: {path} does not exist. Try `opencode service status`."
            raise OpenCodeError(msg) from None
        except (OSError, orjson.JSONDecodeError) as exc:
            raise OpenCodeError(f"Cannot read {path}: {exc}") from exc

        if not isinstance(info, dict):
            raise OpenCodeError(f"Invalid format in {path}: expected a JSON object")

        try:
            url = info["url"]
            password = info["password"]
        except KeyError as exc:
            raise OpenCodeError(f"{path} is missing the {exc.args[0]!r} field") from exc

        if not isinstance(url, str) or not isinstance(password, str):
            raise OpenCodeError(f"{path} has invalid 'url' or 'password' type")

        return cls(
            url=url,
            password=password,
        )
