"""Statistics, quota, and project commands."""

from typing import Annotated

import typer

from .. import client, render
from ..app import app, console
from ..helpers import emit_json, parse_timestamp


@app.command("stats")
def stats(
    project: Annotated[
        str | None,
        typer.Option("-p", "--project", help="Limit to a project (id, prefix, or path)."),
    ] = None,
    since: Annotated[
        str | None,
        typer.Option("--since", help="Start of the range: 7d, 24h, 2w, or YYYY-MM-DD."),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option("--until", help="End of the range: 7d, 24h, 2w, or YYYY-MM-DD."),
    ] = None,
    as_json: Annotated[bool, typer.Option("-j", "--json", help="Print raw JSON.")] = False,
) -> None:
    """Show aggregate usage statistics, quota limits, and per-model breakdown."""
    since_ms = parse_timestamp(since) if since else None
    until_ms = parse_timestamp(until) if until else None

    if since_ms is not None and until_ms is not None and until_ms < since_ms:
        raise client.OpenCodeError("--until must be later than --since.")

    with client.OpenCodeClient.connect() as service:
        project_id = service.resolve_project(project) if project else None
        data = service.get_stats(since=since_ms, until=until_ms, project=project_id)
        try:
            limits_data = service.get_limits()
        except client.HttpStatusError as exc:
            if exc.status_code not in (404, 405, 501):
                raise
            limits_data = None

    if as_json:
        payload = {"stats": data, "limits": limits_data}
        emit_json(payload)
        return

    context_parts: list[str] = []
    if since:
        context_parts.append(f"since {since}")
    if until:
        context_parts.append(f"until {until}")
    if project_id:
        context_parts.append(f"project {render.collapse_home(project or project_id)}")
    context = " · ".join(context_parts) or None

    console.print(render.stats_panel(data, context=context))

    if limits_data:
        console.print(render.limits_panel(limits_data))

    models = data.get("models") or []
    if models:
        console.print(render.models_table(models, width=console.width))


@app.command("limits")
def limits(
    as_json: Annotated[bool, typer.Option("-j", "--json", help="Print raw JSON.")] = False,
) -> None:
    """Show workspace quota and budget limits."""
    with client.OpenCodeClient.connect() as service:
        data = service.get_limits()

    if as_json:
        emit_json(data)
        return

    console.print(render.limits_panel(data))


@app.command("projects")
def projects(
    count: Annotated[bool, typer.Option("--count", help="Include session counts.")] = False,
    since: Annotated[
        str | None,
        typer.Option("--since", help="With --count: only sessions active since 7d/24h/ISO date."),
    ] = None,
    as_json: Annotated[bool, typer.Option("-j", "--json", help="Print raw JSON.")] = False,
) -> None:
    """List OpenCode projects."""
    since_ms = parse_timestamp(since) if since else None

    with client.OpenCodeClient.connect() as service:
        items = service.get_projects()
        counts: dict[str, int] | None = None
        if count:
            counts = {}
            for session in service.list_all_sessions(include_archived=True):
                if since_ms is not None and session.get("time", {}).get("updated", 0) < since_ms:
                    continue
                project_id = session.get("projectID")
                if isinstance(project_id, str):
                    counts[project_id] = counts.get(project_id, 0) + 1

    if as_json:
        payload = [
            {
                "id": item.get("id"),
                "canonical": item.get("canonical"),
                "sessions": counts.get(str(item.get("id")), 0) if counts is not None else None,
            }
            for item in items
        ]
        emit_json(payload)
        return

    if not items:
        console.print("[dim]No projects found.[/]")
        return

    console.print(render.projects_table(items, counts=counts, width=console.width))
