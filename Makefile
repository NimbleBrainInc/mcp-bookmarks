.PHONY: help install format format-check lint typecheck test check run docker-build docker-run

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

run: ## Serve on http://127.0.0.1:8000/mcp
	uv run python -m mcp_bookmarks.server

docker-build: ## Build the container image
	docker build -t mcp-bookmarks .

docker-run: ## Run the image on port 8000 with a named volume
	docker run --rm -p 8000:8000 -v mcp-bookmarks-data:/data mcp-bookmarks
