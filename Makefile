# MaxSurge — common ops shortcuts
# Usage: make <target>

VENV := ./venv/bin
PY := $(VENV)/python
SERVICE := maxsurge

.PHONY: help
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install:  ## Install / update Python dependencies
	$(VENV)/pip install -r requirements.txt

.PHONY: run
run:  ## Run dev server (uvicorn with reload)
	$(PY) -m uvicorn main:app --reload --host 0.0.0.0 --port 8090

.PHONY: restart
restart:  ## Restart production systemd service
	systemctl restart $(SERVICE)
	sleep 3
	systemctl is-active $(SERVICE)

.PHONY: logs
logs:  ## Tail systemd service logs
	journalctl -u $(SERVICE) -f --no-pager

.PHONY: status
status:  ## Show systemd service status
	systemctl status $(SERVICE) --no-pager

.PHONY: health
health:  ## curl /health
	@curl -sf http://localhost:8090/health | $(PY) -m json.tool

.PHONY: smoke
smoke:  ## Run E2E smoke tests against prod
	bash scripts/e2e_smoke.sh

.PHONY: smoke-local
smoke-local:  ## Run E2E smoke tests against localhost:8090
	BASE=http://localhost:8090 bash scripts/e2e_smoke.sh

.PHONY: seed
seed:  ## Seed dev database with test users and data (ENV=dev required)
	ENV=dev $(PY) scripts/seed_dev.py

.PHONY: seed-wipe
seed-wipe:  ## Wipe and re-seed dev database
	ENV=dev $(PY) scripts/seed_dev.py --wipe

.PHONY: backup
backup:  ## Create timestamped DB backup
	@mkdir -p backups
	@ts=$$(date +%Y%m%d_%H%M%S); \
	sqlite3 max_leadfinder.db ".backup backups/max_leadfinder_$${ts}.db" && \
	gzip backups/max_leadfinder_$${ts}.db && \
	echo "backup: backups/max_leadfinder_$${ts}.db.gz ($$(du -h backups/max_leadfinder_$${ts}.db.gz | cut -f1))"

.PHONY: backup-clean
backup-clean:  ## Delete backups older than 14 days
	find backups/ -name "max_leadfinder_*.db.gz" -mtime +14 -delete
	@echo "cleaned backups older than 14 days"

.PHONY: metrics
metrics:  ## Fetch /metrics (requires .env with ADMIN_EMAIL/PASSWORD)
	@. ./.env && curl -sf -u "$$ADMIN_EMAIL:$$ADMIN_PASSWORD" http://localhost:8090/metrics

.PHONY: compile-check
compile-check:  ## Syntax-check all Python files
	@find . -name "*.py" -not -path "./venv/*" -not -path "./__pycache__/*" -not -path "*/__pycache__/*" | \
		xargs -I {} $(PY) -c "import py_compile; py_compile.compile('{}', doraise=True)" && \
	echo "compile: OK"

.PHONY: deploy-check
deploy-check: compile-check health smoke  ## Full deploy validation (compile + health + smoke)
	@echo "deploy-check: all green"
