"""opc - a small CLI for managing OpenCode sessions."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("opc-cli")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0"
