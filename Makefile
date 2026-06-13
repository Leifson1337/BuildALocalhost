# Universal AI Stack Builder — convenience targets.
# Most targets assume a generated deployment in ./output.

OUTPUT ?= output
PROFILE ?= production
SIMULATE ?=

.PHONY: help install preview generate up down logs ps health clean test

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Bootstrap venv + deps and run the wizard
	./install.sh

preview:  ## Dry-run preview (no files written) — set SIMULATE="8xH100" to fake hardware
	python -m installer --profile $(PROFILE) $(if $(SIMULATE),--simulate "$(SIMULATE)") --dry-run --non-interactive

generate:  ## Generate the deployment into $(OUTPUT)
	python -m installer --profile $(PROFILE) $(if $(SIMULATE),--simulate "$(SIMULATE)") --output $(OUTPUT) --non-interactive

up:  ## Start the generated stack
	cd $(OUTPUT) && docker compose pull && docker compose up -d

down:  ## Stop the stack
	cd $(OUTPUT) && docker compose down

logs:  ## Tail logs
	cd $(OUTPUT) && docker compose logs -f --tail=100

ps:  ## Show running services
	cd $(OUTPUT) && docker compose ps

health:  ## Run health checks against the gateway
	./scripts/healthcheck.sh $(OUTPUT)

clean:  ## Remove generated output (keeps catalogs/profiles/templates)
	rm -rf $(OUTPUT)

test:  ## Run installer self-tests
	python -m pytest -q tests || python tests/test_smoke.py
