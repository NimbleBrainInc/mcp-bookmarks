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
2. **Every tool is annotated.** `@mcp.tool(annotations=READS | ADDS | CHANGES)` from
   `annotations.py`, and the tool's row in `tests/test_annotations.py::EXPECTED`. The spec's
   defaults make an unannotated tool a destructive, non-idempotent, open-world write, so a
   missing hint is the most dangerous claim a tool can make, not a blank. A host reads a hint
   to be more careful, never to relax a check; the hints are what the server says about
   itself.
3. **A refusal is a result, returned.** `return not_found(...)` / `refuse(code, message,
   next_step)` from `errors.py`: `isError: true`, the envelope in `structuredContent` and as
   the text block. Never `raise ToolError` for a refusal (it drops `structuredContent`), and
   never a JSON-RPC error (that channel is for a request the server could not take). A tool
   whose return type is `Model | ToolResult` declares `output_schema=schema(Model)`, or the
   derived schema disappears; `schema()` is the union of the model and `ERROR_SCHEMA`,
   because the spec holds every `structuredContent` to the declared schema, error results
   included, and the Inspector enforces it (the SDK clients skip validation on `isError`).
   `mask_error_details=True` stays on.
4. **Tokens are bound to this server's URL; a handle is a name.** `JWTVerifier(audience=
   settings.resource_url)` where `resource_url` is `BOOKMARKS_PUBLIC_URL + /mcp`, built from
   configuration and never from a request header. `RemoteAuthProvider` publishes the
   protected-resource metadata and the 401 challenge. The owner is the token's `sub`, and a
   token without one is refused at the door (`SubjectRequired`). The store takes `owner` on every
   read and write, and `find()` answers another owner's handle exactly as it answers an
   unknown one: there is no existence oracle. Token failures stay 401; the shared refusal
   is only for a caller the server already knows. Never add an `owner` argument to a tool.
5. **Both eras, one surface, proven.** The `client` fixture runs every tool test on
   2026-07-28 and on the 2025 handshake era; `test_eras.py` compares the two surfaces and
   crosses a handle between them. Nothing may depend on which era a caller speaks, and no
   test may pin `mode="legacy"` to make itself pass. A break that shows on one era only is a
   bug on that era, not a reason to narrow the suite.
6. **A list pages by key.** A list tool that can return more than one page takes `cursor`
   and returns `next_cursor` (null on the last page) and a `next_step` that says to call
   again with it and the same filters. The store owns the order, the strictly-after
   predicate, and the cursor's contents (`paging.py`); a tool passes the cursor through. A
   cursor that does not decode, or comes from another listing, is `bad_input` with "call
   again without cursor". Never `OFFSET`: a row removed between pages shifts every later one.
