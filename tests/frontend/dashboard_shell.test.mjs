import assert from "node:assert/strict";
import {createRequire} from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const views = require("../../apps/api/dashboard_views.js");
const {
  createResourceController,
  mountDashboardShell,
  parseDashboardHash,
  selectTab,
} = require("../../apps/api/dashboard_shell.js");


class FakeEventTarget {
  constructor() {
    this.listeners = new Map();
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  dispatch(type, event = {}) {
    const payload = {
      preventDefault() {},
      ...event,
      currentTarget: this,
      target: event.target ?? this,
    };
    return (this.listeners.get(type) ?? []).map((listener) => listener(payload));
  }
}


class FakeClassList {
  constructor(element) {
    this.element = element;
  }

  values() {
    return new Set(this.element.className.split(/\s+/).filter(Boolean));
  }

  add(...names) {
    const values = this.values();
    for (const name of names) values.add(name);
    this.element.className = [...values].join(" ");
  }

  remove(...names) {
    const values = this.values();
    for (const name of names) values.delete(name);
    this.element.className = [...values].join(" ");
  }

  contains(name) {
    return this.values().has(name);
  }

  toggle(name, enabled) {
    if (enabled) this.add(name);
    else this.remove(name);
  }
}


class FakeElement extends FakeEventTarget {
  constructor(document, id = "", {dataset = {}, tagName = "div"} = {}) {
    super();
    this.document = document;
    this.id = id;
    this.tagName = tagName;
    this.dataset = {...dataset};
    this.children = [];
    this.attributes = new Map();
    this.className = "";
    this.classList = new FakeClassList(this);
    this.hidden = false;
    this.tabIndex = -1;
    this.textWrites = 0;
    this._textContent = "";
  }

  get textContent() {
    return this._textContent;
  }

  set textContent(value) {
    this._textContent = String(value);
    this.textWrites += 1;
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
    this._textContent = "";
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "tabindex") this.tabIndex = Number(value);
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  focus() {
    if (this.hidden) return false;
    if (this.dataset.alertId && this.document.getElementById("dashboard-alerts").hidden) {
      return false;
    }
    const naturallyFocusable = new Set(["button", "a", "input", "select", "textarea"]);
    if (!naturallyFocusable.has(this.tagName) && this.getAttribute("tabindex") === null) {
      return false;
    }
    this.document.activeElement = this;
    return true;
  }
}


class FakeDocument extends FakeEventTarget {
  constructor() {
    super();
    this.activeElement = null;
    this.hidden = false;
    this.elements = new Map();
    this.sourceButtons = ["all", "guardian", "environment", "system"].map(
      (source) => this.add(`source-${source}`, {dataset: {alertSource: source}, tagName: "button"}),
    );
    this.stateButtons = ["all", "open", "recovered"].map(
      (state) => this.add(`state-${state}`, {dataset: {alertState: state}, tagName: "button"}),
    );
    for (const button of [...this.sourceButtons, ...this.stateButtons]) {
      button.setAttribute("aria-pressed", String(button.dataset.alertSource === "all" || button.dataset.alertState === "all"));
    }
    for (const tab of ["overview", "alerts", "analytics", "system"]) {
      const button = this.add(`tab-${tab}`, {tagName: "button"});
      button.setAttribute("aria-controls", `dashboard-${tab}`);
      button.setAttribute("aria-selected", String(tab === "overview"));
      button.tabIndex = tab === "overview" ? 0 : -1;
      const panel = this.add(`dashboard-${tab}`, {tagName: "section"});
      panel.hidden = tab !== "overview";
    }
    for (const id of [
      "live-image", "global-attention", "alert-count", "dashboard-health",
      "environment-current", "environment-detail", "environment-last-valid",
      "overview-components", "overview-recent", "overview-updated", "overview-stale",
      "alerts-list", "alerts-announcement", "alerts-updated", "alerts-stale",
      "system-components", "system-refresh", "system-updated", "system-stale", "notify",
    ]) {
      this.add(id);
    }
    for (const section of ["overview", "alerts", "system"]) {
      this.getElementById(`${section}-stale`).hidden = true;
    }
  }

  add(id, options = {}) {
    const element = new FakeElement(this, id, options);
    this.elements.set(id, element);
    return element;
  }

  getElementById(id) {
    return this.elements.get(id) ?? null;
  }

  createElement(tagName) {
    return new FakeElement(this, "", {tagName});
  }

  querySelectorAll(selector) {
    if (selector === "[data-alert-source]") return this.sourceButtons;
    if (selector === "[data-alert-state]") return this.stateButtons;
    return [];
  }
}


class FakeWindow extends FakeEventTarget {
  constructor(hash = "") {
    super();
    this.location = {hash};
    this.replacedHashes = [];
    this.alerts = [];
    this.history = {
      replaceState: (_state, _title, url) => {
        const hashIndex = url.indexOf("#");
        this.location.hash = hashIndex === -1 ? "" : url.slice(hashIndex);
        this.replacedHashes.push(this.location.hash);
      },
    };
  }

  alert(message) {
    this.alerts.push(message);
  }
}


function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return {promise, reject, resolve};
}


function response(payload) {
  return {ok: true, json: async () => payload};
}


function closedAlert(alertId = "guardian:event-1", overrides = {}) {
  return {
    adult_intervention_count: 0,
    alert_id: alertId,
    evidence_state: "collecting",
    kind: alertId.startsWith("environment:") ? "environment_range" : "face_not_visible",
    notification_state: "pending",
    opened_at: "2026-09-03T00:55:00Z",
    priority: "critical",
    reason_codes: alertId.startsWith("environment:") ? ["temperature_high"] : ["occluded"],
    recovered_at: null,
    resolution_cause: null,
    source: alertId.startsWith("environment:") ? "environment" : "guardian",
    state: "open",
    updated_at: "2026-09-03T01:00:00Z",
    ...overrides,
  };
}


function overviewPayload(alert = null, generatedAt = "2026-09-03T01:00:00Z") {
  return {
    schema_version: 1,
    generated_at: generatedAt,
    attention: alert === null ? null : {alert, additional_open_count: 0},
    open_alert_count: alert === null ? 0 : 1,
    guardian_open_count: alert?.source === "guardian" ? 1 : 0,
    today_recovered_count: 0,
    environment: {
      state: "unavailable",
      temperature_c: null,
      humidity_rh: null,
      captured_at: null,
      fresh_until: null,
      failure_reason: "environment_no_reading",
      last_valid_temperature_c: null,
      last_valid_humidity_rh: null,
      last_valid_captured_at: null,
    },
    components: [],
    recent_activity: [],
  };
}


function alertsPayload(alerts = [], generatedAt = "2026-09-03T01:00:00Z") {
  return {schema_version: 1, generated_at: generatedAt, alerts};
}


function systemPayload(generatedAt = "2026-09-03T01:00:00Z") {
  return {schema_version: 1, generated_at: generatedAt, components: []};
}


function mountFixture({
  alertPayload = alertsPayload(),
  fetch: suppliedFetch = null,
  hash = "",
  hidden = false,
  overview = overviewPayload(),
  system = systemPayload(),
  analytics = null,
  analyticsController = {activate() {}},
} = {}) {
  const document = new FakeDocument();
  document.hidden = hidden;
  const window = new FakeWindow(hash);
  const calls = [];
  const timers = [];
  const cleared = [];
  const payloads = new Map([
    ["/api/dashboard/overview", overview],
    ["/api/dashboard/alerts", alertPayload],
    ["/api/dashboard/system", system],
  ]);
  const fetch = suppliedFetch ?? (async (url, options) => {
    calls.push({url, options});
    return response(payloads.get(url));
  });
  const environment = {
    analytics,
    analyticsController,
    clearInterval(id) {
      cleared.push(id);
    },
    dateFormatter: {format: (date) => date.toISOString()},
    document,
    fetch: async (url, options) => {
      if (suppliedFetch) calls.push({url, options});
      return fetch(url, options);
    },
    now: () => new Date("2026-09-03T01:00:30Z"),
    setInterval(callback, milliseconds) {
      const timer = {callback, id: timers.length + 1, milliseconds};
      timers.push(timer);
      return timer.id;
    },
    views,
    window,
  };
  const shell = mountDashboardShell(environment);
  return {calls, cleared, document, environment, shell, timers, window};
}


async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}


test("hash parser accepts only closed tab, alert, and legacy incident mappings", () => {
  assert.deepEqual(parseDashboardHash("#tab=alerts&alert=guardian:event-1"), {
    tab: "alerts",
    alertId: "guardian:event-1",
    environmentIncidentId: null,
  });
  assert.deepEqual(parseDashboardHash("#environment-incident=incident-1"), {
    tab: "alerts",
    alertId: "environment:incident-1",
    environmentIncidentId: "incident-1",
  });
  assert.deepEqual(parseDashboardHash("#tab=unknown"), {
    tab: "overview",
    alertId: null,
    environmentIncidentId: null,
  });
  assert.deepEqual(parseDashboardHash("#tab=alerts&alert=%E0%A4%A"), {
    tab: "overview",
    alertId: null,
    environmentIncidentId: null,
  });
  assert.equal(parseDashboardHash(`#tab=alerts&alert=${"a".repeat(161)}`).alertId, null);
  assert.equal(parseDashboardHash("#environment-incident=bad%2Fpath").alertId, null);
  assert.equal(parseDashboardHash(`#environment-incident=${"a".repeat(129)}`).alertId, null);
});


test("tab clicks and roving keyboard focus select four panels without replacing live media", async () => {
  const activations = [];
  const fixture = mountFixture({analyticsController: {activate: () => activations.push("analytics")}});
  const {document, shell, window} = fixture;
  const liveImage = document.getElementById("live-image");
  await shell.initialRefresh;

  document.getElementById("tab-alerts").dispatch("click");
  assert.equal(document.getElementById("tab-alerts").getAttribute("aria-selected"), "true");
  assert.equal(document.getElementById("tab-alerts").tabIndex, 0);
  assert.equal(document.getElementById("dashboard-alerts").hidden, false);
  assert.equal(document.getElementById("dashboard-overview").hidden, true);
  assert.equal(document.activeElement, null);
  assert.equal(window.location.hash, "#tab=alerts");

  document.getElementById("tab-alerts").dispatch("keydown", {key: "ArrowRight"});
  assert.equal(document.activeElement, document.getElementById("tab-analytics"));
  assert.equal(window.location.hash, "#tab=analytics");
  assert.deepEqual(activations, ["analytics"]);

  document.getElementById("tab-analytics").dispatch("keydown", {key: "ArrowLeft"});
  assert.equal(document.activeElement, document.getElementById("tab-alerts"));
  document.getElementById("tab-alerts").dispatch("keydown", {key: "Home"});
  assert.equal(document.activeElement, document.getElementById("tab-overview"));
  document.getElementById("tab-overview").dispatch("keydown", {key: "End"});
  assert.equal(document.activeElement, document.getElementById("tab-system"));
  assert.equal(window.location.hash, "#tab=system");
  assert.equal(document.getElementById("live-image"), liveImage);

  selectTab(document, "overview", {history: window.history, location: window.location});
  assert.equal(document.getElementById("dashboard-overview").hidden, false);
  assert.equal(document.getElementById("live-image"), liveImage);
});


test("mount makes three immediate fixed requests and one deduplicated fifteen-second schedule", async () => {
  const pending = new Map([
    ["/api/dashboard/overview", deferred()],
    ["/api/dashboard/alerts", deferred()],
    ["/api/dashboard/system", deferred()],
  ]);
  const fixture = mountFixture({fetch: (url) => pending.get(url).promise});

  assert.deepEqual(fixture.calls.map((call) => call.url), [
    "/api/dashboard/overview",
    "/api/dashboard/alerts",
    "/api/dashboard/system",
  ]);
  assert.deepEqual(fixture.timers.map((timer) => timer.milliseconds), [15000]);

  const tick = fixture.timers[0].callback();
  assert.equal(fixture.calls.length, 3);
  pending.get("/api/dashboard/overview").resolve(response(overviewPayload()));
  pending.get("/api/dashboard/alerts").resolve(response(alertsPayload()));
  pending.get("/api/dashboard/system").resolve(response(systemPayload()));
  await Promise.all([fixture.shell.initialRefresh, tick]);
  assert.equal(fixture.calls.length, 3);
});


test("resource controller deduplicates in flight work and discards a superseded late generation", async () => {
  const document = new FakeDocument();
  const first = deferred();
  const second = deferred();
  const requests = [first, second];
  const rendered = [];
  const controller = createResourceController({
    document,
    fetch: () => requests.shift().promise,
    markStale: views.markStale,
    markUnavailable: views.markUnavailable,
    now: () => new Date("2026-09-03T01:00:30Z"),
    render: (_document, payload) => rendered.push(payload.value),
    section: "overview",
    url: "/api/dashboard/overview",
  });

  const oldRequest = controller.refresh();
  assert.equal(controller.refresh(), oldRequest);
  controller.invalidate();
  const newRequest = controller.refresh();
  second.resolve(response({value: "new"}));
  await newRequest;
  first.resolve(response({value: "old"}));
  await oldRequest;

  assert.deepEqual(rendered, ["new"]);
  assert.equal(controller.state.lastPayload.value, "new");
});


test("first resource failure is unavailable and later failure marks retained content stale", async () => {
  const document = new FakeDocument();
  const rendered = {current: null};
  const unavailable = [];
  const stale = [];
  const results = [
    Promise.reject(new Error("private first failure")),
    Promise.resolve(response({value: "kept"})),
    Promise.reject(new Error("private later failure")),
  ];
  const controller = createResourceController({
    document,
    fetch: () => results.shift(),
    markStale: (...args) => stale.push(args),
    markUnavailable: (...args) => unavailable.push(args),
    now: () => new Date("2026-09-03T01:00:30Z"),
    render: (_document, payload) => {
      rendered.current = payload;
      return payload;
    },
    section: "overview",
    url: "/api/dashboard/overview",
  });

  assert.deepEqual(await controller.refresh(), {ok: false, error: "DASHBOARD_DATA_UNAVAILABLE"});
  assert.equal(unavailable.length, 1);
  assert.equal(stale.length, 0);
  await controller.refresh();
  const retained = rendered.current;
  assert.deepEqual(await controller.refresh(), {ok: false, error: "DASHBOARD_DATA_UNAVAILABLE"});

  assert.equal(rendered.current, retained);
  assert.equal(unavailable.length, 1);
  assert.equal(stale.length, 1);
  assert.equal(stale[0][1], "overview");
  assert.equal(stale[0][2].toISOString(), "2026-09-03T01:00:30.000Z");
  assert.doesNotMatch(stale[0].slice(1).map(String).join(" "), /private/);
});


test("alert announcements ignore display timestamps but include closed semantic state", async () => {
  let generation = 0;
  const alert = closedAlert();
  const fixture = mountFixture({fetch: async (url) => {
    if (url === "/api/dashboard/alerts") {
      generation += 1;
      if (generation === 1) return response(alertsPayload([alert], "2026-09-03T01:00:00Z"));
      if (generation === 2) return response(alertsPayload([
        {...alert, updated_at: "2026-09-03T01:00:15Z"},
      ], "2026-09-03T01:00:15Z"));
      return response(alertsPayload([
        closedAlert(undefined, {
          evidence_state: "ready",
          notification_state: "delivered",
          priority: "info",
          recovered_at: "2026-09-03T01:00:20Z",
          resolution_cause: "explicit_safe",
          state: "recovered",
          updated_at: "2026-09-03T01:00:20Z",
        }),
      ], "2026-09-03T01:00:30Z"));
    }
    if (url === "/api/dashboard/overview") return response(overviewPayload());
    return response(systemPayload());
  }});
  await fixture.shell.initialRefresh;
  const announcement = fixture.document.getElementById("alerts-announcement");
  const initialText = announcement.textContent;
  const initialWrites = announcement.textWrites;

  await fixture.timers[0].callback();
  assert.equal(announcement.textContent, initialText);
  assert.equal(announcement.textWrites, initialWrites);

  await fixture.timers[0].callback();
  assert.notEqual(announcement.textContent, initialText);
  assert.equal(announcement.textWrites, initialWrites + 1);
});


test("every closed alert semantic field and server order independently triggers an announcement", async (context) => {
  const first = closedAlert("guardian:matrix-a", {
    recovered_at: "2026-09-03T01:00:00Z",
    state: "recovered",
  });
  const second = closedAlert("guardian:matrix-b", {
    recovered_at: "2026-09-03T01:00:00Z",
    state: "recovered",
  });
  const cases = [
    ["id", () => [{...first, alert_id: "guardian:matrix-changed"}, second]],
    ["source", () => [{...first, source: "environment"}, second]],
    ["kind", () => [{...first, kind: "prone_candidate"}, second]],
    ["state", () => [{...first, recovered_at: null, state: "open"}, second]],
    ["priority", () => [{...first, priority: "warning"}, second]],
    ["reasons", () => [{...first, reason_codes: ["too_dark"]}, second]],
    ["intervention count", () => [{...first, adult_intervention_count: 1}, second]],
    ["evidence", () => [{...first, evidence_state: "ready"}, second]],
    ["notification", () => [{...first, notification_state: "delivered"}, second]],
    ["resolution", () => [{...first, resolution_cause: "explicit_safe"}, second]],
    ["server order", () => [second, first]],
  ];

  for (const [name, changedAlerts] of cases) {
    await context.test(name, async () => {
      let alertsGeneration = 0;
      const fixture = mountFixture({fetch: async (url) => {
        if (url === "/api/dashboard/alerts") {
          alertsGeneration += 1;
          return response(alertsPayload(
            alertsGeneration === 1 ? [first, second] : changedAlerts(),
            alertsGeneration === 1 ? "2026-09-03T01:00:00Z" : "2026-09-03T01:00:15Z",
          ));
        }
        if (url === "/api/dashboard/overview") return response(overviewPayload());
        return response(systemPayload());
      }});
      await fixture.shell.initialRefresh;
      const announcement = fixture.document.getElementById("alerts-announcement");
      const initialWrites = announcement.textWrites;

      await fixture.timers[0].callback();

      assert.equal(announcement.textWrites, initialWrites + 1);
    });
  }
});


test("every closed alert filter avoids fetch and preserves selection and server order", async () => {
  const orderedAlerts = [
    closedAlert("guardian:open"),
    closedAlert("environment:recovered", {
      recovered_at: "2026-09-03T01:00:00Z",
      state: "recovered",
    }),
    closedAlert("system:recovered", {
      kind: "camera_status",
      priority: "warning",
      reason_codes: ["camera_offline"],
      recovered_at: "2026-09-03T01:00:00Z",
      source: "system",
      state: "recovered",
    }),
  ];
  let alertGeneration = 0;
  const fixture = mountFixture({fetch: async (url) => {
    if (url === "/api/dashboard/alerts") {
      alertGeneration += 1;
      return response(alertsPayload(
        orderedAlerts,
        alertGeneration === 1 ? "2026-09-03T01:00:00Z" : "2026-09-03T01:00:15Z",
      ));
    }
    if (url === "/api/dashboard/overview") return response(overviewPayload());
    return response(systemPayload());
  }});
  await fixture.shell.initialRefresh;
  const initialCalls = fixture.calls.length;
  const alertIds = () => fixture.document.getElementById("alerts-list").children.map(
    (row) => row.dataset.alertId,
  );

  for (const button of fixture.document.sourceButtons) {
    button.dispatch("click");
    assert.equal(fixture.calls.length, initialCalls);
    assert.deepEqual(alertIds(), orderedAlerts.map((alert) => alert.alert_id));
    for (const candidate of fixture.document.sourceButtons) {
      assert.equal(
        candidate.getAttribute("aria-pressed"),
        String(candidate === button),
      );
    }
  }
  for (const button of fixture.document.stateButtons) {
    button.dispatch("click");
    assert.equal(fixture.calls.length, initialCalls);
    assert.deepEqual(alertIds(), orderedAlerts.map((alert) => alert.alert_id));
    for (const candidate of fixture.document.stateButtons) {
      assert.equal(
        candidate.getAttribute("aria-pressed"),
        String(candidate === button),
      );
    }
  }

  await fixture.timers[0].callback();
  assert.equal(fixture.document.sourceButtons.at(-1).getAttribute("aria-pressed"), "true");
  assert.equal(fixture.document.stateButtons.at(-1).getAttribute("aria-pressed"), "true");
  assert.deepEqual(alertIds(), orderedAlerts.map((alert) => alert.alert_id));
});


test("scheduler never activates analytics and lifecycle restores only one timer with one refresh", async () => {
  const activations = [];
  const fixture = mountFixture({analyticsController: {activate: () => activations.push("analytics")}});
  await fixture.shell.initialRefresh;
  fixture.document.getElementById("tab-analytics").dispatch("click");
  assert.deepEqual(activations, ["analytics"]);

  await fixture.timers[0].callback();
  assert.deepEqual(activations, ["analytics"]);
  const callsAfterTick = fixture.calls.length;

  fixture.window.dispatch("pagehide", {persisted: true});
  assert.deepEqual(fixture.cleared, [1]);
  fixture.window.dispatch("pageshow", {persisted: false});
  assert.equal(fixture.timers.length, 1);
  fixture.window.dispatch("pageshow", {persisted: true});
  await settle();
  assert.equal(fixture.timers.length, 2);
  assert.equal(fixture.calls.length, callsAfterTick + 3);

  fixture.document.hidden = true;
  fixture.document.dispatch("visibilitychange");
  assert.deepEqual(fixture.cleared, [1, 2]);
  fixture.document.hidden = false;
  fixture.document.dispatch("visibilitychange");
  await settle();
  assert.equal(fixture.timers.length, 3);
  assert.equal(fixture.calls.length, callsAfterTick + 6);
  fixture.document.dispatch("visibilitychange");
  assert.equal(fixture.timers.length, 3);
});


test("shell mounts one lazy analytics controller that remains outside interval refresh", async () => {
  const mounts = [];
  const activations = [];
  const refreshes = [];
  const analytics = {
    mountDashboardAnalytics(environment) {
      mounts.push(environment);
      return {
        activate() {
          activations.push("activate");
        },
        refresh() {
          refreshes.push("refresh");
        },
      };
    },
  };
  const fixture = mountFixture({analytics, analyticsController: null});
  await fixture.shell.initialRefresh;

  assert.equal(mounts.length, 1);
  assert.equal(mounts[0].document, fixture.document);
  assert.equal(typeof mounts[0].fetch, "function");
  assert.deepEqual(activations, []);
  assert.deepEqual(refreshes, []);

  fixture.document.getElementById("tab-analytics").dispatch("click");
  assert.deepEqual(activations, ["activate"]);
  await fixture.timers[0].callback();
  assert.deepEqual(activations, ["activate"]);
  assert.deepEqual(refreshes, []);
  assert.deepEqual(fixture.calls.map((call) => call.url), [
    "/api/dashboard/overview",
    "/api/dashboard/alerts",
    "/api/dashboard/system",
    "/api/dashboard/overview",
    "/api/dashboard/alerts",
    "/api/dashboard/system",
  ]);
});


test("hide and BFCache resume reuse pending resource requests before the next generation", async () => {
  const urls = [
    "/api/dashboard/overview",
    "/api/dashboard/alerts",
    "/api/dashboard/system",
  ];
  const first = new Map(urls.map((url) => [url, deferred()]));
  const second = new Map(urls.map((url) => [url, deferred()]));
  const active = new Map(urls.map((url) => [url, 0]));
  const maximumActive = new Map(urls.map((url) => [url, 0]));
  const generation = new Map(urls.map((url) => [url, 0]));
  const fixture = mountFixture({fetch: (url) => {
    const nextGeneration = generation.get(url) + 1;
    generation.set(url, nextGeneration);
    const activeCount = active.get(url) + 1;
    active.set(url, activeCount);
    maximumActive.set(url, Math.max(maximumActive.get(url), activeCount));
    const request = nextGeneration === 1 ? first.get(url) : second.get(url);
    return request.promise.finally(() => active.set(url, active.get(url) - 1));
  }});

  fixture.document.hidden = true;
  fixture.document.dispatch("visibilitychange");
  fixture.window.dispatch("pagehide", {persisted: true});
  fixture.document.hidden = false;
  fixture.window.dispatch("pageshow", {persisted: true});

  assert.equal(fixture.calls.length, 3);
  assert.deepEqual(Object.fromEntries(maximumActive), Object.fromEntries(urls.map((url) => [url, 1])));
  assert.equal(fixture.timers.length, 2);

  first.get("/api/dashboard/overview").resolve(response(overviewPayload()));
  first.get("/api/dashboard/alerts").resolve(response(alertsPayload()));
  first.get("/api/dashboard/system").resolve(response(systemPayload()));
  await fixture.shell.initialRefresh;
  assert.deepEqual(Object.fromEntries(active), Object.fromEntries(urls.map((url) => [url, 0])));

  const nextTick = fixture.timers.at(-1).callback();
  assert.equal(fixture.calls.length, 6);
  assert.deepEqual(Object.fromEntries(maximumActive), Object.fromEntries(urls.map((url) => [url, 1])));
  second.get("/api/dashboard/overview").resolve(response(overviewPayload(null, "2026-09-03T01:01:00Z")));
  second.get("/api/dashboard/alerts").resolve(response(alertsPayload([], "2026-09-03T01:01:00Z")));
  second.get("/api/dashboard/system").resolve(response(systemPayload("2026-09-03T01:01:00Z")));
  await nextTick;

  assert.equal(fixture.shell.controllers.overview.state.generation, 2);
  assert.equal(fixture.shell.controllers.overview.state.lastPayload.generated_at, "2026-09-03T01:01:00Z");
  assert.deepEqual(Object.fromEntries(active), Object.fromEntries(urls.map((url) => [url, 0])));
});


test("an initially hidden page restores one scheduler and refresh when it becomes visible", async () => {
  const fixture = mountFixture({hidden: true});
  await fixture.shell.initialRefresh;
  assert.equal(fixture.timers.length, 0);
  const initialCalls = fixture.calls.length;

  fixture.document.hidden = false;
  fixture.document.dispatch("visibilitychange");
  await settle();

  assert.equal(fixture.timers.length, 1);
  assert.equal(fixture.calls.length, initialCalls + 3);
});


test("pending attention target focuses one exact alert while filters persist and system refresh stays fixed", async () => {
  const target = closedAlert("guardian:event one");
  const other = closedAlert("guardian:event-one-more", {priority: "warning"});
  const alertsFirst = deferred();
  let alertsGeneration = 0;
  const fixture = mountFixture({fetch: async (url, options) => {
    if (url === "/api/dashboard/overview") return response(overviewPayload(target));
    if (url === "/api/dashboard/alerts") {
      alertsGeneration += 1;
      if (alertsGeneration === 1) return alertsFirst.promise;
      return response(alertsPayload([target, other], "2026-09-03T01:00:15Z"));
    }
    assert.equal(url, "/api/dashboard/system");
    assert.equal(options, undefined);
    return response(systemPayload());
  }});
  await settle();

  const attention = fixture.document.getElementById("global-attention");
  const attentionButton = attention.children[0];
  attention.dispatch("click", {target: attentionButton});
  assert.equal(fixture.window.location.hash, "#tab=alerts&alert=guardian%3Aevent%20one");
  assert.equal(fixture.document.getElementById("dashboard-alerts").hidden, false);

  alertsFirst.resolve(response(alertsPayload([target, other])));
  await fixture.shell.initialRefresh;
  const rows = fixture.document.getElementById("alerts-list").children;
  assert.equal(rows.length, 2);
  assert.equal(rows[0].dataset.alertId, "guardian:event one");
  assert.equal(rows[0].classList.contains("is-target"), true);
  assert.equal(rows[1].classList.contains("is-target"), false);
  assert.equal(fixture.document.activeElement, rows[0]);
  assert.equal(rows[0].getAttribute("tabindex"), "-1");

  const callCount = fixture.calls.length;
  fixture.document.sourceButtons[1].dispatch("click");
  fixture.document.stateButtons[2].dispatch("click");
  assert.equal(fixture.calls.length, callCount);
  assert.equal(fixture.document.sourceButtons[1].getAttribute("aria-pressed"), "true");
  assert.equal(fixture.document.stateButtons[2].getAttribute("aria-pressed"), "true");

  await fixture.timers[0].callback();
  assert.equal(fixture.document.sourceButtons[1].getAttribute("aria-pressed"), "true");
  assert.equal(fixture.document.stateButtons[2].getAttribute("aria-pressed"), "true");
  assert.equal(fixture.document.getElementById("alerts-list").children[0].hidden, true);

  const beforeManual = fixture.calls.map((call) => call.url);
  await Promise.all(fixture.document.getElementById("system-refresh").dispatch("click"));
  assert.deepEqual(
    fixture.calls.slice(beforeManual.length).map((call) => call.url),
    ["/api/dashboard/system"],
  );
  assert.equal(fixture.calls.some((call) => call.url.includes("guardian:event")), false);
});


test("attention clears incompatible filters so its exact alert becomes visible and focusable", async () => {
  const target = closedAlert("guardian:target");
  const fixture = mountFixture({
    alertPayload: alertsPayload([target]),
    overview: overviewPayload(target),
  });
  await fixture.shell.initialRefresh;
  const targetRow = fixture.document.getElementById("alerts-list").children[0];

  fixture.document.sourceButtons.find(
    (button) => button.dataset.alertSource === "environment",
  ).dispatch("click");
  fixture.document.stateButtons.find(
    (button) => button.dataset.alertState === "recovered",
  ).dispatch("click");
  assert.equal(targetRow.hidden, true);

  const attention = fixture.document.getElementById("global-attention");
  attention.dispatch("click", {target: attention.children[0]});
  const focusedRow = fixture.document.getElementById("alerts-list").children[0];

  assert.equal(focusedRow.hidden, false);
  assert.equal(focusedRow.classList.contains("is-target"), true);
  assert.equal(fixture.document.activeElement, focusedRow);
  assert.equal(fixture.document.sourceButtons[0].getAttribute("aria-pressed"), "true");
  assert.equal(fixture.document.stateButtons[0].getAttribute("aria-pressed"), "true");
});


test("a slow target stays pending while Alerts is hidden and focuses after returning", async () => {
  const target = closedAlert("guardian:slow-target");
  const pendingAlerts = deferred();
  const fixture = mountFixture({
    fetch: async (url) => {
      if (url === "/api/dashboard/alerts") return pendingAlerts.promise;
      if (url === "/api/dashboard/overview") return response(overviewPayload(target));
      return response(systemPayload());
    },
  });
  await settle();
  const attention = fixture.document.getElementById("global-attention");
  attention.dispatch("click", {target: attention.children[0]});
  fixture.document.getElementById("tab-system").dispatch("click");

  pendingAlerts.resolve(response(alertsPayload([target])));
  await fixture.shell.initialRefresh;
  const targetRow = fixture.document.getElementById("alerts-list").children[0];
  assert.equal(fixture.document.activeElement, null);
  assert.equal(fixture.document.getElementById("dashboard-alerts").hidden, true);

  fixture.document.getElementById("tab-alerts").dispatch("click");
  assert.equal(fixture.document.activeElement, targetRow);
  assert.equal(targetRow.classList.contains("is-target"), true);
});


test("an alert hash with a deferred response focuses only its exact row after mount", async () => {
  const target = closedAlert("guardian:hash-target");
  const pendingAlerts = deferred();
  const fixture = mountFixture({
    fetch: async (url) => {
      if (url === "/api/dashboard/alerts") return pendingAlerts.promise;
      if (url === "/api/dashboard/overview") return response(overviewPayload());
      return response(systemPayload());
    },
    hash: "#tab=alerts&alert=guardian%3Ahash-target",
  });
  assert.equal(fixture.document.activeElement, null);

  pendingAlerts.resolve(response(alertsPayload([
    closedAlert("guardian:hash-target-more"),
    target,
  ])));
  await fixture.shell.initialRefresh;
  const rows = fixture.document.getElementById("alerts-list").children;

  assert.equal(rows[0].classList.contains("is-target"), false);
  assert.equal(rows[1].classList.contains("is-target"), true);
  assert.equal(fixture.document.activeElement, rows[1]);
  assert.equal(fixture.window.location.hash, "#tab=alerts&alert=guardian%3Ahash-target");
});


test("legacy incident hash remains stable until an exact environment alert is rendered", async () => {
  const pendingAlerts = deferred();
  const fixture = mountFixture({
    fetch: async (url) => {
      if (url === "/api/dashboard/alerts") return pendingAlerts.promise;
      if (url === "/api/dashboard/overview") return response(overviewPayload());
      return response(systemPayload());
    },
    hash: "#environment-incident=incident-1",
  });
  assert.equal(fixture.window.location.hash, "#environment-incident=incident-1");
  assert.equal(fixture.document.getElementById("dashboard-alerts").hidden, false);

  pendingAlerts.resolve(response(alertsPayload([
    closedAlert("environment:incident-10"),
    closedAlert("environment:incident-1"),
  ])));
  await fixture.shell.initialRefresh;

  const rows = fixture.document.getElementById("alerts-list").children;
  assert.equal(rows[0].classList.contains("is-target"), false);
  assert.equal(rows[1].classList.contains("is-target"), true);
  assert.equal(fixture.document.activeElement, rows[1]);
  assert.equal(fixture.window.location.hash, "#environment-incident=incident-1");
  assert.deepEqual(fixture.calls.map((call) => call.url), [
    "/api/dashboard/overview",
    "/api/dashboard/alerts",
    "/api/dashboard/system",
  ]);
});


test("test notification uses one fixed endpoint and closed success or failure phrases", async () => {
  const outcomes = [
    {ok: true},
    {ok: false},
    Promise.reject(new Error("private notification failure")),
  ];
  const fixture = mountFixture({fetch: async (url, options) => {
    if (url === "/api/test-notification") {
      const outcome = outcomes.shift();
      return await outcome;
    }
    if (url === "/api/dashboard/overview") return response(overviewPayload());
    if (url === "/api/dashboard/alerts") return response(alertsPayload());
    return response(systemPayload());
  }});
  await fixture.shell.initialRefresh;

  const notify = fixture.document.getElementById("notify");
  await Promise.all(notify.dispatch("click"));
  await Promise.all(notify.dispatch("click"));
  await Promise.all(notify.dispatch("click"));

  assert.deepEqual(
    fixture.calls.filter((call) => call.url === "/api/test-notification"),
    [
      {url: "/api/test-notification", options: {method: "POST"}},
      {url: "/api/test-notification", options: {method: "POST"}},
      {url: "/api/test-notification", options: {method: "POST"}},
    ],
  );
  assert.deepEqual(fixture.window.alerts, [
    "测试通知已发送",
    "测试通知不可用",
    "测试通知不可用",
  ]);
  assert.doesNotMatch(fixture.window.alerts.join(" "), /private|ntfy/i);
});
