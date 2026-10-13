.PHONY: help install format format-check lint typecheck test check run run-auth token docker-build docker-run

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Install the package and dev tools into .venv
	uv sync --dev

format: ## Format with ruff
	uv run ruff format src/ tests/

format-check: ## Check formatting
	uv run ruff format --check src/ tests/

lint: ## Lint with ruff
	uv run ruff check src/ tests/

typecheck: ## Type check with ty
	uv run ty check src/

test: ## Run the tests
	uv run pytest -q

check: format-check lint typecheck test ## Everything CI runs

run: ## Serve on http://127.0.0.1:8000/mcp with no authentication (every caller is "anonymous")
	BOOKMARKS_ALLOW_ANONYMOUS=true uv run python -m mcp_bookmarks.server

token: ## Mint a development token (SUB=alice) and create .dev-keys/ if needed
	uv run python scripts/dev_token.py --sub $(or $(SUB),alice)

run-auth: ## Serve with authentication, trusting the development key in .dev-keys/
	@test -f .dev-keys/public.pem || (echo "run 'make token' first" && exit 1)
	BOOKMARKS_PUBLIC_URL=http://127.0.0.1:8000 BOOKMARKS_ISSUER=https://dev-issuer.invalid \
	BOOKMARKS_PUBLIC_KEY_FILE=.dev-keys/public.pem uv run python -m mcp_bookmarks.server

docker-build: ## Build the container image
	docker build -t mcp-bookmarks .

docker-run: ## Run the image on port 8000 with a named volume, trusting the development key
	@test -f .dev-keys/public.pem || (echo "run 'make token' first" && exit 1)
	docker run --rm -p 8000:8000 -v mcp-bookmarks-data:/data \
	  -v $(PWD)/.dev-keys/public.pem:/keys/public.pem:ro \
	  -e BOOKMARKS_PUBLIC_URL=http://127.0.0.1:8000 -e BOOKMARKS_ISSUER=https://dev-issuer.invalid \
	  -e BOOKMARKS_PUBLIC_KEY_FILE=/keys/public.pem mcp-bookmarks
