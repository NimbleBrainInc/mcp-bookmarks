# mcp-bookmarks

A bookmarks server that shows how to build a remote [MCP](https://modelcontextprotocol.io)
server on the **2026-07-28** revision of the protocol: Python, [FastMCP 4](https://gofastmcp.com)
on the MCP Python SDK v2, Streamable HTTP, no sessions. Each lesson landed as its own pull
request, so the history reads as the tutorial.

Six tools: `add_bookmark`, `get_bookmark`, `list_bookmarks`, `update_bookmark`,
`archive_bookmark`, `delete_bookmark`. `add_bookmark` returns a `bookmark_id`; every other
tool takes it. That handle is the only thing a client carries between calls.

## Run it

Needs Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/NimbleBrainInc/mcp-bookmarks.git
cd mcp-bookmarks
make install
make run
```

The server listens on `http://127.0.0.1:8000/mcp`. In another terminal, list its tools the
way a client sees them:

```bash
npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --transport http --method tools/list
```

Save a bookmark and read it back with the handle you get:

```bash
npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --transport http \
  --method tools/call --tool-name add_bookmark \
  --tool-arg url=https://modelcontextprotocol.io/specification/2026-07-28/changelog \
  --tool-arg title="MCP 2026-07-28 changelog"
# → structuredContent.bookmark_id: "bm_…"

npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --transport http \
  --method tools/call --tool-name get_bookmark --tool-arg bookmark_id=bm_…
```

Run the checks CI runs:

```bash
make check     # ruff format, ruff check, ty, pytest
```

## Authentication

The server is an OAuth protected resource. It publishes its metadata at
`/.well-known/oauth-protected-resource/mcp`, answers a call without a token with `401` and a
`WWW-Authenticate` header that points there, and accepts a token only when its `aud` claim
names the server's own URL, `BOOKMARKS_PUBLIC_URL` + `/mcp`, exactly. Every bookmark
belongs to the token's subject; another owner's handle is answered as not found.

`make run` skips all of this for local development (every caller is `anonymous`). To run
with authentication on your laptop, mint a development token and start the server trusting
its key:

```bash
make token SUB=alice       # writes .dev-keys/, prints a token
make run-auth
npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --transport http \
  --header "Authorization: Bearer <token>" --method tools/list
```

In production, point `BOOKMARKS_ISSUER` and `BOOKMARKS_JWKS_URI` at your identity provider
and have it mint tokens with `aud` set to your server's URL (RFC 8707 `resource`).

## Deploy

The server is a container that needs one writable directory for its SQLite file.

```bash
make docker-build
make docker-run          # http://127.0.0.1:8000/mcp, data in the mcp-bookmarks-data volume
```

The container refuses to start without authentication settings; `make docker-run` passes
the development key from `make token`.

The documented host is [Fly.io](https://fly.io); `fly.toml` is in the repo. Once with a Fly
account:

```bash
fly launch --no-deploy --copy-config --name <your-app-name>
fly volumes create bookmarks_data --size 1 --region sjc
# edit [env] in fly.toml: BOOKMARKS_PUBLIC_URL, BOOKMARKS_ISSUER, BOOKMARKS_JWKS_URI
fly deploy
curl https://<your-app-name>.fly.dev/health
curl https://<your-app-name>.fly.dev/.well-known/oauth-protected-resource/mcp
```

Then point any MCP client at `https://<your-app-name>.fly.dev/mcp`. Any host that runs a
container with a volume works the same way; only the three commands differ.

SQLite keeps this repo dependency-free, and it pins the data to one machine. The server
itself holds nothing between requests, so moving the store to a database with its own
address is the whole change needed to run more than one replica.

## Configuration

| Variable | Default | What it does |
|---|---|---|
| `BOOKMARKS_DB` | `bookmarks.db` | Path of the SQLite file. The image sets `/data/bookmarks.db`. |
| `BOOKMARKS_HOST` | `127.0.0.1` | Bind address for `python -m mcp_bookmarks.server`. |
| `BOOKMARKS_PORT` | `8000` | Port for the same. |
| `BOOKMARKS_PUBLIC_URL` | unset | Where clients reach the server, scheme and host. Tokens must carry `aud` = this + `/mcp`. |
| `BOOKMARKS_ISSUER` | unset | The authorization server, as it prints its `iss` claim. Setting it turns authentication on. |
| `BOOKMARKS_JWKS_URI` | unset | Where the issuer publishes its signing keys. |
| `BOOKMARKS_PUBLIC_KEY_FILE` | unset | A PEM public key instead of a JWKS, for development. |
| `BOOKMARKS_ALLOW_ANONYMOUS` | `false` | Run with no authentication. Local development only. |

## The lessons

Each row is one merged pull request. Read them in order.

| # | Lesson | PR |
|---|---|---|
| 1 | The server holds nothing between requests. Cross-call state is an explicit handle in the arguments, never a session. | [#1](https://github.com/NimbleBrainInc/mcp-bookmarks/pull/1) |
| 2 | Every tool is annotated. Under the spec's defaults an unannotated tool is a destructive write, so a missing hint is a claim, not a blank. | [#2](https://github.com/NimbleBrainInc/mcp-bookmarks/pull/2) |
| 3 | A tool's own failure is a result with `isError: true` and a structured body, not a protocol error. It is returned, not raised (`ToolError` drops `structuredContent`), and the declared `outputSchema` admits the error shape, because the spec binds error results to it and the Inspector checks. | [#3](https://github.com/NimbleBrainInc/mcp-bookmarks/pull/3) |
| 4 | The server publishes its protected-resource metadata, accepts only tokens whose `aud` is its own URL, and answers another owner's handle exactly like an unknown one. | [#4](https://github.com/NimbleBrainInc/mcp-bookmarks/pull/4) |
| 5 | Every test runs on both protocol eras, 2026-07-28 and the 2025 handshake, so a behaviour that differs between them fails in CI instead of in a client you do not run. | [#5](https://github.com/NimbleBrainInc/mcp-bookmarks/pull/5) |

The tutorial that walks through building this from an empty directory is on the
[NimbleBrain blog](https://nimblebrain.ai/blog/).

## Layout

```
src/mcp_bookmarks/
  server.py       the FastMCP server: tools, health route, ASGI app
  store.py        SQLite: every durable fact lives here, never in the process
  models.py       wire shapes; each tool's output schema is built from them
  ids.py          handles: bm_ + 128 random bits
  annotations.py  READS, ADDS, CHANGES: what a tool says it does to the world
  errors.py       refusals: isError results with a code, a message, and a next step
  config.py       settings from the environment; the server's URL is configuration
  auth.py         JWT verification bound to that URL; who the current call acts as
tests/
  test_tools.py       each tool, through fastmcp.Client, once per protocol era (so are
                      test_annotations.py and test_errors.py: every test on the client fixture)
  test_stateless.py   handles cross connections; no era gets a session
  test_health.py      /health answers for the store, not the process
  test_annotations.py every tool is in the table, and the wire matches it
  test_errors.py      refusals are results; why they are returned, not raised
  test_auth.py        metadata, 401 challenge, audience binding, no existence oracle, on both eras
  test_eras.py        the two eras advertise one surface; a handle crosses between them
scripts/
  dev_token.py        a stand-in authorization server for your laptop
```

## License

MIT.
