# Universal AI Stack Builder — convenience targets.
# Most targets assume a generated deployment in ./output.

OUTPUT ?= output
PROFILE ?= production
SIMULATE ?=

.PHONY: help install preview generate generate-k8s up down logs ps health \
        backup restore update rollback bundle bootstrap-tenants \
        audit-images scan sbom status eval clean test

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Bootstrap venv + deps and run the wizard
	./install.sh

preview:  ## Dry-run preview (no files written) — set SIMULATE="8xH100" to fake hardware
	python -m installer --profile $(PROFILE) $(if $(SIMULATE),--simulate "$(SIMULATE)") --dry-run --non-interactive

generate:  ## Generate the Compose deployment into $(OUTPUT)
	python -m installer --profile $(PROFILE) $(if $(SIMULATE),--simulate "$(SIMULATE)") --output $(OUTPUT) --non-interactive

generate-k8s:  ## Generate Compose + Kubernetes manifests + Helm chart
	python -m installer --profile $(PROFILE) $(if $(SIMULATE),--simulate "$(SIMULATE)") --target kubernetes --output $(OUTPUT) --non-interactive

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

backup:  ## Back up DB, volumes, configs and .env
	./scripts/backup.sh $(OUTPUT) backups

restore:  ## Restore from a backup: make restore BACKUP=backups/<stamp>
	./scripts/restore.sh $(BACKUP) $(OUTPUT)

update:  ## Safe update: backup, snapshot, pull, recreate, health-check
	./scripts/update.sh $(OUTPUT)

rollback:  ## Roll back to the previous image snapshot
	./scripts/rollback.sh $(OUTPUT)

bundle:  ## Build an offline/air-gapped bundle (images + deployment)
	./scripts/offline-bundle.sh create $(OUTPUT) ai-stack-bundle.tar

bootstrap-tenants:  ## Create LiteLLM teams/keys from policy.yaml (multi_tenant)
	./scripts/bootstrap-tenants.sh $(OUTPUT)

audit-images:  ## List images + pinning status (supply-chain)
	python -m installer audit-images --output $(OUTPUT)

scan:  ## Scan images for vulnerabilities (Trivy/Grype)
	./scripts/scan-images.sh $(OUTPUT)

sbom:  ## Generate CycloneDX SBOMs (Syft)
	./scripts/generate-sbom.sh $(OUTPUT)

status:  ## Admin overview of the generated deployment
	python -m installer status --output $(OUTPUT)

eval:  ## Run a golden-dataset eval: make eval DATASET=configs/eval/example-golden.yaml
	python -m installer eval --dataset $(DATASET) --output $(OUTPUT)

clean:  ## Remove generated output (keeps catalogs/profiles/templates)
	rm -rf $(OUTPUT)

test:  ## Run installer self-tests
	python -m pytest -q tests || python tests/test_smoke.py
