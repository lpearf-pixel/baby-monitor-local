SHELL := /bin/bash
PYTHON := ./.venv-alpha/bin/python
BASH ?= /bin/bash
.DEFAULT_GOAL := help

.PHONY: help alpha-update alpha-install alpha-start alpha-stop alpha-restart alpha-status alpha-visual-status alpha-visual-performance alpha-visual-diagnostic alpha-logs alpha-quality-hd alpha-quality-info alpha-quality-rollback alpha-source-check alpha-subtype-probe alpha-subtype-apply alpha-go2rtc-info alpha-go2rtc-rebuild alpha-go2rtc-rollback alpha-realtime-models-check alpha-realtime-models-install

help:
	@echo "Baby Monitor Local Alpha commands:"
	@echo "  make alpha-update            Update the Alpha branch without changing file modes"
	@echo "  make alpha-install           Install Intel macOS Alpha dependencies"
	@echo "  make alpha-start             Start go2rtc and the dashboard"
	@echo "  make alpha-stop              Stop Alpha services"
	@echo "  make alpha-restart           Restart Alpha services"
	@echo "  make alpha-status            Show branch, listeners and health"
	@echo "  make alpha-visual-status     Show redacted visual worker and M2 bridge health"
	@echo "  make alpha-visual-performance Run the 10-minute redacted performance gate"
	@echo "  make alpha-visual-diagnostic Measure redacted realtime stage timings"
	@echo "  make alpha-logs              Tail recent service logs"
	@echo "  make alpha-quality-hd        Enable 720p MJPEG plus on-demand VideoToolbox HD"
	@echo "  make alpha-quality-info      Show non-sensitive preview quality settings"
	@echo "  make alpha-quality-rollback  Restore the newest quality backup"
	@echo "  make alpha-source-check      Verify source codec, media and HD preview health"
	@echo "  make alpha-subtype-probe     Safely probe Xiaomi source quality numbers 0-5"
	@echo "  make alpha-subtype-apply     Apply verified MJSXJ17CM native HD subtype 3"
	@echo "  make alpha-go2rtc-info       Show non-sensitive pinned build metadata"
	@echo "  make alpha-go2rtc-rebuild    Rebuild the pinned patched go2rtc binary"
	@echo "  make alpha-go2rtc-rollback   Restore the newest valid go2rtc backup"
	@echo "  make alpha-realtime-models-check    Verify pinned realtime visual models"
	@echo "  make alpha-realtime-models-install  Explicitly install pinned models"

alpha-update:
	@git config core.fileMode false
	@git fetch origin
	@git switch codex/basic-usable-alpha
	@git pull --ff-only
	@echo "Alpha branch updated without changing script permissions."

alpha-install:
	@bash tools/install_alpha_macos.sh

alpha-go2rtc-info:
	@$(PYTHON) tools/go2rtc_build.py info

alpha-go2rtc-rebuild:
	@$(PYTHON) tools/go2rtc_build.py rebuild

alpha-go2rtc-rollback:
	@$(PYTHON) tools/go2rtc_build.py rollback

alpha-realtime-models-check:
	@$(PYTHON) tools/realtime_models.py check

alpha-realtime-models-install:
	@$(PYTHON) tools/realtime_models.py install

alpha-start:
	@bash tools/start_alpha.sh

alpha-stop:
	@bash tools/stop_alpha.sh

alpha-restart: alpha-stop alpha-start

alpha-status:
	@if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
		echo "Branch: $$(git branch --show-current)"; \
		echo "Commit: $$(git rev-parse --short HEAD)"; \
	else \
		echo "Source: packaged archive"; \
	fi
	@echo "Dashboard listener:"
	@lsof -nP -iTCP:$${BABY_MONITOR_PORT:-8080} -sTCP:LISTEN 2>/dev/null || true
	@echo "go2rtc listener:"
	@lsof -nP -iTCP:1984 -sTCP:LISTEN 2>/dev/null || true
	@echo "Gauge worker:"
	@if [[ "$$(uname -s)" == "Darwin" ]] && launchctl print "gui/$$(id -u)/com.babymonitor.gauge" >/dev/null 2>&1; then \
		echo "running (launchd)"; \
	elif [[ -f runtime/pids/gauge.pid ]] && kill -0 "$$(cat runtime/pids/gauge.pid)" 2>/dev/null; then \
		echo "running (pid)"; \
	else echo "offline"; fi
	@echo "Dashboard health:"
	@curl -fsS http://127.0.0.1:$${BABY_MONITOR_PORT:-8080}/healthz 2>/dev/null || echo "offline"

alpha-logs:
	@echo "=== go2rtc ==="
	@tail -n 80 runtime/logs/go2rtc.log 2>/dev/null || true
	@echo "=== dashboard ==="
	@tail -n 80 runtime/logs/api.log 2>/dev/null || true
	@echo "=== gauge ==="
	@tail -n 80 runtime/logs/gauge.log 2>/dev/null || true
	@echo "=== environment watchdog ==="
	@tail -n 80 runtime/logs/environment-watchdog.log 2>/dev/null || true

alpha-quality-hd:
	@$(PYTHON) tools/alpha_quality.py apply-hd --config runtime/go2rtc.yaml --backups runtime/backups
	@$(MAKE) alpha-restart
	@$(MAKE) alpha-source-check

alpha-quality-info:
	@$(PYTHON) tools/alpha_quality.py info --config runtime/go2rtc.yaml

alpha-quality-rollback:
	@$(PYTHON) tools/alpha_quality.py rollback --config runtime/go2rtc.yaml --backups runtime/backups
	@$(MAKE) alpha-restart

alpha-source-check:
	@set -a; \
	if [[ -f runtime/alpha.env ]]; then source runtime/alpha.env; fi; \
	set +a; \
	$(PYTHON) tools/alpha_quality.py check \
		--base-url "$${GO2RTC_BASE_URL:-http://127.0.0.1:1984}" \
		--dashboard-url "http://127.0.0.1:$${BABY_MONITOR_PORT:-8080}"

alpha-subtype-probe:
	@set -a; \
	if [[ -f runtime/alpha.env ]]; then source runtime/alpha.env; fi; \
	set +a; \
	$(PYTHON) tools/alpha_quality.py probe-subtypes \
		--config runtime/go2rtc.yaml \
		--backups runtime/backups \
		--base-url "$${GO2RTC_BASE_URL:-http://127.0.0.1:1984}" \
		--candidates 0 1 2 3 4 5 \
		--restart-command "make --no-print-directory alpha-restart"

alpha-subtype-apply:
	@set -a; \
	if [[ -f runtime/alpha.env ]]; then source runtime/alpha.env; fi; \
	set +a; \
	$(PYTHON) tools/alpha_quality.py apply-subtype \
		--config runtime/go2rtc.yaml \
		--backups runtime/backups \
		--base-url "$${GO2RTC_BASE_URL:-http://127.0.0.1:1984}" \
		--dashboard-url "http://127.0.0.1:$${BABY_MONITOR_PORT:-8080}" \
		--subtype 3 \
		--minimum-width 1920 \
		--minimum-height 1080 \
		--restart-command "make --no-print-directory alpha-restart"

alpha-visual-status:
	@metrics_status=0; \
	visual_running=0; \
	echo "Visual worker:"; \
	if [[ "$$(uname -s)" == "Darwin" ]] && launchctl print "gui/$$(id -u)/com.babymonitor.visual" >/dev/null 2>&1; then \
		echo "running (launchd)"; \
		visual_running=1; \
	elif [[ -f runtime/pids/visual.pid ]] && kill -0 "$$(cat runtime/pids/visual.pid)" 2>/dev/null; then \
		echo "running (pid)"; \
		visual_running=1; \
	else \
		echo "offline"; \
	fi; \
	if [[ "$$visual_running" -eq 1 ]]; then \
		$(PYTHON) tools/realtime_visual_status.py || metrics_status=$$?; \
	fi; \
	echo "Ollama tunnel:"; \
	if [[ "$$(uname -s)" == "Darwin" ]] && launchctl print "gui/$$(id -u)/com.babymonitor.ollama-tunnel" >/dev/null 2>&1; then \
		echo "running (launchd)"; \
	else \
		echo "offline"; \
	fi; \
	echo "Ollama bridge:"; \
	if curl -fsS --noproxy '*' --max-time 2 http://127.0.0.1:11435/api/version >/dev/null 2>&1; then \
		echo "reachable"; \
	else \
		echo "unreachable"; \
	fi; \
	exit "$$metrics_status"

alpha-visual-performance:
	@$(PYTHON) tools/realtime_visual_performance.py

alpha-visual-diagnostic:
	@$(BASH) tools/run_realtime_visual_diagnostic.sh
