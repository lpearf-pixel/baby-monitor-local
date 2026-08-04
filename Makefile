SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help alpha-update alpha-install alpha-start alpha-stop alpha-restart alpha-status alpha-logs

help:
	@echo "Baby Monitor Local Alpha commands:"
	@echo "  make alpha-update   Update the Alpha branch without changing file modes"
	@echo "  make alpha-install  Install Intel macOS Alpha dependencies"
	@echo "  make alpha-start    Start go2rtc and the dashboard"
	@echo "  make alpha-stop     Stop Alpha services"
	@echo "  make alpha-restart  Restart Alpha services"
	@echo "  make alpha-status   Show branch, listeners and health"
	@echo "  make alpha-logs     Tail recent service logs"

alpha-update:
	@git config core.fileMode false
	@git fetch origin
	@git switch codex/basic-usable-alpha
	@git pull --ff-only
	@echo "Alpha branch updated without changing script permissions."

alpha-install:
	@bash tools/install_alpha_macos.sh

alpha-start:
	@bash tools/start_alpha.sh

alpha-stop:
	@bash tools/stop_alpha.sh

alpha-restart: alpha-stop alpha-start

alpha-status:
	@echo "Branch: $$(git branch --show-current)"
	@echo "Commit: $$(git rev-parse --short HEAD)"
	@echo "Dashboard listener:"
	@lsof -nP -iTCP:$${BABY_MONITOR_PORT:-8080} -sTCP:LISTEN 2>/dev/null || true
	@echo "go2rtc listener:"
	@lsof -nP -iTCP:1984 -sTCP:LISTEN 2>/dev/null || true
	@echo "Dashboard health:"
	@curl -fsS http://127.0.0.1:$${BABY_MONITOR_PORT:-8080}/healthz 2>/dev/null || echo "offline"

alpha-logs:
	@echo "=== go2rtc ==="
	@tail -n 80 runtime/logs/go2rtc.log 2>/dev/null || true
	@echo "=== dashboard ==="
	@tail -n 80 runtime/logs/api.log 2>/dev/null || true
