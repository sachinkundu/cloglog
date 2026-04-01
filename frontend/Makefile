.PHONY: test coverage lint dev build

test: ## Run frontend tests
	npx vitest run

coverage: ## Run tests with coverage
	npx vitest run --coverage

lint: ## Run linter
	npx tsc --noEmit

dev: ## Start dev server
	npx vite

build: ## Build for production
	npx vite build
