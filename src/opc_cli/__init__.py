"""opc - a small CLI for managing OpenCode sessions."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("opc-cli")
except PackageNotFoundError:  # source checkout without an installed dist
    __version__ = "0.0.0"
