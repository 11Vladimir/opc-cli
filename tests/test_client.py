from pathlib import Path

import httpx
import pytest

from opc_cli import client


def test_service_file_override(monkeypatch):
    monkeypatch.setenv("OPC_SERVICE_FILE", "~/svc.json")
    assert client.service_file() == Path("~/svc.json").expanduser()


def test_service_file_xdg_state_home(monkeypatch):
    monkeypatch.delenv("OPC_SERVICE_FILE", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", "/state")
    assert client.service_file() == Path("/state/opencode/service.json")


def test_service_file_home_fallback(monkeypatch):
    monkeypatch.delenv("OPC_SERVICE_FILE", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: Path("/home/u"))
    assert client.service_file() == Path("/home/u/.local/state/opencode/service.json")


def test_endpoint_from_file_ok(tmp_path):
    path = tmp_path / "service.json"
    path.write_text('{"url": "http://127.0.0.1:4096", "password": "secret"}')
    ep = client.Endpoint.from_file(path)
    assert ep == client.Endpoint(url="http://127.0.0.1:4096", password="secret")


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "[]",
        '{"url": "http://127.0.0.1:4096"}',
        '{"url": "http://127.0.0.1:4096", "password": null}',
    ],
)
def test_endpoint_from_file_invalid(tmp_path, payload):
    path = tmp_path / "service.json"
    path.write_text(payload)
    with pytest.raises(client.OpenCodeError):
        client.Endpoint.from_file(path)


def test_connect_missing_service_file(monkeypatch):
    monkeypatch.setenv("OPC_SERVICE_FILE", "/definitely/missing.json")
    with pytest.raises(client.OpenCodeError):
        client.OpenCodeClient.connect()


def _service(handler) -> client.OpenCodeClient:
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")
    return client.OpenCodeClient(http)


def test_request_ok():
    seen_orders: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_orders.append(request.url.params.get("order"))
        return httpx.Response(200, json={"data": []})

    with _service(handler) as service:
        assert service.list_sessions() == []
        assert service.list_sessions(order=client.SortOrder.DESC) == []

    assert seen_orders == ["asc", "desc"]


def test_request_http_error():
    with (
        _service(lambda request: httpx.Response(404, json={"error": "nope"})) as service,
        pytest.raises(client.OpenCodeError, match="nope"),
    ):
        service.get_session("ses_missing")


def test_request_empty_response():
    with _service(lambda request: httpx.Response(204)) as service:
        assert service._request("DELETE", client.Route.session("ses_1")) is None


def test_request_invalid_json():
    with (
        _service(lambda request: httpx.Response(200, content=b"not-json")) as service,
        pytest.raises(client.OpenCodeError, match="Invalid JSON"),
    ):
        service.list_sessions()


def test_get_messages_reverses_order():
    payload = {"data": [{"id": "msg_2", "type": "assistant"}, {"id": "msg_1", "type": "user"}]}
    with _service(lambda request: httpx.Response(200, json=payload)) as service:
        messages = service.get_messages("ses_1", limit=2)
    assert [m["id"] for m in messages] == ["msg_1", "msg_2"]


def test_get_stats():
    payload = {"data": {"sessions": 5, "prompts": 10}}
    with _service(lambda request: httpx.Response(200, json=payload)) as service:
        assert service.get_stats() == {"sessions": 5, "prompts": 10}


def test_get_limits():
    payload = {"data": {"workspace": {"name": "Default"}, "go": {}, "budgets": []}}
    with _service(lambda request: httpx.Response(200, json=payload)) as service:
        assert service.get_limits()["workspace"]["name"] == "Default"


def test_resolve_session_prefix():
    data = {"data": [{"id": "ses_abc111"}, {"id": "ses_xyz222"}]}
    with _service(lambda request: httpx.Response(200, json=data)) as service:
        assert service.resolve_session("ses_abc") == "ses_abc111"


def test_resolve_session_accepts_28_char_prefix():
    full = "ses_e2b0571afffetUGR478SIJcizV"
    data = {"data": [{"id": full}]}
    with _service(lambda request: httpx.Response(200, json=data)) as service:
        assert service.resolve_session(full[:28]) == full


def test_resolve_session_full_id_skips_listing():
    full = "ses_e2b0571afffetUGR478SIJcizV"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"data": []})

    with _service(handler) as service:
        assert service.resolve_session(full) == full
    assert calls == []


def test_resolve_sessions_fetches_once():
    calls = 0
    data = {"data": [{"id": "ses_abc111"}, {"id": "ses_xyz222"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=data)

    with _service(handler) as service:
        result = service.resolve_sessions(["ses_abc", "ses_xyz", "ses_abc111"])

    assert result == ["ses_abc111", "ses_xyz222"]
    assert calls == 1


def test_resolve_session_ambiguous():
    data = {"data": [{"id": "ses_abc111"}, {"id": "ses_abc222"}]}
    with (
        _service(lambda request: httpx.Response(200, json=data)) as service,
        pytest.raises(client.OpenCodeError, match="ambiguous"),
    ):
        service.resolve_session("ses_abc")


def test_resolve_session_not_found():
    data = {"data": [{"id": "ses_abc111"}]}
    with (
        _service(lambda request: httpx.Response(200, json=data)) as service,
        pytest.raises(client.OpenCodeError, match="No session id"),
    ):
        service.resolve_session("ses_zzz")


def test_delete_session():
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(204)

    with _service(handler) as service:
        service.delete_session("ses_1")
    assert seen == [("DELETE", "/api/session/ses_1")]


def test_list_empty_sessions():
    data = {
        "data": [
            {"id": "ses_empty", "tokens": {"input": 0, "output": 0}, "time": {"idle": 1}},
            {"id": "ses_busy", "tokens": {"input": 0, "output": 0}, "time": {"busy": 1}},
            {"id": "ses_titled", "title": "Hi", "tokens": {"input": 0, "output": 0}},
            {"id": "ses_used", "tokens": {"input": 10, "output": 5}},
        ]
    }
    with _service(lambda request: httpx.Response(200, json=data)) as service:
        empty = service.list_empty_sessions()
    assert [s["id"] for s in empty] == ["ses_empty"]


def test_rename_session():
    seen: list[tuple[str, str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        return httpx.Response(204)

    with _service(handler) as service:
        service.rename_session("ses_1", "New title")
    assert seen == [("PATCH", "/api/session/ses_1", b'{"title":"New title"}')]


def test_move_session(tmp_path):
    seen: list[tuple[str, str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        return httpx.Response(204)

    with _service(handler) as service:
        service.move_session("ses_1", tmp_path)
    assert seen == [("POST", "/api/session/ses_1/move", f'{{"directory":"{tmp_path}"}}'.encode())]


def test_fork_session():
    seen: list[tuple[str, str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        return httpx.Response(200, json={"data": {"id": "ses_forked"}})

    with _service(handler) as service:
        assert service.fork_session("ses_1") == {"id": "ses_forked"}
    assert seen == [("POST", "/api/session/ses_1/fork", b"{}")]


def test_fork_session_before_message():
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content)
        return httpx.Response(200, json={"data": {"id": "ses_forked"}})

    with _service(handler) as service:
        service.fork_session("ses_1", before="msg_1")
    assert seen == [b'{"before":"msg_1"}']


def test_set_archived():
    seen: list[tuple[str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.content))
        return httpx.Response(204)

    with _service(handler) as service:
        service.set_archived("ses_1", archived=True)
        service.set_archived("ses_1", archived=False)

    assert seen == [("PATCH", b'{"archived":true}'), ("PATCH", b'{"archived":false}')]


def test_export_session():
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.url.params.get("sanitize")))
        return httpx.Response(200, json={"data": {"info": {"id": "ses_1"}, "messages": []}})

    with _service(handler) as service:
        transfer = service.export_session("ses_1", sanitize=True)

    assert transfer["info"]["id"] == "ses_1"
    assert seen == [("/api/experimental/session/ses_1/export", "true")]


def test_list_all_sessions_paginates(monkeypatch):
    monkeypatch.setattr(client.api, "PAGE_SIZE", 1)
    calls: list[str | None] = []
    pages = {
        None: {"data": [{"id": "ses_1"}], "cursor": {"next": "c1"}},
        "c1": {"data": [{"id": "ses_2"}], "cursor": {"next": "c2"}},
        "c2": {"data": [{"id": "ses_3"}], "cursor": {"next": None}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        calls.append(cursor)
        return httpx.Response(200, json=pages[cursor])

    with _service(handler) as service:
        sessions = service.list_all_sessions()

    assert [s["id"] for s in sessions] == ["ses_1", "ses_2", "ses_3"]
    assert calls == [None, "c1", "c2"]


def test_list_all_sessions_stops_on_repeated_cursor(monkeypatch):
    monkeypatch.setattr(client.api, "PAGE_SIZE", 1)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": [{"id": "ses_1"}], "cursor": {"next": "same"}})

    with _service(handler) as service:
        service.list_all_sessions()

    assert calls == 2


def test_list_all_sessions_respects_cap():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"id": "ses_1"}, {"id": "ses_2"}], "cursor": {"next": "more"}},
        )

    with _service(handler) as service:
        sessions = service.list_all_sessions(max_sessions=2)

    assert len(sessions) == 2


def test_list_sessions_page_reports_more():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"id": "ses_1"}, {"id": "ses_2"}], "cursor": {"next": "abc"}},
        )

    with _service(handler) as service:
        page, has_more = service.list_sessions_page(limit=1)

    assert [s["id"] for s in page] == ["ses_1"]
    assert has_more is True


def test_list_sessions_page_reports_end():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "ses_1"}], "cursor": {"next": "abc"}})

    with _service(handler) as service:
        page, has_more = service.list_sessions_page()

    assert [s["id"] for s in page] == ["ses_1"]
    assert has_more is False


def test_get_projects():
    payload = [{"id": "p1", "canonical": "/tmp"}]
    with _service(lambda request: httpx.Response(200, json=payload)) as service:
        assert service.get_projects() == payload


def test_resolve_project_by_id_prefix_and_path(tmp_path):
    payload = [{"id": "p123", "canonical": str(tmp_path)}]
    with _service(lambda request: httpx.Response(200, json=payload)) as service:
        assert service.resolve_project("p1") == "p123"
        assert service.resolve_project(str(tmp_path)) == "p123"


def test_resolve_project_missing():
    payload = [{"id": "p1", "canonical": "/tmp"}]
    with (
        _service(lambda request: httpx.Response(200, json=payload)) as service,
        pytest.raises(client.OpenCodeError, match="No project"),
    ):
        service.resolve_project("zzz")


def test_get_stats_params():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"data": {}})

    with _service(handler) as service:
        service.get_stats(since=100, until=200, project="p1")

    assert seen == {"from": "100", "to": "200", "project": "p1"}


def test_http_status_error_carries_status():
    with (
        _service(lambda request: httpx.Response(404, json={"error": "x"})) as service,
        pytest.raises(client.HttpStatusError) as info,
    ):
        service.get_session("ses_1")

    assert info.value.status_code == 404


def test_get_retries_connect_errors(monkeypatch):
    monkeypatch.setattr(client.api, "RETRY_DELAY", 0.0)
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"data": []})

    with _service(handler) as service:
        assert service.list_sessions() == []

    assert attempts["count"] == 3


def test_non_get_is_not_retried(monkeypatch):
    monkeypatch.setattr(client.api, "RETRY_DELAY", 0.0)
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        raise httpx.ConnectError("boom", request=request)

    with (
        _service(handler) as service,
        pytest.raises(client.OpenCodeError),
    ):
        service.delete_session("ses_1")

    assert attempts["count"] == 1


def test_get_retries_read_errors(monkeypatch):
    monkeypatch.setattr(client.api, "RETRY_DELAY", 0.0)
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ReadError("reset", request=request)
        return httpx.Response(200, json={"data": []})

    with _service(handler) as service:
        assert service.list_sessions() == []

    assert attempts["count"] == 2


def test_error_detail_reads_nested_errors():
    payload = {"errors": [{"message": "first failure"}]}
    with (
        _service(lambda request: httpx.Response(400, json=payload)) as service,
        pytest.raises(client.HttpStatusError, match="first failure"),
    ):
        service.get_session("ses_1")
