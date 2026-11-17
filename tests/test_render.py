import datetime as dt
from pathlib import Path

from opc_cli import render


def test_format_tokens_small():
    assert render.format_tokens(999) == "999"


def test_format_tokens_thousands():
    assert render.format_tokens(1500) == "1.5k"


def test_format_tokens_millions():
    assert render.format_tokens(2_500_000) == "2.5M"


def test_short_id_is_unchanged():
    assert render.short_id("ses_abc") == "ses_abc"


def test_short_id_is_truncated():
    assert render.short_id("ses_e2b0571afffetUGR478SIJcizV") == "ses_e2b0571af"


def test_model_label_missing():
    assert render.model_label(None) == "-"


def test_model_label_full():
    model = {"providerID": "opencode-go", "id": "deepseek", "variant": "high"}
    assert render.model_label(model) == "opencode-go/deepseek (high)"


def test_session_state_running():
    assert render.session_state({"time": {"busy": 1}}) == "[green]*[/]"


def test_session_state_idle():
    assert render.session_state({"time": {"idle": 1}}) == " "


def test_session_state_archived():
    assert render.session_state({"time": {"idle": 1, "archived": 2}}) == "[dim]a[/]"


def test_sessions_table_archived_legend():
    rows = [{"id": "ses_1", "title": "Old", "time": {"archived": 2}}]
    line = render.legend(rows)
    assert line is not None
    assert "archived" in line.plain


def test_sessions_table_no_archived_legend():
    rows = [{"id": "ses_1", "title": "New"}]
    table = render.sessions_table(rows, total=1)
    assert table.caption is not None
    assert "archived" not in table.caption


def test_session_state_subagent():
    assert render.session_state({"parentID": "ses_root", "time": {"idle": 1}}) == "[dim]↳[/]"


def test_format_id():
    assert render.format_id("ses_e2b0571afffetUGR478SIJcizV") == "[dim]ses_[/][cyan]e2b0571af[/]"


def test_format_agent():
    assert render.format_agent(None) == "[dim]-[/]"
    assert render.format_agent("build") == "[cyan]build[/]"


def test_format_styled_tokens():
    assert render.format_styled_tokens(0) == "[dim]0[/]"
    assert render.format_styled_tokens(1500) == "1.5k"
    assert render.format_styled_tokens(2_500_000) == "[yellow]2.5M[/]"


def test_format_time_missing():
    assert render.format_time(None) == "-"
    assert render.format_time(0) == "-"


def test_format_short_time_today():
    now_ms = int(dt.datetime.now().timestamp() * 1000)
    assert render.format_short_time(now_ms) == "just now"
    assert render.format_short_time(now_ms - 5 * 60 * 1000) == "5m ago"
    assert render.format_short_time(now_ms - 3 * 3600 * 1000) == "3h ago"
    assert render.format_short_time(now_ms - 2 * 86_400 * 1000) == "2d ago"


def test_format_short_time_previous_year():
    moment = dt.datetime(dt.datetime.now().year - 5, 1, 2, 3, 4)
    expected = moment.strftime("%Y-%m-%d")
    assert render.format_short_time(int(moment.timestamp() * 1000)) == expected


def test_collapse_home(monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: Path("/home/u"))
    assert render.collapse_home("/home/u/x") == "~/x"
    assert render.collapse_home("/home/u") == "~"
    assert render.collapse_home("/tmp/x") == "/tmp/x"


def test_is_current_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    assert render.is_current_directory(str(tmp_path))
    assert not render.is_current_directory(str(tmp_path / "nested"))


def test_is_current_directory_with_explicit_cwd(tmp_path):
    assert render.is_current_directory(str(tmp_path), cwd=tmp_path)
    assert not render.is_current_directory(str(tmp_path / "nested"), cwd=tmp_path)


def test_format_short_time_with_reference():
    reference = dt.datetime(2026, 1, 2, 12, 0)
    moment = reference - dt.timedelta(minutes=5)
    assert render.format_short_time(int(moment.timestamp() * 1000), now=reference) == "5m ago"


def test_session_markdown():
    transfer = {
        "info": {
            "id": "ses_1",
            "title": "Demo",
            "agent": "build",
            "model": {"providerID": "p", "id": "m"},
            "location": {"directory": "/tmp"},
            "time": {"updated": 1_700_000_000_000},
            "tokens": {"input": 10, "output": 5},
        },
        "messages": [
            {"type": "user", "text": "hello", "time": {"created": 1_700_000_000_000}},
            {"type": "agent-switched", "time": {"created": 1_700_000_001_000}},
            {
                "type": "assistant",
                "content": [
                    {"type": "text", "text": "hi"},
                    {"type": "tool", "name": "read"},
                ],
                "time": {"created": 1_700_000_002_000},
            },
        ],
    }
    markdown = render.session_markdown(transfer)
    assert markdown.startswith("# Demo")
    assert "## user" in markdown
    assert "hello" in markdown
    assert "## assistant" in markdown
    assert "`-> read`" in markdown
    assert "agent-switched" not in markdown


def test_message_panels_group():
    messages = [
        {"type": "user", "text": "hello", "time": {"created": 1_700_000_000_000}},
        {
            "type": "assistant",
            "content": [
                {"type": "text", "text": "hi"},
                {"type": "tool", "name": "read"},
            ],
            "time": {"created": 1_700_000_001_000},
        },
    ]
    group = render.message_panels(messages)
    assert len(group.renderables) == 2


def test_sessions_table_caption_with_more():
    rows = [{"id": "ses_1", "title": "One"}, {"id": "ses_2", "title": "Two"}]
    table = render.sessions_table(rows, total=5)
    assert table.caption == "2 sessions (+3 more)"


def test_sessions_table_caption_exact():
    rows = [{"id": "ses_1", "title": "One"}]
    table = render.sessions_table(rows, total=1)
    assert table.caption == "1 session"


def test_sessions_table_subagent_legend():
    rows = [{"id": "ses_1", "title": "One", "parentID": "ses_root"}]
    line = render.legend(rows)
    assert line is not None
    assert "subagent" in line.plain


def test_legend_running_and_archived():
    rows = [
        {"id": "ses_1", "time": {"busy": 1}},
        {"id": "ses_2", "time": {"archived": 1}},
    ]
    line = render.legend(rows)
    assert line is not None
    assert "running" in line.plain
    assert "archived" in line.plain


def test_legend_empty_when_no_markers():
    assert render.legend([{"id": "ses_1", "title": "One"}]) is None


def test_plural():
    assert render.plural(1, "session") == "1 session"
    assert render.plural(2, "session") == "2 sessions"
    assert render.plural(1, "project") == "1 project"


def test_limits_panel():
    future_ms = int(dt.datetime.now().timestamp() * 1000) + 3600 * 1000
    data = {
        "workspace": {"name": "Default"},
        "go": {
            "rolling": {"percent": 10, "limited": False, "resetsAt": future_ms},
            "weekly": {"percent": 65, "limited": False, "resetsAt": future_ms},
            "monthly": {"percent": 90, "limited": True, "resetsAt": future_ms},
        },
        "budgets": [],
    }
    panel = render.limits_panel(data)
    assert panel.title == "limits (Default)"


def test_models_table():
    models = [
        {
            "model": {"providerID": "opencode-go", "id": "m1", "variant": "high"},
            "steps": 10,
            "tokens": {"input": 1000, "output": 200, "reasoning": 50, "cache": {"read": 5000}},
        }
    ]
    table = render.models_table(models)
    assert table.row_count == 1


def test_format_directory_highlights_cwd(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    assert render.format_directory(str(tmp_path)).startswith("[green]")
    assert render.format_directory("/tmp").startswith("[dim]")


def test_projects_table():
    projects = [
        {"id": "p123456789", "canonical": "/tmp", "time": {"active": 1_700_000_000_000}},
        {"id": "p987654321", "canonical": "/var", "time": {"active": 1_700_000_100_000}},
    ]
    table = render.projects_table(projects, counts={"p123456789": 3})
    assert table.row_count == 2
    assert table.caption == "2 projects"


def test_limits_panel_budgets():
    data = {
        "workspace": {"name": "Default"},
        "go": {},
        "budgets": [{"limit": 10.0, "spent": 2.5, "resetsAt": 1_800_000_000_000}],
    }
    panel = render.limits_panel(data)
    assert panel.title == "limits (Default)"


def test_limits_panel_shows_console_url():
    from io import StringIO

    from rich.console import Console

    data = {
        "workspace": {"name": "Default", "usageURL": "https://example.test/usage"},
        "go": {},
        "budgets": [],
    }
    buffer = StringIO()
    Console(file=buffer, width=200).print(render.limits_panel(data))
    assert "https://example.test/usage" in buffer.getvalue()


def test_stats_panel_context_title():
    panel = render.stats_panel({"sessions": 1}, context="since 7d · project api")
    assert panel.title == "usage · since 7d · project api"


def test_projects_table_survives_missing_cwd(monkeypatch):
    def boom() -> Path:
        raise OSError("cwd is gone")

    monkeypatch.setattr(Path, "cwd", boom)
    table = render.projects_table([{"id": "p1", "canonical": "/tmp"}])
    assert table.row_count == 1
