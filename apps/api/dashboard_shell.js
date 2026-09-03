(function exposeDashboardShell(root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BabyMonitorDashboardShell = api;
  if (root.document) {
    const mount = () => {
      if (!root.BabyMonitorDashboardViews) return;
      api.mountDashboardShell({
        analyticsController: root.BabyMonitorDashboardAnalytics ?? null,
        clearInterval: root.clearInterval.bind(root),
        document: root.document,
        fetch: root.fetch.bind(root),
        setInterval: root.setInterval.bind(root),
        views: root.BabyMonitorDashboardViews,
        window: root,
      });
    };
    if (root.document.readyState === "loading") {
      root.document.addEventListener("DOMContentLoaded", mount, {once: true});
    } else {
      mount();
    }
  }
})(globalThis, function createDashboardShellApi() {
  "use strict";

  const tabs = new Map([
    ["overview", "dashboard-overview"],
    ["alerts", "dashboard-alerts"],
    ["analytics", "dashboard-analytics"],
    ["system", "dashboard-system"],
  ]);
  const alertSources = new Set(["all", "guardian", "environment", "system"]);
  const alertStates = new Set(["all", "open", "recovered"]);
  const incidentIdPattern = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
  const unavailableCode = "DASHBOARD_DATA_UNAVAILABLE";

  function defaultHashSelection() {
    return {tab: "overview", alertId: null, environmentIncidentId: null};
  }

  function decodeHashPart(value) {
    return decodeURIComponent(value.replace(/\+/g, " "));
  }

  function validAlertId(value) {
    return typeof value === "string" && value.length > 0 && value.length <= 160 &&
      !/[\u0000-\u001f\u007f]/.test(value);
  }

  function parseDashboardHash(hash) {
    if (typeof hash !== "string") return defaultHashSelection();
    const values = new Map();
    try {
      const source = hash.startsWith("#") ? hash.slice(1) : hash;
      if (source.length === 0) return defaultHashSelection();
      for (const pair of source.split("&")) {
        const separator = pair.indexOf("=");
        const rawKey = separator === -1 ? pair : pair.slice(0, separator);
        const rawValue = separator === -1 ? "" : pair.slice(separator + 1);
        const key = decodeHashPart(rawKey);
        const value = decodeHashPart(rawValue);
        if (!["tab", "alert", "environment-incident"].includes(key)) continue;
        if (values.has(key)) return defaultHashSelection();
        values.set(key, value);
      }
    } catch (_error) {
      return defaultHashSelection();
    }

    const incidentId = values.get("environment-incident");
    if (incidentIdPattern.test(incidentId ?? "")) {
      return {
        tab: "alerts",
        alertId: `environment:${incidentId}`,
        environmentIncidentId: incidentId,
      };
    }

    const tab = tabs.has(values.get("tab")) ? values.get("tab") : "overview";
    const alertId = tab === "alerts" && validAlertId(values.get("alert"))
      ? values.get("alert") : null;
    return {tab, alertId, environmentIncidentId: null};
  }

  function replaceHash(history, location, hash) {
    if (!history || typeof history.replaceState !== "function") return;
    history.replaceState(null, "", hash);
    if (location && location.hash !== hash) location.hash = hash;
  }

  function selectTab(document, tab, options = {}) {
    if (!tabs.has(tab)) throw new TypeError("closed dashboard tab required");
    for (const [name, panelId] of tabs) {
      const button = document.getElementById(`tab-${name}`);
      const panel = document.getElementById(panelId);
      const selected = name === tab;
      if (button) {
        button.setAttribute("aria-selected", String(selected));
        button.tabIndex = selected ? 0 : -1;
      }
      if (panel) panel.hidden = !selected;
    }
    const selectedButton = document.getElementById(`tab-${tab}`);
    if (options.focus && selectedButton && typeof selectedButton.focus === "function") {
      selectedButton.focus();
    }
    if (options.writeHash !== false) {
      replaceHash(
        options.history,
        options.location,
        options.hash ?? `#tab=${tab}`,
      );
    }
    if (tab === "analytics" && typeof options.analyticsController?.activate === "function") {
      try {
        const activation = options.analyticsController.activate();
        if (activation && typeof activation.catch === "function") activation.catch(() => {});
      } catch (_error) {
        // Analytics degrades independently from navigation.
      }
    }
    return tab;
  }

  function createResourceController(environment) {
    const state = {
      generation: 0,
      inFlight: null,
      lastPayload: null,
      lastSuccessAt: null,
    };

    function invalidate() {
      state.generation += 1;
      state.inFlight = null;
    }

    function refresh() {
      if (state.inFlight !== null) return state.inFlight;
      const generation = state.generation + 1;
      state.generation = generation;
      const request = (async () => {
        try {
          const response = await environment.fetch(environment.url);
          if (!response || response.ok !== true) throw new TypeError(unavailableCode);
          const payload = await response.json();
          if (generation !== state.generation) return {ok: false, superseded: true};
          const renderOptions = typeof environment.renderOptions === "function"
            ? environment.renderOptions() : environment.renderOptions;
          const rendered = environment.render(environment.document, payload, renderOptions);
          if (generation !== state.generation) return {ok: false, superseded: true};
          state.lastPayload = payload;
          state.lastSuccessAt = (environment.now ?? (() => new Date()))();
          if (typeof environment.onSuccess === "function") {
            environment.onSuccess(payload, rendered);
          }
          return {ok: true, payload};
        } catch (_error) {
          if (generation === state.generation) {
            if (state.lastPayload === null) {
              environment.markUnavailable(environment.document, environment.section);
            } else {
              environment.markStale(
                environment.document,
                environment.section,
                state.lastSuccessAt,
                environment.staleOptions,
              );
            }
          }
          return {ok: false, error: unavailableCode};
        } finally {
          if (generation === state.generation) state.inFlight = null;
        }
      })();
      state.inFlight = request;
      return request;
    }

    return {invalidate, refresh, state};
  }

  function alertSignature(payload) {
    return JSON.stringify(payload.alerts.map((alert) => [
      alert.alert_id,
      alert.source,
      alert.kind,
      alert.state,
      alert.priority,
      alert.reason_codes,
      alert.adult_intervention_count,
      alert.evidence_state,
      alert.notification_state,
      alert.resolution_cause,
    ]));
  }

  function mountDashboardShell(environment) {
    const document = environment.document;
    const window = environment.window;
    const views = environment.views;
    if (!document || !window || !views || typeof environment.fetch !== "function" ||
        typeof environment.setInterval !== "function" ||
        typeof environment.clearInterval !== "function") {
      return null;
    }

    const parsed = parseDashboardHash(window.location?.hash ?? "");
    let sourceFilter = "all";
    let stateFilter = "all";
    let highlightAlertId = parsed.alertId;
    let pendingAlertId = parsed.alertId;
    let alertSemanticSignature = null;
    let announcementRevision = 0;
    let timerId = null;
    let paused = Boolean(document.hidden);

    const selectionOptions = (extra = {}) => ({
      analyticsController: environment.analyticsController,
      history: window.history,
      location: window.location,
      ...extra,
    });

    function focusPendingAlert() {
      if (pendingAlertId === null) return false;
      const list = document.getElementById("alerts-list");
      if (!list) return false;
      const row = Array.from(list.children).find(
        (candidate) => candidate.dataset?.alertId === pendingAlertId,
      );
      if (!row) return false;
      row.classList?.add("is-target");
      row.setAttribute?.("tabindex", "-1");
      if (typeof row.focus === "function") row.focus();
      pendingAlertId = null;
      return true;
    }

    function renderAlerts(documentObject, payload) {
      const rendered = views.renderAlerts(documentObject, payload, {
        dateFormatter: environment.dateFormatter,
        highlightAlertId,
        sourceFilter,
        stateFilter,
      });
      const signature = alertSignature(payload);
      if (signature !== alertSemanticSignature) {
        alertSemanticSignature = signature;
        announcementRevision += 1;
        const announcement = documentObject.getElementById("alerts-announcement");
        if (announcement) {
          announcement.textContent = `警报内容已更新（${announcementRevision}）：${rendered.alerts.length} 项`;
        }
      }
      focusPendingAlert();
      return rendered;
    }

    const common = {
      document,
      fetch: environment.fetch,
      markStale: views.markStale,
      markUnavailable: views.markUnavailable,
      now: environment.now,
      staleOptions: {dateFormatter: environment.dateFormatter},
    };
    const controllers = {
      overview: createResourceController({
        ...common,
        render: views.renderOverview,
        renderOptions: {dateFormatter: environment.dateFormatter},
        section: "overview",
        url: "/api/dashboard/overview",
      }),
      alerts: createResourceController({
        ...common,
        render: renderAlerts,
        section: "alerts",
        url: "/api/dashboard/alerts",
      }),
      system: createResourceController({
        ...common,
        render: views.renderSystem,
        renderOptions: {dateFormatter: environment.dateFormatter},
        section: "system",
        url: "/api/dashboard/system",
      }),
    };

    function refreshAll() {
      return Promise.all([
        controllers.overview.refresh(),
        controllers.alerts.refresh(),
        controllers.system.refresh(),
      ]);
    }

    function startTimer() {
      if (timerId !== null || document.hidden) return;
      timerId = environment.setInterval(refreshAll, 15000);
    }

    function stopTimer() {
      if (timerId === null) return;
      environment.clearInterval(timerId);
      timerId = null;
    }

    function pause() {
      paused = true;
      stopTimer();
      for (const controller of Object.values(controllers)) controller.invalidate();
    }

    function resume() {
      if (!paused || document.hidden) return null;
      paused = false;
      const refreshed = refreshAll();
      startTimer();
      return refreshed;
    }

    const tabNames = [...tabs.keys()];
    for (const [index, tab] of tabNames.entries()) {
      const button = document.getElementById(`tab-${tab}`);
      if (!button) continue;
      button.addEventListener("click", () => {
        selectTab(document, tab, selectionOptions());
      });
      button.addEventListener("keydown", (event) => {
        let nextIndex = null;
        if (event.key === "ArrowRight") nextIndex = (index + 1) % tabNames.length;
        if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabNames.length) % tabNames.length;
        if (event.key === "Home") nextIndex = 0;
        if (event.key === "End") nextIndex = tabNames.length - 1;
        if (nextIndex === null) return;
        event.preventDefault();
        selectTab(document, tabNames[nextIndex], selectionOptions({focus: true}));
      });
    }

    for (const button of document.querySelectorAll("[data-alert-source]")) {
      button.addEventListener("click", () => {
        const next = button.dataset.alertSource;
        if (!alertSources.has(next)) return;
        sourceFilter = next;
        for (const candidate of document.querySelectorAll("[data-alert-source]")) {
          candidate.setAttribute("aria-pressed", String(candidate.dataset.alertSource === sourceFilter));
        }
        views.applyAlertFilters(document, sourceFilter, stateFilter);
      });
    }
    for (const button of document.querySelectorAll("[data-alert-state]")) {
      button.addEventListener("click", () => {
        const next = button.dataset.alertState;
        if (!alertStates.has(next)) return;
        stateFilter = next;
        for (const candidate of document.querySelectorAll("[data-alert-state]")) {
          candidate.setAttribute("aria-pressed", String(candidate.dataset.alertState === stateFilter));
        }
        views.applyAlertFilters(document, sourceFilter, stateFilter);
      });
    }

    const attention = document.getElementById("global-attention");
    if (attention) {
      attention.addEventListener("click", (event) => {
        const alertId = event.target?.dataset?.alertTarget;
        if (!validAlertId(alertId)) return;
        highlightAlertId = alertId;
        pendingAlertId = alertId;
        selectTab(document, "alerts", selectionOptions({
          hash: `#tab=alerts&alert=${encodeURIComponent(alertId)}`,
        }));
        if (controllers.alerts.state.lastPayload !== null) {
          renderAlerts(document, controllers.alerts.state.lastPayload);
        }
      });
    }

    const systemRefresh = document.getElementById("system-refresh");
    if (systemRefresh) {
      systemRefresh.addEventListener("click", () => controllers.system.refresh());
    }

    const notify = document.getElementById("notify");
    if (notify) {
      notify.addEventListener("click", async () => {
        let success = false;
        try {
          const response = await environment.fetch("/api/test-notification", {method: "POST"});
          success = response?.ok === true;
        } catch (_error) {
          success = false;
        }
        if (typeof window.alert === "function") {
          window.alert(success ? "测试通知已发送" : "测试通知不可用");
        }
      });
    }

    window.addEventListener("pagehide", pause);
    window.addEventListener("pageshow", (event) => {
      if (event.persisted) resume();
    });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) pause();
      else resume();
    });

    selectTab(document, parsed.tab, selectionOptions({
      writeHash: parsed.alertId === null,
    }));
    const initialRefresh = refreshAll();
    startTimer();

    return {
      controllers,
      initialRefresh,
      refresh: refreshAll,
      selectTab: (tab, options = {}) => selectTab(document, tab, selectionOptions(options)),
    };
  }

  return {
    createResourceController,
    mountDashboardShell,
    parseDashboardHash,
    selectTab,
  };
});
