# FirePilot — Local Development Makefile
# All validation targets run with FIREPILOT_ENV=demo (mock mode).
# Reference: docs/adr/0003-cicd-pipeline-design-and-policy-validation-toolchain.md

PYTHON  ?= python3
OPA     ?= opa
RUFF    ?= ruff

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: check-deps
check-deps: ## Verify required tools are installed
	@bash ci/scripts/check-deps.sh

.PHONY: validate
validate: check-deps ## Run Gates 1–3 (same as CI)
	FIREPILOT_ENV=demo bash ci/scripts/validate-all.sh

.PHONY: test-policies
test-policies: check-deps ## Run OPA policy tests only
	$(OPA) test ci/policies/ -v

.PHONY: lint
lint: ## Run ruff against all Python code
	@if command -v $(RUFF) >/dev/null 2>&1; then \
		$(RUFF) check \
			--exclude .venv \
			--exclude __pycache__ \
			--exclude build \
			--exclude dist \
			.; \
	else \
		echo "WARNING: ruff not found — skipping lint. Install with: pip install ruff"; \
		exit 0; \
	fi

.PHONY: test
test: ## Run all Python tests (MCP servers)
	@found=0; \
	for server_dir in mcp-servers/*/; do \
		if [ -f "$$server_dir/pyproject.toml" ] && [ -d "$$server_dir/tests" ]; then \
			found=1; \
			echo "Running tests in $$server_dir..."; \
			(cd "$$server_dir" && FIREPILOT_ENV=demo $(PYTHON) -m pytest tests/ -v) || exit 1; \
		fi; \
	done; \
	if [ "$$found" -eq 0 ]; then \
		echo "No MCP server test directories found — nothing to run."; \
	fi

.PHONY: demo
demo: ## Run full CI validation pipeline (Gates 1–4) in demo mode; uses Docker if available
	@if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then \
		docker compose -f demo/docker-compose.yml run --rm --build demo-validate && \
		docker compose -f demo/docker-compose.yml run --rm demo-validate bash ci/scripts/gate4-deploy.sh; \
	else \
		bash demo/demo-validate.sh; \
	fi

.PHONY: demo-orchestrator
demo-orchestrator: ## Run Claude-powered analysis of the example issue (requires ANTHROPIC_API_KEY)
	@if [ -z "$${ANTHROPIC_API_KEY:-}" ]; then \
		echo "ERROR: ANTHROPIC_API_KEY is not set."; \
		echo "Export your Anthropic API key before running this target:"; \
		echo "  export ANTHROPIC_API_KEY=sk-ant-..."; \
		exit 1; \
	fi
	@if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then \
		docker compose -f demo/docker-compose.yml run --rm --build demo-orchestrator; \
	else \
		$(PYTHON) ci/scripts/process-issue.py --issue-body "$$(cat demo/example-issue.md)"; \
	fi

.PHONY: demo-clean
demo-clean: ## Remove Docker images and containers created by the demo
	docker compose -f demo/docker-compose.yml down --rmi local 2>/dev/null || true

.PHONY: clean
clean: ## Remove generated files / caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
