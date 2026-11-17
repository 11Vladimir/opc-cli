import datetime as dt
from collections.abc import Callable
from pathlib import Path

import httpx
import orjson
import pytest
from typer.testing import CliRunner

from opc_cli import __version__, cli, client

runner = CliRunner()

Handler = Callable[[httpx.Request], httpx.Response]


def _patch_service(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    """Route all client traffic through an in-memory transport."""
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")
    monkeypatch.setattr(
        client.OpenCodeClient,
        "connect",
        classmethod(lambda cls, endpoint=None: client.OpenCodeClient(http)),
    )


def test_ls_renders_sessions(monkeypatch):
    sessions = {
        "data": [
            {"id": "ses_abc111", "title": "First", "time": {"updated": 1_700_000_000_000}},
            {"id": "ses_abc222", "title": "Second", "time": {"updated": 1_700_000_100_000}},
        ]
    }
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json=sessions))

    result = runner.invoke(cli.app, ["ls"])

    assert result.exit_code == 0
    assert "First" in result.stdout
    assert "2 sessions" in result.stdout


def test_ls_empty(monkeypatch):
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json={"data": []}))

    result = runner.invoke(cli.app, ["ls"])

    assert result.exit_code == 0
    assert "No sessions found." in result.stdout


def test_stats_renders_panels(monkeypatch):
    payload = {
        "data": {
            "sessions": 3,
            "prompts": 7,
            "models": [
                {
                    "model": {"providerID": "opencode-go", "id": "m1"},
                    "steps": 4,
                    "tokens": {"input": 1000, "output": 100},
                }
            ],
        }
    }
    limits = {
        "data": {
            "workspace": {"id": "wrk_1", "name": "Default", "usageURL": "https://x"},
            "go": {"rolling": {"percent": 10, "limited": False, "resetsAt": 0}},
            "budgets": [],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == client.Route.STATS:
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json=limits)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["stats"])

    assert result.exit_code == 0
    assert "usage" in result.stdout
    assert "limits (Default)" in result.stdout
    assert "opencode-go/m1" in result.stdout


def test_limits_renders_meters(monkeypatch):
    limits = {
        "data": {
            "workspace": {"id": "wrk_1", "name": "Default", "usageURL": "https://x"},
            "go": {
                "rolling": {"percent": 10, "limited": False, "resetsAt": 0},
                "weekly": {"percent": 70, "limited": False, "resetsAt": 0},
                "monthly": {"percent": 95, "limited": True, "resetsAt": 0},
            },
            "budgets": [],
        }
    }
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json=limits))

    result = runner.invoke(cli.app, ["limits"])

    assert result.exit_code == 0
    assert "rolling" in result.stdout
    assert "monthly" in result.stdout


def test_rm_requires_confirmation(monkeypatch):
    sessions = {"data": [{"id": "ses_abc111", "title": "First"}]}
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["rm", "ses_abc111"], input="n\n")

    assert result.exit_code != 0
    assert not any(method == "DELETE" for method, _ in calls)


def test_rm_deletes_with_yes(monkeypatch):
    sessions = {"data": [{"id": "ses_abc111", "title": "First"}]}
    deleted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            deleted.append(request.url.path)
            return httpx.Response(204)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["rm", "-y", "ses_abc111"])

    assert result.exit_code == 0
    assert deleted == ["/api/session/ses_abc111"]
    assert "Deleted" in result.stdout


def test_clean_deletes_empty_sessions(monkeypatch):
    sessions = {
        "data": [
            {"id": "ses_empty", "tokens": {"input": 0, "output": 0}, "time": {"idle": 1}},
            {"id": "ses_used", "title": "Keep", "tokens": {"input": 10, "output": 5}},
        ]
    }
    deleted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            deleted.append(request.url.path)
            return httpx.Response(204)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["clean", "-y"])

    assert result.exit_code == 0
    assert deleted == ["/api/session/ses_empty"]


def test_clean_nothing_to_do(monkeypatch):
    sessions = {"data": [{"id": "ses_used", "title": "Keep", "tokens": {"input": 10}}]}
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json=sessions))

    result = runner.invoke(cli.app, ["clean", "-y"])

    assert result.exit_code == 0
    assert "No empty sessions found." in result.stdout


def test_error_is_reported_with_exit_code(monkeypatch):
    _patch_service(monkeypatch, lambda request: httpx.Response(500, json={"error": "boom"}))

    result = runner.invoke(cli.app, ["ls"])

    assert result.exit_code == 1


def test_resume_changes_dir_and_execs(monkeypatch, tmp_path):
    session_id = "ses_e2b0571afffetUGR478SIJcizV"
    payload = {
        "data": {
            "id": session_id,
            "location": {"directory": str(tmp_path)},
        }
    }
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json=payload))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/opencode")

    seen_chdir: list[Path] = []
    seen_exec: list[tuple[str, list[str]]] = []
    monkeypatch.setattr("os.chdir", lambda path: seen_chdir.append(Path(path)))
    monkeypatch.setattr("os.execvp", lambda file, args: seen_exec.append((file, list(args))))

    result = runner.invoke(cli.app, ["resume", session_id])

    assert result.exit_code == 0
    assert seen_chdir == [tmp_path]
    assert seen_exec == [("/usr/bin/opencode", ["/usr/bin/opencode", "-s", session_id])]


def test_ls_json(monkeypatch):
    sessions = {
        "data": [
            {"id": "ses_abc111", "title": "First"},
            {"id": "ses_abc222", "title": "Second"},
        ]
    }
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json=sessions))

    result = runner.invoke(cli.app, ["ls", "--json"])

    assert result.exit_code == 0
    payload = orjson.loads(result.stdout)
    assert payload["total"] == 2
    assert [s["id"] for s in payload["sessions"]] == ["ses_abc111", "ses_abc222"]


def test_limits_json(monkeypatch):
    limits = {
        "data": {
            "workspace": {"id": "wrk_1", "name": "Default", "usageURL": "https://x"},
            "go": {"rolling": {"percent": 10, "limited": False, "resetsAt": 0}},
            "budgets": [],
        }
    }
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json=limits))

    result = runner.invoke(cli.app, ["limits", "-j"])

    assert result.exit_code == 0
    payload = orjson.loads(result.stdout)
    assert payload["workspace"]["name"] == "Default"


def test_stats_json(monkeypatch):
    stats = {
        "data": {
            "sessions": 3,
            "models": [
                {
                    "model": {"providerID": "opencode-go", "id": "m1"},
                    "steps": 2,
                    "tokens": {"input": 10, "output": 5},
                }
            ],
        }
    }
    limits = {
        "data": {
            "workspace": {"id": "wrk_1", "name": "Default", "usageURL": "https://x"},
            "go": {"rolling": {"percent": 10, "limited": False, "resetsAt": 0}},
            "budgets": [],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == client.Route.STATS:
            return httpx.Response(200, json=stats)
        return httpx.Response(200, json=limits)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["stats", "-j"])

    assert result.exit_code == 0
    payload = orjson.loads(result.stdout)
    assert payload["stats"]["sessions"] == 3
    assert payload["limits"]["workspace"]["name"] == "Default"
    assert payload["stats"]["models"][0]["model"]["id"] == "m1"


def test_stats_json_without_limits(monkeypatch):
    stats = {"data": {"sessions": 1, "models": []}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == client.Route.STATS:
            return httpx.Response(200, json=stats)
        return httpx.Response(404, json={"error": "no limits"})

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["stats", "-j"])

    assert result.exit_code == 0
    assert orjson.loads(result.stdout)["limits"] is None


def test_show_rejects_zero_messages(monkeypatch):
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json={"data": []}))

    result = runner.invoke(cli.app, ["show", "-m", "0", "ses_abc"])

    assert result.exit_code == 2


def test_ls_rejects_zero_limit(monkeypatch):
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json={"data": []}))

    result = runner.invoke(cli.app, ["ls", "-n", "0"])

    assert result.exit_code == 2


def test_version_flag():
    result = runner.invoke(cli.app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"opc {__version__}"


def test_resume_print_only(monkeypatch, tmp_path):
    session_id = "ses_e2b0571afffetUGR478SIJcizV"
    payload = {"data": {"id": session_id, "location": {"directory": str(tmp_path)}}}
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json=payload))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/opencode")

    execs: list[tuple[str, list[str]]] = []
    monkeypatch.setattr("os.execvp", lambda file, args: execs.append((file, list(args))))

    result = runner.invoke(cli.app, ["resume", "--print", session_id])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"cd {tmp_path} && /usr/bin/opencode -s {session_id}"
    assert execs == []


def test_resume_print_without_directory(monkeypatch):
    session_id = "ses_e2b0571afffetUGR478SIJcizV"
    payload = {"data": {"id": session_id, "location": {}}}
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json=payload))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/opencode")

    result = runner.invoke(cli.app, ["resume", "-p", session_id])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"/usr/bin/opencode -s {session_id}"


def test_rename_command(monkeypatch):
    sessions = {"data": [{"id": "ses_abc111", "title": "Old"}]}
    seen: list[tuple[str, str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            seen.append((request.method, request.url.path, request.content))
            return httpx.Response(204)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["rename", "ses_abc", "New title"])

    assert result.exit_code == 0
    assert seen == [("PATCH", "/api/session/ses_abc111", b'{"title":"New title"}')]
    assert "Renamed" in result.stdout


def test_mv_command(monkeypatch, tmp_path):
    sessions = {"data": [{"id": "ses_abc111", "title": "Old"}]}
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen.append((request.method, request.url.path))
            return httpx.Response(204)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["mv", "ses_abc", str(tmp_path)])

    assert result.exit_code == 0
    assert seen == [("POST", "/api/session/ses_abc111/move")]
    assert "Moved" in result.stdout


def test_mv_missing_directory(monkeypatch):
    sessions = {"data": [{"id": "ses_abc111", "title": "Old"}]}
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json=sessions))

    result = runner.invoke(cli.app, ["mv", "ses_abc", "/definitely/missing/dir"])

    assert result.exit_code == 1


def test_fork_command(monkeypatch):
    sessions = {"data": [{"id": "ses_abc111", "title": "Old"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/fork"):
            return httpx.Response(200, json={"data": {"id": "ses_forked", "title": "Old"}})
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["fork", "ses_abc"])

    assert result.exit_code == 0
    assert "ses_forked" in result.stdout


def test_export_markdown(monkeypatch):
    sessions = {"data": [{"id": "ses_abc111", "title": "Old"}]}
    transfer = {
        "data": {
            "info": {"id": "ses_abc111", "title": "Demo"},
            "messages": [{"type": "user", "text": "hello", "time": {"created": 0}}],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "/export" in request.url.path:
            return httpx.Response(200, json=transfer)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["export", "ses_abc"])

    assert result.exit_code == 0
    assert result.stdout.startswith("# Demo")
    assert "hello" in result.stdout


def test_export_json_to_file(monkeypatch, tmp_path):
    sessions = {"data": [{"id": "ses_abc111", "title": "Old"}]}
    transfer = {"data": {"info": {"id": "ses_abc111"}, "messages": []}}

    def handler(request: httpx.Request) -> httpx.Response:
        if "/export" in request.url.path:
            return httpx.Response(200, json=transfer)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)
    target = tmp_path / "session.json"

    result = runner.invoke(cli.app, ["export", "ses_abc", "-j", "-o", str(target)])

    assert result.exit_code == 0
    assert orjson.loads(target.read_text())["info"]["id"] == "ses_abc111"


def test_rm_reports_partial_failure(monkeypatch):
    sessions = {"data": [{"id": "ses_aaa111"}, {"id": "ses_bbb222"}]}
    deleted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            path = request.url.path
            if path.endswith("ses_bbb222"):
                return httpx.Response(500, json={"error": "boom"})
            deleted.append(path)
            return httpx.Response(204)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["rm", "-y", "ses_aaa", "ses_bbb"])

    assert result.exit_code == 1
    assert deleted == ["/api/session/ses_aaa111"]
    error = str(result.exception)
    assert "Deleted 1 of 2" in error
    assert "ses_bbb222" in error


def test_archive_command(monkeypatch):
    sessions = {"data": [{"id": "ses_abc111", "title": "Old"}]}
    seen: list[tuple[str, str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            seen.append((request.method, request.url.path, request.content))
            return httpx.Response(204)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["archive", "ses_abc"])

    assert result.exit_code == 0
    assert seen == [("PATCH", "/api/session/ses_abc111", b'{"archived":true}')]
    assert "Archived" in result.stdout


def test_unarchive_command(monkeypatch):
    sessions = {"data": [{"id": "ses_abc111", "title": "Old"}]}
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            seen.append(request.content)
            return httpx.Response(204)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["unarchive", "ses_abc"])

    assert result.exit_code == 0
    assert seen == [b'{"archived":false}']
    assert "Restored" in result.stdout


def test_show_json(monkeypatch):
    session_id = "ses_abc111"
    details = {"data": {"id": session_id, "title": "Demo"}}
    messages = {"data": [{"id": "msg_1", "type": "user", "text": "hi"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/message"):
            return httpx.Response(200, json=messages)
        if request.url.path == "/api/session":
            return httpx.Response(200, json={"data": [{"id": session_id, "title": "Demo"}]})
        return httpx.Response(200, json=details)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["show", "-j", session_id])

    assert result.exit_code == 0
    payload = orjson.loads(result.stdout)
    assert payload["session"]["title"] == "Demo"
    assert payload["messages"][0]["text"] == "hi"


def test_fork_before_option(monkeypatch):
    sessions = {"data": [{"id": "ses_abc111", "title": "Old"}]}
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/fork"):
            seen.append(request.content)
            return httpx.Response(200, json={"data": {"id": "ses_forked"}})
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["fork", "-b", "msg_1", "ses_abc"])

    assert result.exit_code == 0
    assert seen == [b'{"before":"msg_1"}']


def test_ls_uses_single_page_by_default(monkeypatch):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        data = [{"id": f"ses_{i}", "title": f"T{i}"} for i in range(101)]
        return httpx.Response(200, json={"data": data, "cursor": {"next": "more"}})

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["ls"])

    assert result.exit_code == 0
    assert calls == 1
    assert "(+more)" in result.stdout


def test_ls_count_enumerates_all_pages(monkeypatch):
    monkeypatch.setattr(client.api, "PAGE_SIZE", 1)
    calls: list[str | None] = []
    pages = {
        None: {"data": [{"id": "ses_1", "title": "One"}], "cursor": {"next": "c1"}},
        "c1": {"data": [{"id": "ses_2", "title": "Two"}], "cursor": {"next": None}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        calls.append(cursor)
        return httpx.Response(200, json=pages[cursor])

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["ls", "--count", "-n", "1"])

    assert result.exit_code == 0
    assert calls == [None, "c1"]
    assert "(+1 more)" in result.stdout


def test_ls_single_page_reports_exact_total(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [{"id": f"ses_{i}", "title": f"T{i}"} for i in range(5)],
                "cursor": {"next": None},
            },
        )

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["ls", "-n", "2"])

    assert result.exit_code == 0
    assert "(+3 more)" in result.stdout


def test_parse_since_relative():
    value = cli.parse_timestamp("7d")
    assert value < int(dt.datetime.now().timestamp() * 1000)


def test_parse_since_iso():
    assert cli.parse_timestamp("2026-01-01") == int(dt.datetime(2026, 1, 1).timestamp() * 1000)


def test_parse_since_invalid():
    with pytest.raises(client.OpenCodeError, match="Invalid date value"):
        cli.parse_timestamp("nope")


def test_projects_command(monkeypatch):
    payload = [{"id": "p1", "canonical": "/tmp", "time": {"active": 1_700_000_000_000}}]
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json=payload))

    result = runner.invoke(cli.app, ["projects"])

    assert result.exit_code == 0
    assert "p1" in result.stdout
    assert "/tmp" in result.stdout


def test_stats_since_and_project(monkeypatch):
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == client.Route.STATS:
            seen.update(dict(request.url.params))
            return httpx.Response(200, json={"data": {"sessions": 1}})
        if request.url.path == client.Route.PROJECTS:
            return httpx.Response(200, json=[{"id": "p1", "canonical": "/tmp"}])
        return httpx.Response(404, json={"error": "nope"})

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["stats", "--since", "7d", "-p", "p1"])

    assert result.exit_code == 0
    assert seen["project"] == "p1"
    assert int(seen["from"]) > 0


def test_ls_project_filter(monkeypatch):
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == client.Route.PROJECTS:
            return httpx.Response(200, json=[{"id": "p1", "canonical": "/tmp"}])
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"data": [{"id": "ses_1", "title": "One"}]})

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["ls", "-p", "p1"])

    assert result.exit_code == 0
    assert seen["project"] == "p1"


def test_export_all_writes_files(monkeypatch, tmp_path):
    sessions = {"data": [{"id": "ses_1", "title": "One"}], "cursor": {"next": None}}
    transfer = {"data": {"info": {"id": "ses_1", "title": "One"}, "messages": []}}

    def handler(request: httpx.Request) -> httpx.Response:
        if "/export" in request.url.path:
            return httpx.Response(200, json=transfer)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)
    target = tmp_path / "out"

    result = runner.invoke(cli.app, ["export", "--all", "-o", str(target)])

    assert result.exit_code == 0
    assert (target / "ses_1.md").exists()


def test_export_requires_output_for_all(monkeypatch):
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json=[]))

    result = runner.invoke(cli.app, ["export", "--all"])

    assert result.exit_code == 1


def test_resume_tmux(monkeypatch, tmp_path):
    session_id = "ses_e2b0571afffetUGR478SIJcizV"
    payload = {"data": {"id": session_id, "location": {"directory": str(tmp_path)}}}
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json=payload))
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setenv("TMUX", "/tmp/tmux-0,1,0")

    calls: list[list[str]] = []

    class Completed:
        returncode = 0

    monkeypatch.setattr(
        "subprocess.run",
        lambda args, check: calls.append(list(args)) or Completed(),
    )

    result = runner.invoke(cli.app, ["resume", "--tmux", session_id])

    assert result.exit_code == 0
    assert calls == [
        [
            "/usr/bin/tmux",
            "new-window",
            "-c",
            str(tmp_path),
            "--",
            "/usr/bin/opencode",
            "-s",
            session_id,
        ]
    ]


def test_rm_progress_branch(monkeypatch):
    sessions = {"data": [{"id": "ses_aaa111"}, {"id": "ses_bbb222"}]}
    monkeypatch.setattr(type(cli.console), "is_terminal", property(lambda self: True))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["rm", "-y", "ses_aaa", "ses_bbb"])

    assert result.exit_code == 0
    assert "Deleted 2 session(s)" in result.stdout


def test_ls_roots_filter(monkeypatch):
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"data": [{"id": "ses_1", "title": "One"}]})

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["ls", "--roots"])

    assert result.exit_code == 0
    assert seen["parentID"] == "null"


def test_stats_until_param(monkeypatch):
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == client.Route.STATS:
            seen.update(dict(request.url.params))
            return httpx.Response(200, json={"data": {"sessions": 1}})
        return httpx.Response(404, json={"error": "nope"})

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["stats", "--since", "2026-11-01", "--until", "2026-11-07"])

    assert result.exit_code == 0
    assert seen["from"] < seen["to"]


def test_clean_dry_run(monkeypatch):
    sessions = {
        "data": [
            {"id": "ses_empty", "tokens": {"input": 0, "output": 0}, "time": {"idle": 1}},
            {"id": "ses_used", "title": "Keep", "tokens": {"input": 10, "output": 5}},
        ]
    }
    deletes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            deletes.append(request.url.path)
            return httpx.Response(204)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["clean", "--dry-run"])

    assert result.exit_code == 0
    assert deletes == []
    assert "Dry run: 1 empty session(s)" in result.stdout


def test_projects_json(monkeypatch):
    payload = [{"id": "p1", "canonical": "/tmp", "time": {"active": 1_700_000_000_000}}]
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json=payload))

    result = runner.invoke(cli.app, ["projects", "-j"])

    assert result.exit_code == 0
    data = orjson.loads(result.stdout)
    assert data == [{"id": "p1", "canonical": "/tmp", "sessions": None}]


def test_projects_count(monkeypatch):
    projects = [{"id": "p1", "canonical": "/tmp", "time": {"active": 1_700_000_000_000}}]
    sessions = {
        "data": [
            {"id": "ses_1", "projectID": "p1", "time": {"updated": 1_700_000_000_000}},
            {"id": "ses_2", "projectID": "p1", "time": {"updated": 1_700_000_000_000}},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == client.Route.PROJECTS:
            return httpx.Response(200, json=projects)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["projects", "--count"])

    assert result.exit_code == 0
    assert "2" in result.stdout


def test_export_all_since_filters_sessions(monkeypatch, tmp_path):
    sessions = {
        "data": [
            {"id": "ses_old", "title": "Old", "time": {"updated": 1_600_000_000_000}},
            {"id": "ses_new", "title": "New", "time": {"updated": 1_800_000_000_000}},
        ]
    }
    transfer = {"data": {"info": {"id": "ses_new", "title": "New"}, "messages": []}}

    def handler(request: httpx.Request) -> httpx.Response:
        if "/export" in request.url.path:
            return httpx.Response(200, json=transfer)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)
    target = tmp_path / "out"

    result = runner.invoke(cli.app, ["export", "--all", "--since", "30d", "-o", str(target)])

    assert result.exit_code == 0
    assert [p.name for p in target.iterdir()] == ["ses_new.md"]


def test_export_all_progress_branch(monkeypatch, tmp_path):
    sessions = {
        "data": [
            {"id": "ses_1", "title": "One", "time": {"updated": 1_800_000_000_000}},
            {"id": "ses_2", "title": "Two", "time": {"updated": 1_800_000_000_000}},
        ]
    }
    transfer = {"data": {"info": {"id": "ses_1", "title": "One"}, "messages": []}}

    def handler(request: httpx.Request) -> httpx.Response:
        if "/export" in request.url.path:
            return httpx.Response(200, json=transfer)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)
    monkeypatch.setattr(type(cli.console), "is_terminal", property(lambda self: True))
    target = tmp_path / "out"

    result = runner.invoke(cli.app, ["export", "--all", "-o", str(target)])

    assert result.exit_code == 0
    assert sorted(p.name for p in target.iterdir()) == ["ses_1.md", "ses_2.md"]


def test_archive_progress_branch(monkeypatch):
    sessions = {"data": [{"id": "ses_aaa111"}, {"id": "ses_bbb222"}]}
    monkeypatch.setattr(type(cli.console), "is_terminal", property(lambda self: True))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            return httpx.Response(204)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["archive", "ses_aaa", "ses_bbb"])

    assert result.exit_code == 0
    assert "Archived 2 session(s)" in result.stdout


def test_rm_prompt_truncates_many_ids(monkeypatch):
    ids = [f"ses_{i:026d}" for i in range(6)]
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json={"data": []}))

    result = runner.invoke(cli.app, ["rm", *ids], input="n\n")

    assert result.exit_code != 0
    assert "…" in result.stdout


def test_archive_reports_partial_failure(monkeypatch):
    sessions = {"data": [{"id": "ses_aaa111"}, {"id": "ses_bbb222"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            if request.url.path.endswith("ses_bbb222"):
                return httpx.Response(500, json={"error": "boom"})
            return httpx.Response(204)
        return httpx.Response(200, json=sessions)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["archive", "ses_aaa", "ses_bbb"])

    assert result.exit_code == 1
    error = str(result.exception)
    assert "Archived 1 of 2" in error
    assert "ses_bbb222" in error


def test_resume_print_and_tmux_conflict(monkeypatch):
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json={"data": {}}))

    result = runner.invoke(cli.app, ["resume", "-p", "-t", "ses_1"])

    assert result.exit_code == 1
    assert "either --print or --tmux" in str(result.exception)


def test_ls_count_json_shape(monkeypatch):
    data = {"data": [{"id": "ses_1", "title": "One"}, {"id": "ses_2", "title": "Two"}]}
    _patch_service(monkeypatch, lambda request: httpx.Response(200, json=data))

    result = runner.invoke(cli.app, ["ls", "--count", "-j"])

    assert result.exit_code == 0
    payload = orjson.loads(result.stdout)
    assert payload["total"] == 2
    assert payload["has_more"] is False
    assert len(payload["sessions"]) == 2


def test_show_single_message(monkeypatch):
    session_id = "ses_abc111"
    details = {"data": {"id": session_id, "title": "Demo"}}
    messages = {"data": [{"id": "msg_1", "type": "user", "text": "only one"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/message"):
            return httpx.Response(200, json=messages)
        if request.url.path == client.Route.SESSIONS:
            return httpx.Response(200, json={"data": [{"id": session_id}]})
        return httpx.Response(200, json=details)

    _patch_service(monkeypatch, handler)

    result = runner.invoke(cli.app, ["show", "-m", "1", "-j", session_id])

    assert result.exit_code == 0
    payload = orjson.loads(result.stdout)
    assert len(payload["messages"]) == 1
    assert payload["messages"][0]["text"] == "only one"


def test_stats_rejects_reversed_range():
    result = runner.invoke(cli.app, ["stats", "--since", "2026-11-10", "--until", "2026-11-01"])

    assert result.exit_code == 1
    assert "--until must be later than --since" in str(result.exception)
