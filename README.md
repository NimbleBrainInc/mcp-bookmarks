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

## Deploy

The server is a container that needs one writable directory for its SQLite file.

```bash
make docker-build
make docker-run          # http://127.0.0.1:8000/mcp, data in the mcp-bookmarks-data volume
```

The documented host is [Fly.io](https://fly.io); `fly.toml` is in the repo. Once with a Fly
account:

```bash
fly launch --no-deploy --copy-config --name <your-app-name>
fly volumes create bookmarks_data --size 1 --region sjc
fly deploy
curl https://<your-app-name>.fly.dev/health
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

## The lessons

Each row is one merged pull request. Read them in order.

| # | Lesson | PR |
|---|---|---|
| 1 | The server holds nothing between requests. Cross-call state is an explicit handle in the arguments, never a session. | [#1](https://github.com/NimbleBrainInc/mcp-bookmarks/pull/1) |

The tutorial that walks through building this from an empty directory is on the
[NimbleBrain blog](https://nimblebrain.ai/blog/).

## Layout

```
src/mcp_bookmarks/
  server.py   the FastMCP server: tools, health route, ASGI app
  store.py    SQLite: every durable fact lives here, never in the process
  models.py   wire shapes; FastMCP derives each tool's output schema from them
  ids.py      handles: bm_ + 128 random bits
tests/
  test_tools.py       each tool, through fastmcp.Client
  test_stateless.py   handles cross connections; no era gets a session
```

## License

MIT.
