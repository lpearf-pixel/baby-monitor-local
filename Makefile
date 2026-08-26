SHELL := /bin/bash
PYTHON := ./.venv-alpha/bin/python
PYTHON311 ?= /usr/local/bin/python3.11
BASH ?= /bin/bash
.DEFAULT_GOAL := help

.PHONY: help alpha-update alpha-install alpha-start alpha-stop alpha-restart alpha-go2rtc-restart alpha-status alpha-guardian-start alpha-guardian-test alpha-guardian-test-live alpha-guardian-scene-test alpha-audio-status alpha-audio-test alpha-remote-preflight alpha-remote-status alpha-remote-configure alpha-remote-test alpha-voice-status alpha-voice-test alpha-voice-start alpha-voice-stop alpha-voice-listen-start alpha-voice-listen-status alpha-voice-listen-stop alpha-voice-preflight alpha-voice-v0-test alpha-voice-v0-probe alpha-voice-v0-stability alpha-voice-keychain-helper-build alpha-voice-keychain-migrate alpha-voice-keychain-check alpha-voice-converter-install alpha-voice-speaker-install alpha-voice-speaker-check alpha-voice-asr-install alpha-voice-ecapa-source alpha-voice-ecapa-install alpha-voice-ecapa-probe alpha-voice-paraformer-install alpha-voice-enroll-dad alpha-voice-enroll-mom alpha-voice-asr-capture alpha-voice-asr-capture-fixed alpha-voice-asr-capture-fixed-all alpha-voice-asr-capture-all alpha-voice-asr-evaluate alpha-voice-asr-bakeoff alpha-voice-asr-paraformer alpha-voice-asr-recover alpha-voice-vad-diagnostic alpha-voice-models-install alpha-voice-model-benchmark alpha-visual-status alpha-visual-performance alpha-visual-diagnostic alpha-visual-launchd-update alpha-logs alpha-quality-hd alpha-quality-info alpha-quality-rollback alpha-source-check alpha-subtype-probe alpha-subtype-apply alpha-go2rtc-info alpha-go2rtc-rebuild alpha-go2rtc-rollback alpha-realtime-models-check alpha-realtime-models-install alpha-ws2021-collect-calibrated alpha-ws2021-collect-model alpha-ws2021-model-train-bootstrap alpha-ws2021-model-train alpha-ws2021-model-export alpha-ws2021-model-check

help:
	@echo "Baby Monitor Local Alpha commands:"
	@echo "  make alpha-update            Update the Alpha branch without changing file modes"
	@echo "  make alpha-install           Install Intel macOS Alpha dependencies"
	@echo "  make alpha-start             Start go2rtc and the dashboard"
	@echo "  make alpha-stop              Stop Alpha services"
	@echo "  make alpha-restart           Restart Alpha services"
	@echo "  make alpha-go2rtc-restart    Restart only go2rtc on macOS"
	@echo "  make alpha-status            Show branch, listeners and health"
	@echo "  make alpha-guardian-start    Start and verify the complete guardian chain"
	@echo "  make alpha-guardian-test     Run complete automatic guardian acceptance"
	@echo "  make alpha-guardian-test-live Run supervised two-phone live acceptance"
	@echo "  make alpha-guardian-scene-test Run supervised household scene acceptance"
	@echo "  make alpha-audio-status      Show bounded audio worker status"
	@echo "  make alpha-audio-test        Run side-effect-free audio software gate"
	@echo "  make alpha-remote-preflight  Audit private remote access prerequisites"
	@echo "  make alpha-remote-status     Show redacted private remote access status"
	@echo "  make alpha-remote-configure  Apply the fixed private Serve route after confirmation"
	@echo "  make alpha-remote-test       Run side-effect-free private access software checks"
	@echo "  make alpha-voice-status      Show bounded Voice Care worker status"
	@echo "  make alpha-voice-test        Run side-effect-free Voice Care software gate"
	@echo "  make alpha-voice-start       Start only the Voice Care worker"
	@echo "  make alpha-voice-stop        Stop only the Voice Care worker"
	@echo "  make alpha-voice-listen-start Start the continuous listen-only Voice worker"
	@echo "  make alpha-voice-listen-status Show listen-only Voice worker status"
	@echo "  make alpha-voice-listen-stop Stop the continuous listen-only Voice worker"
	@echo "  make alpha-voice-preflight   Validate disabled Voice runtime without audio"
	@echo "  make alpha-voice-v0-test     Run synthetic Voice Care V0 software gate"
	@echo "  make alpha-voice-v0-probe    Run 60-second non-persistent audio probe"
	@echo "  make alpha-voice-v0-stability Run 10-minute non-persistent audio probe"
	@echo "  make alpha-voice-keychain-helper-build Build the stable signed Keychain helper"
	@echo "  make alpha-voice-keychain-migrate Copy the legacy ASR key to the stable helper"
	@echo "  make alpha-voice-keychain-check Check the existing calibration key via the helper"
	@echo "  make alpha-voice-converter-install Install the isolated Whisper converter"
	@echo "  make alpha-voice-speaker-install Install the isolated ECAPA runtime"
	@echo "  make alpha-voice-speaker-check Verify the isolated ECAPA runtime"
	@echo "  make alpha-voice-ecapa-source Acquire the pinned ECAPA source"
	@echo "  make alpha-voice-ecapa-install Install the verified ECAPA bundle"
	@echo "  make alpha-voice-ecapa-probe Run the generated local ECAPA gate"
	@echo "  make alpha-voice-enroll-dad Privately enroll Dad on this i9"
	@echo "  make alpha-voice-enroll-mom Privately enroll Mom on this i9"
	@echo "  make alpha-voice-asr-capture PROMPT=<id> Save one encrypted fixed test phrase"
	@echo "  make alpha-voice-asr-capture-fixed PROMPT=<id> Rerecord one clip through macOS login launchd"
	@echo "  make alpha-voice-asr-capture-fixed-all Rerecord all six clips through macOS login launchd"
	@echo "  make alpha-voice-asr-capture-all Save the six fixed phrases in one session"
	@echo "  make alpha-voice-asr-evaluate Re-evaluate the encrypted fixed phrase corpus"
	@echo "  make alpha-voice-asr-bakeoff Run the closed local ASR decode matrix"
	@echo "  make alpha-voice-asr-paraformer Evaluate the pinned Mandarin Paraformer candidate"
	@echo "  make alpha-voice-asr-recover Safely recover a blocked headless ASR request"
	@echo "  make alpha-voice-asr-install Install the isolated pinned Paraformer runtime"
	@echo "  make alpha-voice-paraformer-install Install the verified Paraformer model bundle"
	@echo "  make alpha-voice-vad-diagnostic Run aggregate Silero signal diagnostics"
	@echo "  make alpha-voice-models-install Install verified local Whisper base/small models"
	@echo "  make alpha-voice-model-benchmark Run generated local Whisper base/small gate"
	@echo "  make alpha-visual-status     Show redacted visual worker and M2 bridge health"
	@echo "  make alpha-visual-performance Run the 10-minute redacted performance gate"
	@echo "  make alpha-visual-diagnostic Measure redacted realtime stage timings"
	@echo "  make alpha-visual-launchd-update Safely apply interactive visual scheduling"
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
	@echo "  make alpha-ws2021-collect-calibrated Collect private crops at current calibration"
	@echo "  make alpha-ws2021-collect-model      Collect private crops using local detector"
	@echo "  make alpha-ws2021-dataset            Build the private deterministic dataset"
	@echo "  make alpha-ws2021-model-train-bootstrap Train 20-epoch collection seed on i9"
	@echo "  make alpha-ws2021-model-train        Train private YOLOX-Tiny weights on i9"
	@echo "  make alpha-ws2021-model-export       Export private OpenVINO FP16 model"
	@echo "  make alpha-ws2021-model-check        Verify private model artifacts"

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

alpha-ws2021-collect-calibrated:
	@$(PYTHON) tools/ws2021_collect.py calibrated

alpha-ws2021-collect-model:
	@$(PYTHON) tools/ws2021_collect.py model

alpha-ws2021-dataset:
	@$(PYTHON) tools/ws2021_dataset.py --source runtime/training/ws2021/crops --output runtime/training/ws2021/dataset

alpha-ws2021-model-train-bootstrap:
	@$(PYTHON) tools/ws2021_model.py train-bootstrap

alpha-ws2021-model-train:
	@$(PYTHON) tools/ws2021_model.py train

alpha-ws2021-model-export:
	@$(PYTHON) tools/ws2021_model.py export

alpha-ws2021-model-check:
	@$(PYTHON) tools/ws2021_model.py check

alpha-start:
	@bash tools/start_alpha.sh

alpha-stop:
	@bash tools/stop_alpha.sh

alpha-restart: alpha-stop alpha-start

alpha-go2rtc-restart:
	@bash tools/start_alpha.sh --go2rtc-only-restart

alpha-guardian-start:
	@$(BASH) tools/start_guardian.sh

alpha-guardian-test:
	@$(BASH) tools/test_guardian.sh

alpha-guardian-test-live:
	@$(BASH) tools/test_guardian_live.sh

alpha-guardian-scene-test:
	@$(PYTHON) tools/guardian_scene_acceptance.py

alpha-audio-status:
	@$(PYTHON) tools/audio_status.py runtime/status/audio.json

alpha-audio-test:
	@$(PYTHON) -m pytest -q tests/audio tests/contracts/test_audio.py tests/contracts/test_audio_settings.py tests/deploy/test_audio_worker_deploy.py

alpha-remote-preflight:
	@$(PYTHON) tools/private_remote_access.py preflight

alpha-remote-status:
	@$(PYTHON) tools/private_remote_access.py status

alpha-remote-configure:
	@$(PYTHON) tools/private_remote_access.py configure

alpha-remote-test:
	@$(PYTHON) -m pytest -q tests/monitoring/test_private_remote_access.py tests/tools/test_private_remote_access.py tests/deploy/test_private_remote_access.py tests/deploy/test_network_access.py

alpha-voice-status:
	@$(PYTHON) tools/voice_status.py runtime/status/voice.json

alpha-voice-test:
	@$(PYTHON) -m pytest -q tests/voice tests/contracts/test_voice_care.py tests/contracts/test_voice_settings.py tests/tools/test_voice_status.py tests/deploy/test_voice_worker_deploy.py tests/deploy/test_voice_listen_lifecycle.py

alpha-voice-start:
	@$(BASH) tools/start_alpha.sh --voice-only

alpha-voice-stop:
	@$(BASH) tools/stop_alpha.sh --voice-only

alpha-voice-listen-start:
	@$(BASH) tools/voice_listen_lifecycle.sh start

alpha-voice-listen-status:
	@$(BASH) tools/voice_listen_lifecycle.sh status

alpha-voice-listen-stop:
	@$(BASH) tools/voice_listen_lifecycle.sh stop

alpha-voice-preflight:
	@$(PYTHON) -m tools.voice_asr_capture_macos preflight

alpha-voice-v0-test:
	@$(PYTHON) -m pytest -q tests/audio tests/stream/test_probe.py tests/tools/test_voice_audio_probe.py tests/deploy/test_audio_worker_deploy.py
	@$(PYTHON) tools/voice_audio_probe.py synthetic

alpha-voice-v0-probe:
	@$(PYTHON) tools/voice_audio_probe.py live --duration 60

alpha-voice-v0-stability:
	@$(PYTHON) tools/voice_audio_probe.py live --duration 600

alpha-voice-keychain-helper-build:
	@$(PYTHON) -m tools.voice_keychain_helper_build ensure

alpha-voice-keychain-migrate:
	@$(PYTHON) -m tools.voice_keychain_migrate

alpha-voice-keychain-check:
	@$(PYTHON) -m tools.voice_keychain_probe

alpha-voice-converter-install:
	@set -eu; \
	"$(PYTHON311)" tools/voice_converter_environment.py --project-root . >/dev/null 2>&1 || { echo "voice_converter_install=unavailable"; exit 1; }; \
	environment="runtime/voice-converter-venv"; \
	if [[ "$$(uname -s)" != "Darwin" || "$$(uname -m)" != "x86_64" || ! -x "$(PYTHON311)" || -L "$$environment" ]]; then \
		echo "voice_converter_install=unavailable"; \
		exit 1; \
	fi; \
	if [[ ! -x "$$environment/bin/python" ]]; then \
		"$(PYTHON311)" -m venv "$$environment" >/dev/null 2>&1 || { echo "voice_converter_install=failed"; exit 1; }; \
	else \
		"$(PYTHON311)" -m venv --upgrade "$$environment" >/dev/null 2>&1 || { echo "voice_converter_install=failed"; exit 1; }; \
	fi; \
	"$$environment/bin/python" -m pip install --requirement config/voice-converter-requirements.txt >/dev/null 2>&1 || { echo "voice_converter_install=failed"; exit 1; }; \
	"$$environment/bin/python" tools/voice_whisper_converter.py --check --expected-prefix "$$PWD/$$environment" >/dev/null 2>&1 || { echo "voice_converter_install=failed"; exit 1; }; \
	echo "voice_converter_install=ready"

alpha-voice-speaker-install:
	@set -eu; \
	if [[ "$$(uname -s)" != "Darwin" || "$$(uname -m)" != "x86_64" || ! -x "$(PYTHON311)" ]]; then \
		echo "voice_speaker_install=unavailable"; \
		exit 1; \
	fi; \
	"$(PYTHON311)" tools/voice_speaker_environment.py --project-root . --path-only >/dev/null 2>&1 || { echo "voice_speaker_install=unavailable"; exit 1; }; \
	environment="runtime/voice-speaker-venv"; \
	if [[ ! -x "$$environment/bin/python" ]]; then \
		"$(PYTHON311)" -m venv "$$environment" >/dev/null 2>&1 || { echo "voice_speaker_install=failed"; exit 1; }; \
	else \
		"$(PYTHON311)" -m venv --upgrade "$$environment" >/dev/null 2>&1 || { echo "voice_speaker_install=failed"; exit 1; }; \
	fi; \
	"$$environment/bin/python" -m pip install --requirement config/voice-speaker-requirements.txt >/dev/null 2>&1 || { echo "voice_speaker_install=failed"; exit 1; }; \
	"$(PYTHON311)" tools/voice_speaker_environment.py --project-root . --expected-prefix "$$PWD/$$environment" >/dev/null 2>&1 || { echo "voice_speaker_install=failed"; exit 1; }; \
	echo "voice_speaker_install=ready"

alpha-voice-speaker-check:
	@set -eu; \
	if [[ "$$(uname -s)" != "Darwin" || "$$(uname -m)" != "x86_64" || ! -x "$(PYTHON311)" ]]; then \
		echo "voice_speaker_check=unavailable"; \
		exit 1; \
	fi; \
	environment="runtime/voice-speaker-venv"; \
	"$(PYTHON311)" tools/voice_speaker_environment.py --project-root . --expected-prefix "$$PWD/$$environment" >/dev/null 2>&1 || { echo "voice_speaker_check=unavailable"; exit 1; }; \
	echo "voice_speaker_check=ready"

alpha-voice-asr-install:
	@set -eu; \
	if [[ "$$(uname -s)" != "Darwin" || "$$(uname -m)" != "x86_64" || ! -x "$(PYTHON311)" ]]; then \
		echo "voice_asr_install=unavailable"; \
		exit 1; \
	fi; \
	"$(PYTHON311)" -m tools.voice_asr_install --project-root . --base-python "$(PYTHON311)" >/dev/null 2>&1 || { echo "voice_asr_install=failed"; exit 1; }; \
	echo "voice_asr_install=ready"

alpha-voice-ecapa-source:
	@set -eu; \
	environment="runtime/voice-speaker-venv"; \
	if [[ "$$(uname -s)" != "Darwin" || "$$(uname -m)" != "x86_64" || ! -x "$(PYTHON311)" || ! -x "$$environment/bin/python" ]]; then \
		echo "voice_ecapa_source=unavailable"; \
		exit 1; \
	fi; \
	"$(PYTHON311)" tools/voice_speaker_environment.py --project-root . --expected-prefix "$$PWD/$$environment" >/dev/null 2>&1 || { echo "voice_ecapa_source=unavailable"; exit 1; }; \
	"$$environment/bin/python" -m tools.voice_ecapa_source --project-root . >/dev/null 2>&1 || { echo "voice_ecapa_source=failed"; exit 1; }; \
	echo "voice_ecapa_source=ready"

alpha-voice-ecapa-install:
	@set -eu; \
	settings="runtime/config/voice-care-models.json"; \
	source="runtime/models/voice-care-sources/speechbrain-ecapa-voxceleb/source"; \
	manifest="runtime/models/voice-care-sources/speechbrain-ecapa-voxceleb/source-manifest.json"; \
	if [[ ! -x "$(PYTHON)" || ! -f "$$settings" || -L "$$settings" || ! -d "$$source" || -L "$$source" || ! -f "$$manifest" || -L "$$manifest" ]]; then \
		echo "voice_ecapa_install=unavailable"; \
		exit 1; \
	fi; \
	manifest_sha=$$(/usr/bin/shasum -a 256 "$$manifest" 2>/dev/null | /usr/bin/awk '{print $$1}') || { echo "voice_ecapa_install=unavailable"; exit 1; }; \
	if [[ ! "$$manifest_sha" =~ ^[0-9a-f]{64}$$ ]]; then \
		echo "voice_ecapa_install=unavailable"; \
		exit 1; \
	fi; \
	$(PYTHON) -m tools.voice_models --settings "$$settings" --artifact "speechbrain-ecapa-voxceleb" --operation acquire --source-dir "$$source" --source-manifest "$$manifest" --source-manifest-sha256 "$$manifest_sha" --project-root . >/dev/null 2>&1 || { echo "voice_ecapa_install=failed"; exit 1; }; \
	echo "voice_ecapa_install=ready"

alpha-voice-paraformer-install:
	@set -eu; \
	settings="runtime/config/voice-care-models.json"; \
	source="runtime/models/voice-care-sources/sherpa-onnx-paraformer-zh-2023-09-14/source"; \
	manifest="runtime/models/voice-care-sources/sherpa-onnx-paraformer-zh-2023-09-14/source-manifest.json"; \
	if [[ ! -x "$(PYTHON)" || ! -f "$$settings" || -L "$$settings" || ! -d "$$source" || -L "$$source" || ! -f "$$manifest" || -L "$$manifest" ]]; then \
		echo "voice_paraformer_install=unavailable"; \
		exit 1; \
	fi; \
	manifest_sha=$$(/usr/bin/shasum -a 256 "$$manifest" 2>/dev/null | /usr/bin/awk '{print $$1}') || { echo "voice_paraformer_install=unavailable"; exit 1; }; \
	if [[ ! "$$manifest_sha" =~ ^[0-9a-f]{64}$$ ]]; then \
		echo "voice_paraformer_install=unavailable"; \
		exit 1; \
	fi; \
	$(PYTHON) -m tools.voice_models --settings "$$settings" --artifact "sherpa-onnx-paraformer-zh-2023-09-14" --operation acquire --source-dir "$$source" --source-manifest "$$manifest" --source-manifest-sha256 "$$manifest_sha" --project-root . >/dev/null 2>&1 || { echo "voice_paraformer_install=failed"; exit 1; }; \
	echo "voice_paraformer_install=ready"

alpha-voice-ecapa-probe:
	@$(PYTHON) -c 'from tools.voice_ecapa_probe_cli import run; raise SystemExit(run())'

alpha-voice-enroll-dad:
	@$(PYTHON) -m tools.voice_enroll --role dad

alpha-voice-enroll-mom:
	@$(PYTHON) -m tools.voice_enroll --role mom

alpha-voice-asr-capture:
	@$(PYTHON) -m tools.voice_asr_calibrate capture --prompt-id "$(PROMPT)"

alpha-voice-asr-capture-fixed:
	@$(PYTHON) -m tools.voice_asr_capture_macos record --prompt-id "$(PROMPT)"

alpha-voice-asr-capture-fixed-all:
	@set -eu; \
	for prompt in feeding_start_dad feeding_start_mom feeding_amount feeding_finish care_cancel negative_weather; do \
		$(PYTHON) -m tools.voice_asr_capture_macos record --prompt-id "$$prompt"; \
	done

alpha-voice-asr-capture-all:
	@$(PYTHON) -m tools.voice_asr_calibrate capture-all

alpha-voice-asr-evaluate:
	@$(PYTHON) -m tools.voice_asr_calibrate evaluate

alpha-voice-asr-bakeoff:
	@$(PYTHON) -m tools.voice_asr_calibrate bakeoff

alpha-voice-asr-paraformer:
	@$(PYTHON) -m tools.voice_asr_capture_macos paraformer

alpha-voice-asr-recover:
	@$(PYTHON) -m tools.voice_asr_capture_macos recover

alpha-voice-vad-diagnostic:
	@$(PYTHON) -m tools.voice_asr_capture_macos vad-diagnostic

alpha-voice-models-install:
	@set -eu; \
	settings="runtime/config/voice-care-models.json"; \
	base_source="runtime/models/voice-care-sources/openai-whisper-base/source"; \
	base_manifest="runtime/models/voice-care-sources/openai-whisper-base/source-manifest.json"; \
	small_source="runtime/models/voice-care-sources/openai-whisper-small/source"; \
	small_manifest="runtime/models/voice-care-sources/openai-whisper-small/source-manifest.json"; \
	if [[ ! -f "$$settings" || -L "$$settings" || ! -d "$$base_source" || -L "$$base_source" || ! -f "$$base_manifest" || -L "$$base_manifest" || ! -d "$$small_source" || -L "$$small_source" || ! -f "$$small_manifest" || -L "$$small_manifest" ]]; then \
		echo "voice_models_install=unavailable"; \
		exit 1; \
	fi; \
	base_sha=$$(/usr/bin/shasum -a 256 "$$base_manifest" 2>/dev/null | /usr/bin/awk '{print $$1}') || { echo "voice_models_install=unavailable"; exit 1; }; \
	small_sha=$$(/usr/bin/shasum -a 256 "$$small_manifest" 2>/dev/null | /usr/bin/awk '{print $$1}') || { echo "voice_models_install=unavailable"; exit 1; }; \
	if [[ ! "$$base_sha" =~ ^[0-9a-f]{64}$$ || ! "$$small_sha" =~ ^[0-9a-f]{64}$$ ]]; then \
		echo "voice_models_install=unavailable"; \
		exit 1; \
	fi; \
	$(PYTHON) tools/voice_models.py --settings "$$settings" --artifact "openai-whisper-base" --operation convert-whisper --source-dir "$$base_source" --source-manifest "$$base_manifest" --source-manifest-sha256 "$$base_sha" --project-root . >/dev/null 2>&1 || { echo "voice_models_install=failed"; exit 1; }; \
	$(PYTHON) tools/voice_models.py --settings "$$settings" --artifact "openai-whisper-small" --operation convert-whisper --source-dir "$$small_source" --source-manifest "$$small_manifest" --source-manifest-sha256 "$$small_sha" --project-root . >/dev/null 2>&1 || { echo "voice_models_install=failed"; exit 1; }; \
	echo "voice_models_install=ready"

alpha-voice-model-benchmark:
	@$(PYTHON) tools/voice_model_benchmark.py

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

alpha-visual-launchd-update:
	@$(BASH) tools/update_visual_launchd.sh
