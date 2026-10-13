# mcp-bookmarks: agent guide

A teaching repo. Each pull request is one lesson about writing a remote MCP server on the
2026-07-28 protocol, and the README's lesson table links them in order. Keep that shape:
one lesson per PR, the rule stated in the PR body, a test that fails without it.

## Working here

- `make check` is CI: `ruff format --check`, `ruff check`, `ty check`, `pytest`. Run it
  before pushing.
- Python 3.13+, `uv` for everything (`uv sync`, `uv run`, `uv add`). `fastmcp>=4.1,<5` on
  `mcp>=2,<3`; SDK v2 models are snake_case in Python (`is_error`, `read_only_hint`).
- Tests go through `fastmcp.Client`, never by calling a tool function. The in-memory client
  (`Client(mcp)`) covers tool behaviour; the `live_server` fixture runs the real ASGI app
  under uvicorn for anything about HTTP itself.

## The rules the lessons encode

1. **Nothing lives in the process between requests.** Durable state goes in the store;
   state a client needs back goes in a result as a handle the client passes to the next
   call. No `ctx.set_state`, no module-level dicts keyed by caller, no `Mcp-Session-Id`.
   `stateless_http=True` stays on so the 2025-era handshake mints no session either.
2. **Every tool is annotated.** `@mcp.tool(annotations=...)` with one of `READS`, `ADDS`, or
   `CHANGES` from `annotations.py`, and the tool's row in `tests/test_annotations.py::EXPECTED`. The spec's
   defaults make an unannotated tool a destructive, non-idempotent, open-world write, so a
   missing hint is the most dangerous claim a tool can make, not a blank. A host reads a hint
   to be more careful, never to relax a check; the hints are what the server says about
   itself.
