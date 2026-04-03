.PHONY: test coverage build quality

test: ## Run MCP server tests
	npx vitest run

coverage: ## Run tests with coverage
	npx vitest run --coverage

build: ## Build TypeScript
	npx tsc

quality: build test ## Build and run all tests
	@echo "✓ MCP server quality gate passed"
