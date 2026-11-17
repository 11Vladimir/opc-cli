# opc

![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-3776AB?logo=python&logoColor=white)
![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)
![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)

A fast, zero-configuration terminal CLI for inspecting and managing [OpenCode](https://opencode.ai) sessions, rendered with [Rich](https://github.com/Textualize/rich).

Unlike tools that edit OpenCode's SQLite database directly, `opc` uses the
official HTTP API of the running service — safe to use while OpenCode is
running, with no schema coupling and no risk of corrupting `opencode.db`.

---

## Features

- **Zero configuration** — automatically discovers the running OpenCode background service via `~/.local/state/opencode/service.json` (or `$XDG_STATE_HOME/opencode/service.json`) and authenticates with HTTP Basic.
- **Responsive Rich output** — terminal-width-aware tables, compact timestamps, tilde-collapsed paths, and colour-coded message panels.
- **Short ID prefixes** — pass any unique session ID prefix (e.g. `ses_e2b05`) instead of copying full 30-character IDs.
- **Batch deletion** — remove multiple sessions in a single command with upfront prefix resolution and confirmation.
- **Quota awareness** — `opc limits` and `opc stats` show rolling/weekly/monthly usage meters and per-model token breakdowns.
- **Session hygiene** — `opc clean` wipes idle, untitled, zero-token sessions in one step, and `opc resume` jumps straight back into a session in its original directory.
- **Session editing** — `opc rename` fixes unhelpful auto-titles, `opc mv` repoints sessions after a folder rename, `opc fork` branches a conversation, and `opc export` writes Markdown or lossless JSON.
- **Archive workflow** — `opc archive` / `opc unarchive` hide sessions without deleting them; `opc ls -a` shows them with an `a` marker.
- **Project awareness** — `opc projects` maps project IDs to directories, and `ls`/`stats` accept `-p/--project` with an id, id prefix, or path.

## Safe by design

Most third-party OpenCode session managers read and write
`~/.local/share/opencode/opencode.db` directly with raw SQL. That works until
the schema changes, and their READMEs warn users to back up the database before
every run because a write can corrupt live data.

`opc` never touches the database or the on-disk session files. It talks to the
**official OpenCode HTTP API** exposed by the running background service:

```
opc ──HTTP (Basic auth)──▶ OpenCode service ──▶ SQLite
```

Concretely:

- **No direct SQLite access** — no schema coupling, no migration breakage, no
  risk of corrupting the database.
- **Safe while OpenCode is running** — you can list or delete sessions while the
  TUI, Zed, or another client is attached; the service serialises writes and
  every client sees the change immediately.
- **Same permissions as OpenCode** — `opc` authenticates with the ephemeral
  password from `service.json`; it cannot do anything the service itself would
  not allow.
- **Read-only by default** — `ls`, `show`, `stats`, and `limits` only issue
  `GET` requests; destructive commands (`rm`, `clean`) resolve every prefix
  first, show what will be affected, and ask for confirmation.

The only local reads are the service registration file and the `opencode`
binary path used by `opc resume`. Nothing else on disk is modified.

### How it compares

| | `opc` | Tools that edit `opencode.db` directly |
|---|---|---|
| Data access | Official HTTP API of the running service | Raw SQL against the SQLite file |
| While OpenCode is running | Safe | Needs backups; a write can corrupt live data |
| OpenCode upgrades | Unaffected | Break when the internal schema changes |
| Removing sessions | `opc archive` first — restorable | Rows deleted permanently |
| Setup | Zero config (`service.json` auto-discovery) | DB path plus backup discipline |

## Requirements

- **Python 3.14+**
- **[uv](https://docs.astral.sh/uv/)** (recommended for installation and development)
- A running **OpenCode v2** background service (`opencode service status`)

## Installation

Install globally as the `opc` command with `uv`:

```sh
git clone https://github.com/11Vladimir/opc-cli.git
cd opc-cli
uv tool install --editable .
```

Or run directly inside the project without global installation:

```sh
uv sync
uv run opc --help
```

### Uninstall

Remove the global `opc` command and its isolated environment:

```sh
uv tool uninstall opc-cli
```

Verify it is gone:

```sh
which opc        # should print nothing
uv tool list     # opc-cli should no longer be listed
```

Optional clean-up of the package archives left in uv's cache:

```sh
uv cache clean opc-cli
```

What is **not** removed (by design):

- the project checkout itself (`opc-cli/`) and its `.venv` — delete them manually if you want;
- OpenCode data — sessions, config, and `~/.local/state/opencode/service.json` are never touched by `opc`, and uninstalling leaves them intact.

## Quick Start

### List sessions (`opc ls`)

```sh
opc ls                        # list sessions (oldest first by default)
opc ls -o desc -n 10          # 10 newest sessions
opc ls -C .                   # only sessions from the current directory
opc ls -p ~/projects/api      # only sessions of that project (id, prefix, or path)
opc ls -s "refactor" -a       # filter by title, include archived sessions
```

Example output:

```text
 id                title                           agent      updated          tokens   directory
 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
 ses_e2b0571af   * Refactor the auth middleware    build      just now         255.8k   /home/spk/Desktop/pr…
 ses_e2b29fb44     Add CSV export to reports       plan       1h ago            93.9k   /home/spk
 ses_e2b7b72d5     Debug flaky CI tests            mentor     1d ago           510.8k   /home/spk/Desktop/pr…

3 sessions (+24 more)
* running
```

Sessions are read one page at a time: when the result fits in a single page you
get an exact `(+N more)` counter, otherwise the caption shows `(+more)`. Pass
`--count` to walk every page for an exact total (slower on large histories).

### Inspect a session (`opc show`)

```sh
opc show ses_e2b0571a         # show session metadata + last 6 messages
opc show ses_e2b0571a -m 20   # show last 20 messages
```

```text
╭──────────────────── session ─────────────────────╮
│                                                  │
│  id        ses_e2b0571afffetUGR478SIJcizV        │
│  title     Refactor the auth middleware          │
│  agent     build                                 │
│  model     opencode-go/gemini-4-argon (high)     │
│  directory /home/spk/Desktop/project             │
│  updated   2026-11-17 09:36                      │
│  tokens    255.8k total (220.0k in / 35.8k out)  │
│  cost      $0.0000                               │
│                                                  │
╰──────────────────────────────────────────────────╯
```

### View usage statistics (`opc stats`)

```sh
opc stats
```

The output combines three panels: aggregate usage, quota limits, and a per-model breakdown.

```text
╭───────── usage ─────────╮
│ sessions      33        │
│ subagents     14        │
│ prompts       249       │
│ steps         1102      │
│ input tokens  9.9M      │
│ output tokens 447.9k    │
│ tool calls    1480      │
│ tool failures 74        │
│ active days   4         │
│ streak        4         │
│ cost          $0.0000   │
╰─────────────────────────╯

╭────────────────────── limits (Default) ───────────────────────╮
│  rolling    ━━────────────────────   10%   resets in 3h 57m   │
│  weekly     ━━━━━━━━━━━━──────────   56%   resets in 15h 18m  │
│  monthly    ━━━━━━────────────────   28%   resets in 28d 00h  │
╰───────────────────────────────────────────────────────────────╯

 model                         steps     input    output  reasoning  cache read
 ─────────────────────────────────────────────────────────────────────────────
 opencode-go/gemini-4-argon…     217      4.9M    94.5k      55.5k       33.9M
 opencode-go/glm-5.3 (high)      128      1.1M    53.7k      99.0k       14.3M
 ...
```

### Check quota limits only (`opc limits`)

```sh
opc limits
```

Shows the rolling / weekly / monthly metering bars plus any configured USD
budgets, with the workspace console URL at the bottom. Bars turn yellow at 60%
and red at 85% (or when the limit is hit).

### Browse projects (`opc projects`)

```sh
opc projects                 # project ids, paths, and last activity
opc projects --count         # also count sessions per project
opc projects --count --since 30d   # count only recently active sessions
opc projects -j              # machine-readable list
```

Project ids show up in session payloads and can be used with `ls -p` and
`stats -p`.

### Statistics for a range or project (`opc stats`)

```sh
opc stats --since 7d              # last week
opc stats --since 2026-11-01      # since an ISO date
opc stats --since 2026-11-01 --until 2026-11-07   # a closed range
opc stats -p ~/projects/api       # only that project
opc stats --since 30d -p api -j   # JSON for scripting
```

The usage panel title echoes the selected range and project
(`usage · since 30d · project ~/projects/api`), so screenshots are unambiguous.

### Delete empty sessions (`opc clean`)

```sh
opc clean        # preview the empty untitled sessions and confirm
opc clean -y     # delete them without prompting
opc clean --dry-run   # only show what would be deleted
```

A session counts as empty when it is idle, has no title, and has zero tokens —
i.e. the `<untitled>` rows that pile up from accidental OpenCode launches.

### Resume a session (`opc resume`)

```sh
opc resume ses_e2b0571a        # cd into the session directory and launch OpenCode
opc resume --print ses_e2b0571a  # print the shell command instead of running it
opc resume --tmux ses_e2b0571a   # open it in a new tmux window
```

Resolves the prefix, looks up the session's original directory, `cd`s into it,
and replaces the current process with the OpenCode launch (`opencode -s <id>`).
If the directory no longer exists it warns and resumes in the current directory.
Use `--print` (or `-p`) to emit a ready-to-paste command
(`cd <dir> && opencode -s <id>`) for scripts, tmux panes, or another shell.

### Delete sessions (`opc rm`)

```sh
opc rm ses_e2b7f2b72                              # prompts for confirmation
opc rm -y ses_e2d33af4a ses_e2d3634ae ses_e2d37   # delete multiple without prompt
```

All prefixes are resolved in a single API call before anything is deleted, so
a typo in one ID aborts the whole batch. On a terminal, batches of two or more
sessions show an in-place progress bar with an `n/total` counter.

If one delete fails mid-batch, `opc` stops immediately and reports how many
sessions were removed and which ID failed, for example
`Deleted 3 of 12 session(s); failed on ses_abc111: 500 …`.

### Rename, move, and fork (`opc rename` / `opc mv` / `opc fork`)

```sh
opc rename ses_e2b0571a "CLI: session manager"   # fix an unhelpful auto-title
opc mv ses_e2b0571a ~/projects/renamed-repo       # follow a moved/renamed folder
opc fork ses_e2b0571a                             # branch off a new session
opc fork ses_e2b0571a -b msg_1d4fc28              # branch from an earlier message
```

- `rename` updates the session title (`PATCH /api/session/{id}`), useful when
  the auto-generated title no longer matches the conversation.
- `mv` repoints the session to another directory (`POST /api/session/{id}/move`),
  which fixes the "I renamed my project folder and lost my history" problem.
  The destination must exist.
- `fork` creates a new session from the current one and prints its details.
  With `-b/--before <message-id>` it branches from that point in history
  instead of the end.

### Archive sessions (`opc archive` / `opc unarchive`)

```sh
opc archive ses_e2b0571a        # hide from the default listing
opc archive ses_a ses_b         # archive several at once
opc unarchive ses_e2b0571a      # bring it back
opc ls -a                       # show archived too (marked with `a`)
```

Archived sessions are still stored and can be restored at any time; unlike
`opc rm`, nothing is deleted.

### Export a session (`opc export`)

```sh
opc export ses_e2b0571a                    # Markdown to stdout
opc export ses_e2b0571a -o session.md      # Markdown to a file
opc export ses_e2b0571a -j -o session.json # lossless raw JSON
opc export ses_e2b0571a --sanitize         # redact secrets before exporting
opc export --all -o ./exports              # every root session into a directory
opc export --all -C ~/projects/api -o ./api-exports   # only that directory
opc export --all -p api --since 30d -o ./recent-api     # only recent sessions
opc export --all -p api --include-archived -o ./all-api
```

Markdown output starts with a small metadata block and then one `## <role> ·
<time>` section per user/assistant message, with tool calls shown as
`` `-> tool` `` lines. Metadata-only events (agent/model switches, idle markers)
are skipped.

## Command Reference

| Command | Arguments / Options | Description |
|---|---|---|
| `opc ls` | `-C, --dir <path>`<br>`-s, --search <text>`<br>`-p, --project <id\|prefix\|path>`<br>`-n, --limit <int>` (default: `30`)<br>`-o, --order <asc\|desc>` (default: `asc`)<br>`-a, --all`<br>`--roots`<br>`--count`<br>`-j, --json` | List sessions with responsive columns and overflow counter. |
| `opc show` | `<session>`<br>`-m, --messages <int>` (default: `6`)<br>`-j, --json` | Display session metadata and recent messages in chronological order. |
| `opc stats` | `-p, --project <id\|prefix\|path>`<br>`--since <7d\|24h\|2w\|YYYY-MM-DD>`<br>`--until <7d\|24h\|2w\|YYYY-MM-DD>`<br>`-j, --json` | Show aggregate usage, quota limits, and per-model breakdown. |
| `opc limits` | `-j, --json` | Show workspace quota meters and USD budgets. |
| `opc projects` | `--count`<br>`--since <7d\|24h\|YYYY-MM-DD>`<br>`-j, --json` | List registered projects with optional session counts. |
| `opc clean` | `-y, --yes`<br>`--dry-run` | Delete all idle, untitled, zero-token sessions. |
| `opc resume` | `<session>`<br>`-p, --print`<br>`-t, --tmux` | Resume a session inside its original directory. |
| `opc fork` | `<session>`<br>`-b, --before <message-id>` | Fork a session into a new one. |
| `opc archive` | `<sessions>...` | Archive one or more sessions. |
| `opc unarchive` | `<sessions>...` | Restore archived sessions. |
| `opc rename` | `<session>` `<title>` | Update a session title. |
| `opc mv` | `<session>` `<directory>` | Move a session to another directory. |
| `opc export` | `<session>`<br>`--all -o <dir>`<br>`-C, --dir`<br>`-p, --project`<br>`-s, --search`<br>`--since <7d\|24h\|YYYY-MM-DD>`<br>`--include-archived`<br>`-o, --output <file>`<br>`-j, --json`<br>`--sanitize` | Export a session as Markdown or raw JSON. |
| `opc rm` | `<sessions>...`<br>`-y, --yes` | Permanently delete one or more sessions by ID or unique prefix. |

Global options:

| Option | Description |
|---|---|
| `-h, --help` | Show help for the command and exit. |
| `-V, --version` | Print the `opc` version and exit. |

## Machine-readable output

`ls`, `stats`, and `limits` accept `-j / --json` and print raw JSON to stdout
instead of Rich tables, so output can be piped into `jq` or scripts:

```sh
opc ls -j | jq '.sessions[].title'
opc limits -j | jq '.go.monthly.percent'
opc stats -j | jq '.stats.models | length'
```

Each command emits a stable shape:

| Command | JSON shape |
|---|---|
| `opc ls -j` | `{"total": <int \| null>, "has_more": <bool>, "sessions": [<session>...]}` |
| `opc show -j` | `{"session": {...}, "messages": [...]}` |
| `opc limits -j` | `{"workspace": {...}, "go": {...}, "budgets": [...]}` |
| `opc projects -j` | `[{"id": ..., "canonical": ..., "sessions": <int\|null>}...]` |
| `opc stats -j` | `{"stats": {...}, "limits": {...} \| null}` |

JSON is written with `orjson` and no ANSI escapes, so it is safe to redirect
(`opc ls -j > sessions.json`).

## Table Legend

`opc ls` prints a dim legend line under the table, listing only the markers that
actually appear in the current output:

| Marker | Meaning |
|---|---|
| `*` (green) | Session is currently running (busy). |
| `↳` (dim) | The row is a subagent (child) session. |
| `a` (dim) | The session is archived (only visible with `-a/--all`). |
| dim title | Subagent or untitled session. |
| yellow token count | Session used ≥ 1M tokens. |
| dim `0` | Session has no tokens (likely empty). |
| green directory | Session belongs to the current working directory. |
| `+N more` | Remaining sessions beyond `--limit` (exact when the page fits). |
| `+more` | More sessions exist beyond the fetched page; use `--count` for an exact number. |

## Environment Variables

| Variable | Description |
|---|---|
| `OPC_SERVICE_FILE` | Explicit path to OpenCode's `service.json` registration file (overrides XDG discovery). |
| `XDG_STATE_HOME` | Base directory for state files; defaults to `~/.local/state`. |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `OpenCode is not running: … does not exist` | The background service has not started. Run `opencode service status` (or just start OpenCode once); `opc` never starts the service itself. |
| `401 Unauthorized` | The service restarted and rotated the password in `service.json`. Re-run the command; `GET` requests already retry a few times. |
| `Cannot reach the OpenCode service` after a restart | Same as above — retry once the service is healthy (`opc ls`). |
| `opencode` binary was not found on PATH | `opc resume` shells out to `opencode`. Install it or use `opc resume --print` to get the raw command. |
| `tmux` binary was not found / tmux exits non-zero | `opc resume --tmux` needs tmux. Drop the flag, or start tmux first (`tmux new-session`). |
| Empty or wrong session directory in `opc resume` | The folder was moved or deleted. `opc` warns and resumes in the current directory; use `opc mv <session> <dir>` to repoint it. |
| `(+more)` instead of `(+N more)` | `opc ls` fetches one page by default. Add `--count` for an exact total. |
| `--since` rejects a value | Accepted forms are `30m`, `24h`, `7d`, `2w`, or an ISO date such as `2026-11-01`. |
| `opc` works in one terminal but not another | The global install lives in `~/.local/bin`; make sure it is on `PATH`, or run `uv run opc` inside the project. |
| Need to point `opc` at a non-standard service | Set `OPC_SERVICE_FILE=/path/to/service.json` and/or `XDG_STATE_HOME`. |

## Project Structure

```text
opc-cli/
├── pyproject.toml
├── src/opc_cli/
│   ├── __init__.py
│   ├── __main__.py       # `python -m opc_cli` entry point
│   ├── app.py            # Typer app and shared Rich console
│   ├── helpers.py        # JSON output, date parsing, bulk progress
│   ├── cli.py            # Entry point: --version, command imports, error handling
│   ├── commands/
│   │   ├── sessions.py   # ls, show, rm, clean, resume, fork, archive, rename, mv
│   │   ├── stats.py      # stats, limits, projects
│   │   └── export.py     # export (single session and --all)
│   ├── client/
│   │   ├── api.py        # OpenCodeClient: transport + domain methods
│   │   ├── config.py     # service discovery and Endpoint
│   │   ├── constants.py  # timeouts, page size, retry policy
│   │   ├── errors.py     # OpenCodeError / HttpStatusError
│   │   └── routes.py     # Route and SortOrder enums
│   └── render/
│       ├── common.py     # formatting primitives and table styling
│       ├── sessions.py   # session/project tables and panels
│       ├── stats.py      # usage, limits, and per-model tables
│       └── messages.py   # message panels and Markdown transcripts
└── tests/
    ├── test_cli.py
    ├── test_client.py
    └── test_render.py
```

## Build backend

Packaging uses [`uv_build`](https://docs.astral.sh/uv/concepts/build-backend/),
so `uv build` and `uv tool install` work without extra dependencies:

```toml
[build-system]
requires = ["uv_build>=0.13.7,<0.14"]
build-backend = "uv_build"
```

## Contributing

Contributions are welcome — bug reports, documentation fixes, and new commands.
The project is intentionally small, so the bar is "keep it simple and keep it
green".

### Setup

```sh
git clone <your-repo-url>
cd opc-cli
uv sync
uv run opc --help
```

`uv sync` creates `.venv`, installs the package in editable mode, and registers
the `opc` entry point inside the environment.

### Checks before a pull request

```sh
uv run ruff check           # lint
uv run ruff format --check  # formatting
uv run pytest               # test suite
uvx ty check                # optional static types (Astral ty)
```

All four are expected to pass. CI runs on pull requests targeting `main` only
(direct pushes do not trigger it), plus `uv build` and a smoke test that runs
`opc --version` from the built wheel.

Two cost-saving rules:

- pull requests touching only Markdown/docs skip the heavy job, while the
  required **CI gate** check still reports green;
- draft pull requests are skipped until they are marked ready for review.

### Releasing

PyPI publishing is intentionally deferred; releases are GitHub tags.

```sh
# 1. bump the version in pyproject.toml only (opc reads it from package metadata)
# 2. merge that change to main through a pull request
# 3. tag the commit on main and push the tag
git tag -a v0.2.0 -m "v0.2.0"        # or: git tag -s v0.2.0 -m "v0.2.0"
git push origin v0.2.0
```

Pushing the tag starts `.github/workflows/release.yml`, which:

- fails if the tag (`v0.2.0`) does not match `pyproject.toml` (`0.2.0`);
- runs `ruff` and the test suite;
- builds the sdist and wheel and smoke-tests the wheel;
- creates the GitHub release with generated notes and both artifacts attached.

Manual fallback, if the workflow is unavailable:

```sh
uv build
uvx --from "$(ls dist/*.whl | head -n 1)" opc --version
gh release create v0.2.0 dist/* --title v0.2.0 --generate-notes
```

When PyPI is enabled later, the release workflow only needs an extra
`uv publish` step (the hook is already commented in `release.yml`).

### Architecture rules

| Layer | Rule |
|---|---|
| `client/` | The only place that talks HTTP. Endpoints live in `routes.py`, filters in `_session_params`, transport in `api.py`. Never touch OpenCode's SQLite database or session files. |
| `render/` | Pure functions: take dicts, return Rich renderables (`Table`, `Panel`, `Group`, `Text`). No `Console()` and no printing inside these modules. |
| `app.py` / `helpers.py` | The Typer app and console live in `app.py`; shared helpers (JSON output, date parsing, bulk progress) live in `helpers.py`. |
| `commands/*.py` | One Typer command per function, grouped by area (`sessions`, `stats`, `export`). They register on import. |

Two conventions worth remembering:

- **English only** in code, comments, help texts, and CLI output;
- **prefix-first session ids** — every command that takes a session resolves it
  through `resolve_session`/`resolve_sessions`, so short prefixes keep working.

### Adding a command

1. Add the route to `Route` in `client/routes.py` (with a `@classmethod` if it
   takes a session id).
2. Add a domain method to `OpenCodeClient` in `client/api.py` that calls
   `_json(...)` or `_request(...)`.
3. Add a Typer command to the matching module in `commands/` — resolve the
   session, call the method, and print through `render/`.
4. Cover it with two tests: a client test using `httpx.MockTransport`, and a CLI
   test using the `_patch_service` helper in `tests/test_cli.py`.

### Tests

- No network and no real OpenCode instance: HTTP is mocked with
  `httpx.MockTransport`, paths and environment with `tmp_path`/`monkeypatch`.
- The suite should stay under a second; if a test needs sleep or a retry loop,
  it is testing the wrong layer.
- Use `pytest.raises(..., match=...)` so failures stay readable.

### Style

`ruff` configuration lives in `pyproject.toml` (`line-length = 100`,
`target-version = "py314"`). Run `uv run ruff format` before committing; do not
add `# noqa` without a short comment explaining why.

## License

Released under the [MIT License](LICENSE).
