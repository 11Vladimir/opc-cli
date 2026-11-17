"""Message panels and Markdown transcripts."""

from typing import Any

from rich.console import Group
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from .common import format_time, format_tokens, model_label


def message_body(message: dict[str, Any]) -> Text:
    """Extract the readable text of a single message."""
    kind = message.get("type")
    if kind == "user":
        return Text(message.get("text") or "<empty>")

    if kind == "assistant":
        body = Text()
        for part in message.get("content", []):
            part_type = part.get("type")
            if part_type == "text" and part.get("text"):
                if body.plain:
                    body.append("\n\n")
                body.append(part["text"])
            elif part_type == "tool":
                if body.plain:
                    body.append("\n")
                body.append(f"-> {part.get('name', 'tool')}", style="dim")

        return body if body.plain else Text("<empty>", style="dim")
    return Text(message.get("text") or message.get("command") or "")


def message_markdown(message: dict[str, Any]) -> str | None:
    """Render one message as Markdown, or None for metadata-only events."""
    kind = message.get("type")
    if kind == "user":
        return message.get("text") or None
    if kind == "assistant":
        chunks: list[str] = []
        for part in message.get("content", []):
            part_type = part.get("type")
            if part_type == "text" and part.get("text"):
                chunks.append(part["text"])
            elif part_type == "tool":
                chunks.append(f"`-> {part.get('name', 'tool')}`")
        return "\n\n".join(chunks) or None
    if kind == "system":
        return message.get("text") or None
    return None


def session_markdown(transfer: dict[str, Any]) -> str:
    """Render an exported session (info + messages) as Markdown."""
    info = transfer.get("info", {})
    time = info.get("time", {})
    tokens = info.get("tokens", {})
    lines = [
        f"# {info.get('title') or '<untitled>'}",
        "",
        f"- **id**: `{info.get('id', '-')}`",
        f"- **agent**: {info.get('agent') or '-'}",
        f"- **model**: {model_label(info.get('model'))}",
        f"- **directory**: `{info.get('location', {}).get('directory') or '-'}`",
        f"- **updated**: {format_time(time.get('updated'))}",
        f"- **tokens**: {format_tokens(tokens.get('input', 0) + tokens.get('output', 0))}",
        "",
    ]

    for message in transfer.get("messages", []):
        body = message_markdown(message)
        if not body:
            continue
        kind = message.get("type") or "message"
        when = format_time(message.get("time", {}).get("created"))
        lines.extend([f"## {kind} · {when}", "", body, ""])

    return "\n".join(lines).rstrip() + "\n"


def message_panels(messages: list[dict[str, Any]]) -> Group:
    """Build coloured panels for a list of messages."""
    styles = {"user": "blue", "assistant": "green"}
    panels: list[Panel] = []
    for message in messages:
        kind = message.get("type") or "message"
        when = format_time(message.get("time", {}).get("created"))
        panels.append(
            Panel(
                message_body(message),
                title=escape(f"{kind}  {when}"),
                border_style=styles.get(kind, "dim"),
            )
        )
    return Group(*panels)
