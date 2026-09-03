import assert from "node:assert/strict";
import {createRequire} from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {
  analyticsPath,
  drawAnalyticsTrend,
  mountDashboardAnalytics,
  presentAnalytics,
} = require("../../apps/api/dashboard_analytics.js");


const GENERATED_AT = "2026-09-03T01:02:00Z";
const ENDED_AT = "2026-09-03T01:00:00Z";


function bucket(startedAt, endedAt, overrides = {}) {
  return {
    started_at: startedAt,
    ended_at: endedAt,
    sample_count: 0,
    available_count: 0,
    availability_rate: null,
    temperature_min_c: null,
    temperature_median_c: null,
    temperature_max_c: null,
    humidity_min_rh: null,
    humidity_median_rh: null,
    humidity_max_rh: null,
    ...overrides,
  };
}


function windowBuckets(windowName, populated = true) {
  const count = windowName === "24h" ? 288 : 168;
  const stepMilliseconds = windowName === "24h" ? 300_000 : 3_600_000;
  const endedAt = Date.parse(ENDED_AT);
  const startedAt = endedAt - count * stepMilliseconds;
  return Array.from({length: count}, (_unused, index) => {
    const bucketStart = new Date(startedAt + index * stepMilliseconds).toISOString();
    const bucketEnd = new Date(startedAt + (index + 1) * stepMilliseconds).toISOString();
    if (index !== 0 || !populated) return bucket(bucketStart, bucketEnd);
    return bucket(bucketStart, bucketEnd, {
      sample_count: 4,
      available_count: 3,
      availability_rate: 0.75,
      temperature_min_c: 20,
      temperature_median_c: 22,
      temperature_max_c: 24,
      humidity_min_rh: 40,
      humidity_median_rh: 45,
      humidity_max_rh: 50,
    });
  });
}


function analyticsPayload(overrides = {}) {
  const windowName = overrides.window ?? "24h";
  const buckets = windowBuckets(windowName);
  const durationMilliseconds = windowName === "24h" ? 86_400_000 : 604_800_000;
  const startedAt = new Date(Date.parse(ENDED_AT) - durationMilliseconds).toISOString();
  const environment = {
    state: "available",
    sample_count: 4,
    available_count: 3,
    availability_rate: 0.75,
    incident_counts: {range_normal: 1, range_critical: 0, unreadable: 2},
    buckets,
    ...overrides.environment,
  };
  const guardian = {
    state: "available",
    confirmed_count: 0,
    recovered_count: 2,
    intervention_count: 3,
    recovery_median_seconds: 90,
    risk_counts: {face_not_visible: 0, prone_candidate: 0, outside_candidate: 0},
    evidence_counts: {
      collecting: 0,
      ready: 2,
      failed: 1,
      interrupted: 0,
      retained_total: 3,
      missing: 4,
      ready_rate: 2 / 3,
    },
    notification_counts: {
      pending: 4,
      delivered: 2,
      rejected: 1,
      terminal_total: 3,
      success_rate: 2 / 3,
    },
    ...overrides.guardian,
  };
  return {
    schema_version: 1,
    generated_at: GENERATED_AT,
    window: windowName,
    started_at: startedAt,
    ended_at: ENDED_AT,
    environment,
    guardian,
    ...overrides,
    window: windowName,
    environment,
    guardian,
  };
}


function unavailableEnvironment() {
  return {
    state: "unavailable",
    sample_count: 0,
    available_count: 0,
    availability_rate: null,
    incident_counts: {range_normal: 0, range_critical: 0, unreadable: 0},
    buckets: [],
  };
}


function unavailableGuardian() {
  return {
    state: "unavailable",
    confirmed_count: 0,
    recovered_count: 0,
    intervention_count: 0,
    recovery_median_seconds: null,
    risk_counts: {face_not_visible: 0, prone_candidate: 0, outside_candidate: 0},
    evidence_counts: {
      collecting: 0,
      ready: 0,
      failed: 0,
      interrupted: 0,
      retained_total: 0,
      missing: 0,
      ready_rate: null,
    },
    notification_counts: {
      pending: 0,
      delivered: 0,
      rejected: 0,
      terminal_total: 0,
      success_rate: null,
    },
  };
}


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
    return (this.listeners.get(type) ?? []).map((listener) => listener({
      preventDefault() {},
      ...event,
      currentTarget: this,
      target: event.target ?? this,
    }));
  }
}


class RecordingContext {
  constructor() {
    this.calls = [];
    this.paths = [];
    this.currentPath = [];
    this.strokeStyle = "";
    this.lineWidth = 1;
  }

  beginPath() {
    this.currentPath = [];
    this.calls.push(["beginPath"]);
  }

  clearRect(...values) {
    this.calls.push(["clearRect", ...values]);
  }

  lineTo(...values) {
    this.currentPath.push(["lineTo", ...values]);
    this.calls.push(["lineTo", ...values]);
  }

  moveTo(...values) {
    this.currentPath.push(["moveTo", ...values]);
    this.calls.push(["moveTo", ...values]);
  }

  stroke() {
    this.paths.push({strokeStyle: this.strokeStyle, operations: [...this.currentPath]});
    this.calls.push(["stroke"]);
  }
}


class FakeElement extends FakeEventTarget {
  constructor(document, id = "", tagName = "div") {
    super();
    this.document = document;
    this.id = id;
    this.tagName = tagName;
    this.children = [];
    this.dataset = {};
    this.attributes = new Map();
    this.hidden = false;
    this._textContent = "";
    this._innerHTMLWrites = 0;
    this.width = 0;
    this.height = 0;
    this.context = tagName === "canvas" ? new RecordingContext() : null;
  }

  get textContent() {
    return this._textContent;
  }

  set textContent(value) {
    this._textContent = String(value);
  }

  set innerHTML(_value) {
    this._innerHTMLWrites += 1;
    throw new Error("innerHTML must not be used");
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
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  getContext(kind) {
    return kind === "2d" ? this.context : null;
  }
}


class FakeDocument {
  constructor() {
    this.elements = new Map();
    this.windowButtons = ["24h", "7d"].map((windowName) => {
      const button = this.add(`window-${windowName}`, "button");
      button.dataset.analyticsWindow = windowName;
      button.setAttribute("aria-pressed", String(windowName === "24h"));
      return button;
    });
    for (const id of [
      "analytics-environment-kpi", "analytics-guardian-kpi",
      "analytics-notification-kpi", "analytics-coverage-kpi", "analytics-trend",
      "analytics-summary", "analytics-table", "analytics-updated", "analytics-stale",
      "analytics-refresh",
    ]) this.add(id, id === "analytics-refresh" ? "button" : "div");
    this.getElementById("analytics-stale").hidden = true;
  }

  add(id, tagName = "div") {
    const element = new FakeElement(this, id, tagName);
    this.elements.set(id, element);
    return element;
  }

  createElement(tagName) {
    return new FakeElement(this, "", tagName);
  }

  getElementById(id) {
    return this.elements.get(id) ?? null;
  }

  querySelectorAll(selector) {
    return selector === "[data-analytics-window]" ? this.windowButtons : [];
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


function formatter() {
  return {format: (date) => `fmt:${date.toISOString()}`};
}


function mountFixture({fetch: suppliedFetch = null} = {}) {
  const document = new FakeDocument();
  const calls = [];
  const fetch = suppliedFetch ?? (async (url) => {
    const windowName = url.endsWith("/7d") ? "7d" : "24h";
    return response(analyticsPayload({window: windowName}));
  });
  const controller = mountDashboardAnalytics({
    dateFormatter: formatter(),
    document,
    fetch: async (url, options) => {
      calls.push({url, options});
      return fetch(url, options);
    },
  });
  return {calls, controller, document};
}


test("analytics paths accept only the two closed windows", () => {
  assert.equal(analyticsPath("24h"), "/api/dashboard/analytics/24h");
  assert.equal(analyticsPath("7d"), "/api/dashboard/analytics/7d");
  assert.throws(() => analyticsPath("30d"), /closed analytics window/);
  assert.throws(() => analyticsPath("..%2Fstatus"), /closed analytics window/);
});


test("presenter distinguishes real zero, null denominators, and unavailable sources", () => {
  const noData = presentAnalytics(analyticsPayload({
    environment: unavailableEnvironment(),
    guardian: {
      notification_counts: {
        pending: 0,
        delivered: 0,
        rejected: 0,
        terminal_total: 0,
        success_rate: null,
      },
    },
  }), {dateFormatter: formatter()});
  assert.equal(noData.availabilityText, "不可用");
  assert.equal(noData.confirmedText, "0");
  assert.equal(noData.notificationSuccessText, "无数据");
  assert.equal(noData.recoveryMedianText, "1分30秒");
  assert.equal(noData.generatedText, "fmt:2026-09-03T01:02:00.000Z");
  assert.match(noData.evidenceText, /2\/3/);
  assert.match(noData.evidenceText, /缺失 4/);
  assert.match(noData.evidenceText, /采集中 0/);
  assert.match(noData.evidenceText, /失败 1/);
  assert.match(noData.evidenceText, /中断 0/);
  const withNotifications = presentAnalytics(analyticsPayload());
  assert.match(withNotifications.notificationSuccessText, /终态 3/);
  assert.match(withNotifications.notificationText, /已送达 2/);
  assert.match(withNotifications.notificationText, /已拒绝 1/);
  assert.match(withNotifications.notificationText, /待发送 4/);

  const guardianUnavailable = presentAnalytics(analyticsPayload({
    guardian: unavailableGuardian(),
  }));
  for (const field of [
    "confirmedText", "recoveredText", "recoveryMedianText", "interventionText",
    "riskText", "evidenceText", "notificationSuccessText", "notificationText",
  ]) assert.equal(guardianUnavailable[field], "不可用");

  const environmentUnavailable = presentAnalytics(analyticsPayload({
    environment: unavailableEnvironment(),
  }));
  assert.equal(environmentUnavailable.availabilityText, "不可用");
  assert.equal(environmentUnavailable.incidentText, "不可用");
  assert.deepEqual(environmentUnavailable.buckets, []);
});


test("contract-valid unavailable Guardian masks stored metrics while environment remains renderable", () => {
  const view = presentAnalytics(analyticsPayload({
    guardian: {
      state: "unavailable",
      confirmed_count: 7,
      recovered_count: 2,
      intervention_count: 3,
      recovery_median_seconds: 90,
    },
  }));

  assert.equal(view.availabilityText, "75.0%");
  assert.equal(view.buckets.length, 288);
  for (const field of [
    "confirmedText", "recoveredText", "recoveryMedianText", "interventionText",
    "riskText", "evidenceText", "notificationSuccessText", "notificationText",
  ]) assert.equal(view[field], "不可用");
});


test("available zero denominators display no-data without replacing count zero", () => {
  const view = presentAnalytics(analyticsPayload({
    environment: {
      state: "available",
      sample_count: 0,
      available_count: 0,
      availability_rate: null,
      incident_counts: {range_normal: 0, range_critical: 0, unreadable: 0},
      buckets: windowBuckets("24h", false),
    },
    guardian: {
      recovered_count: 0,
      recovery_median_seconds: null,
      evidence_counts: {
        collecting: 0,
        ready: 0,
        failed: 0,
        interrupted: 0,
        retained_total: 0,
        missing: 0,
        ready_rate: null,
      },
      notification_counts: {
        pending: 0,
        delivered: 0,
        rejected: 0,
        terminal_total: 0,
        success_rate: null,
      },
    },
  }));
  assert.equal(view.availabilityText, "无数据");
  assert.equal(view.confirmedText, "0");
  assert.equal(view.recoveredText, "0");
  assert.equal(view.recoveryMedianText, "无数据");
  assert.equal(view.notificationSuccessText, "无数据");
});


test("presenter rejects open shapes, stale field names, invalid bounds, and broken invariants", () => {
  assert.throws(() => presentAnalytics({...analyticsPayload(), unexpected: "closed"}), /closed dashboard analytics/);
  assert.throws(() => presentAnalytics(analyticsPayload({environment: {private_state: "bad"}})), /closed dashboard environment analytics/);
  assert.throws(() => presentAnalytics(analyticsPayload({guardian: {confirmed_event_count: 0}})), /closed dashboard guardian analytics/);

  const extraBucketPayload = analyticsPayload();
  extraBucketPayload.environment.buckets[0] = {
    ...extraBucketPayload.environment.buckets[0],
    interpolated: true,
  };
  assert.throws(() => presentAnalytics(extraBucketPayload), /closed dashboard trend bucket/);

  assert.throws(
    () => presentAnalytics(analyticsPayload({generated_at: "2026-09-03T01:02:00"})),
    /timezone-aware analytics timestamp/,
  );
  assert.throws(
    () => presentAnalytics(analyticsPayload({environment: {available_count: 5}})),
    /closed dashboard environment analytics/,
  );
  assert.throws(
    () => presentAnalytics(analyticsPayload({environment: {availability_rate: 0.5}})),
    /closed dashboard environment analytics/,
  );
  assert.throws(
    () => presentAnalytics(analyticsPayload({guardian: {confirmed_count: -1}})),
    /closed dashboard guardian analytics/,
  );
  assert.throws(
    () => presentAnalytics(analyticsPayload({guardian: {
      evidence_counts: {
        collecting: 0, ready: 2, failed: 1, interrupted: 0,
        retained_total: 4, missing: 4, ready_rate: 0.5,
      },
    }})),
    /closed dashboard evidence counts/,
  );
  assert.throws(
    () => presentAnalytics(analyticsPayload({guardian: {
      notification_counts: {
        pending: 0, delivered: 2, rejected: 1, terminal_total: 4, success_rate: 0.5,
      },
    }})),
    /closed dashboard notification counts/,
  );

  const badTemperature = analyticsPayload();
  badTemperature.environment.buckets[0].temperature_max_c = 61;
  assert.throws(() => presentAnalytics(badTemperature), /closed dashboard trend bucket/);

  const shortWindow = analyticsPayload();
  shortWindow.environment.buckets.pop();
  assert.throws(() => presentAnalytics(shortWindow), /closed dashboard environment analytics/);
});


test("trend drawing breaks all six series across gaps and scales temperature and humidity independently", () => {
  const canvas = new FakeElement(null, "trend", "canvas");
  canvas.width = 300;
  canvas.height = 160;
  const buckets = [
    bucket("2026-09-03T00:00:00Z", "2026-09-03T00:05:00Z", {
      sample_count: 1, available_count: 1, availability_rate: 1,
      temperature_min_c: 10, temperature_median_c: 15, temperature_max_c: 20,
      humidity_min_rh: 30, humidity_median_rh: 40, humidity_max_rh: 50,
    }),
    bucket("2026-09-03T00:05:00Z", "2026-09-03T00:10:00Z"),
    bucket("2026-09-03T00:10:00Z", "2026-09-03T00:15:00Z", {
      sample_count: 1, available_count: 1, availability_rate: 1,
      temperature_min_c: 20, temperature_median_c: 25, temperature_max_c: 30,
      humidity_min_rh: 50, humidity_median_rh: 60, humidity_max_rh: 70,
    }),
  ];

  drawAnalyticsTrend(canvas, buckets);

  const seriesPaths = canvas.context.paths.slice(1);
  assert.equal(seriesPaths.length, 6);
  for (const path of seriesPaths) {
    assert.deepEqual(path.operations.map(([operation]) => operation), ["moveTo", "moveTo"]);
  }
  const temperatureMinimum = seriesPaths[0].operations;
  const humidityMinimum = seriesPaths[3].operations;
  assert.equal(temperatureMinimum[0][2], humidityMinimum[0][2]);
  assert.equal(temperatureMinimum[1][2], humidityMinimum[1][2]);
});


test("trend with no finite values clears and draws axes without fabricating a line", () => {
  const canvas = new FakeElement(null, "trend", "canvas");
  canvas.width = 300;
  canvas.height = 160;

  drawAnalyticsTrend(canvas, [
    bucket("2026-09-03T00:00:00Z", "2026-09-03T00:05:00Z"),
    bucket("2026-09-03T00:05:00Z", "2026-09-03T00:10:00Z"),
  ]);

  assert.deepEqual(canvas.context.calls[0], ["clearRect", 0, 0, 300, 160]);
  assert.equal(canvas.context.paths.length, 1);
});


test("rendered analytics use safe DOM, four KPIs, compositions, chart fallback, and a bounded real table", async () => {
  const fixture = mountFixture();

  await fixture.controller.activate();

  assert.equal(fixture.document.getElementById("analytics-environment-kpi").children[1].textContent, "75.0%");
  assert.equal(fixture.document.getElementById("analytics-guardian-kpi").children[1].textContent, "0");
  assert.equal(fixture.document.getElementById("analytics-notification-kpi").children[1].textContent, "1分30秒");
  assert.equal(fixture.document.getElementById("analytics-coverage-kpi").children[1].textContent, "3");
  assert.match(fixture.document.getElementById("analytics-summary").textContent, /风险构成/);
  assert.match(fixture.document.getElementById("analytics-summary").textContent, /已恢复 2/);
  assert.match(fixture.document.getElementById("analytics-summary").textContent, /环境事件/);
  assert.match(fixture.document.getElementById("analytics-summary").textContent, /缺失 4/);
  assert.match(fixture.document.getElementById("analytics-summary").textContent, /待发送 4/);

  const trend = fixture.document.getElementById("analytics-trend");
  assert.equal(trend.children[1].tagName, "canvas");
  assert.match(trend.children[2].textContent, /温度/);
  assert.match(trend.children[2].textContent, /湿度/);

  const table = fixture.document.getElementById("analytics-table").children[0];
  assert.equal(table.tagName, "table");
  assert.equal(table.children[1].children.length, 288);
  assert.equal(table.children[1].children[0].children.length, 4);
  assert.equal(table.children[1].children[0].children[0].textContent, "fmt:2026-09-02T01:00:00.000Z");
  assert.equal(table.children[1].children[0].children[1].textContent, "75.0%");
  assert.equal(table.children[1].children[0].children[2].textContent, "22.0°C");
  assert.equal(table.children[1].children[0].children[3].textContent, "45.0%RH");
  assert.equal(fixture.document.getElementById("analytics-updated").textContent, "fmt:2026-09-03T01:02:00.000Z");
  assert.equal(fixture.document.getElementById("analytics-stale").hidden, true);
  assert.equal([...fixture.document.elements.values()].reduce((total, element) => total + element._innerHTMLWrites, 0), 0);
});


test("controller is lazy, caches each successful window, and refreshes only the current window", async () => {
  const fixture = mountFixture();
  assert.equal(fixture.calls.length, 0);

  await fixture.controller.activate();
  assert.deepEqual(fixture.calls.map((call) => call.url), ["/api/dashboard/analytics/24h"]);

  await fixture.controller.activate();
  assert.equal(fixture.calls.length, 1);

  await fixture.controller.selectWindow("7d");
  assert.deepEqual(fixture.calls.map((call) => call.url), [
    "/api/dashboard/analytics/24h",
    "/api/dashboard/analytics/7d",
  ]);
  assert.equal(fixture.document.windowButtons[0].getAttribute("aria-pressed"), "false");
  assert.equal(fixture.document.windowButtons[1].getAttribute("aria-pressed"), "true");

  await fixture.controller.selectWindow("24h");
  assert.equal(fixture.calls.length, 2);
  await fixture.controller.refresh();
  assert.equal(fixture.calls.at(-1).url, "/api/dashboard/analytics/24h");
  assert.equal(fixture.calls.length, 3);
  assert.throws(() => fixture.controller.selectWindow("30d"), /closed analytics window/);
});


test("controller deduplicates one pending request per window and ignores inactive late rendering", async () => {
  const pending24h = deferred();
  const pending7d = deferred();
  const fixture = mountFixture({fetch: async (url) => (
    url.endsWith("/7d") ? pending7d.promise : pending24h.promise
  )});

  const first = fixture.controller.activate();
  const duplicate = fixture.controller.refresh();
  assert.equal(fixture.calls.length, 1);

  const sevenDay = fixture.controller.selectWindow("7d");
  assert.equal(fixture.calls.length, 2);
  pending24h.resolve(response(analyticsPayload()));
  await Promise.all([first, duplicate]);
  assert.equal(fixture.document.getElementById("analytics-updated").textContent, "正在读取…");

  pending7d.resolve(response(analyticsPayload({window: "7d", generated_at: "2026-09-03T01:03:00Z"})));
  await sevenDay;
  assert.equal(fixture.document.getElementById("analytics-updated").textContent, "fmt:2026-09-03T01:03:00.000Z");

  await fixture.controller.selectWindow("24h");
  assert.equal(fixture.calls.length, 2);
  assert.equal(fixture.document.getElementById("analytics-updated").textContent, "fmt:2026-09-03T01:02:00.000Z");
});


test("failed refresh retains metrics, chart, and generated time while marking stale", async () => {
  const outcomes = [response(analyticsPayload()), {ok: false}];
  const fixture = mountFixture({fetch: async () => outcomes.shift()});
  await fixture.controller.activate();
  const metric = fixture.document.getElementById("analytics-environment-kpi").children[1];
  const trendCanvas = fixture.document.getElementById("analytics-trend").children[1];
  const updated = fixture.document.getElementById("analytics-updated").textContent;

  const result = await fixture.controller.refresh();

  assert.deepEqual(result, {ok: false, error: "DASHBOARD_DATA_UNAVAILABLE"});
  assert.equal(fixture.document.getElementById("analytics-environment-kpi").children[1], metric);
  assert.equal(fixture.document.getElementById("analytics-trend").children[1], trendCanvas);
  assert.equal(fixture.document.getElementById("analytics-updated").textContent, updated);
  assert.equal(fixture.document.getElementById("analytics-stale").hidden, false);
  assert.equal(
    fixture.document.getElementById("analytics-stale").textContent,
    "数据可能已过期 · 上次更新：fmt:2026-09-03T01:02:00.000Z",
  );
});


test("stale state belongs to each window and only a successful response clears it", async () => {
  let twentyFourHourCalls = 0;
  const fixture = mountFixture({fetch: async (url) => {
    if (url.endsWith("/7d")) {
      return response(analyticsPayload({
        window: "7d",
        generated_at: "2026-09-03T01:03:00Z",
      }));
    }
    twentyFourHourCalls += 1;
    if (twentyFourHourCalls === 2) return {ok: false};
    return response(analyticsPayload({
      generated_at: twentyFourHourCalls === 1
        ? "2026-09-03T01:02:00Z"
        : "2026-09-03T01:05:00Z",
    }));
  }});
  await fixture.controller.activate();
  await fixture.controller.refresh();
  assert.equal(fixture.document.getElementById("analytics-stale").hidden, false);
  assert.equal(fixture.calls.length, 2);

  await fixture.controller.activate();
  assert.equal(fixture.calls.length, 2);
  assert.equal(fixture.document.getElementById("analytics-stale").hidden, false);
  assert.equal(
    fixture.document.getElementById("analytics-stale").textContent,
    "数据可能已过期 · 上次更新：fmt:2026-09-03T01:02:00.000Z",
  );

  await fixture.controller.selectWindow("7d");
  assert.equal(fixture.document.getElementById("analytics-stale").hidden, true);
  assert.equal(fixture.document.getElementById("analytics-updated").textContent, "fmt:2026-09-03T01:03:00.000Z");
  assert.equal(fixture.calls.length, 3);

  await fixture.controller.selectWindow("24h");
  assert.equal(fixture.calls.length, 3);
  assert.equal(fixture.document.getElementById("analytics-stale").hidden, false);
  assert.equal(
    fixture.document.getElementById("analytics-stale").textContent,
    "数据可能已过期 · 上次更新：fmt:2026-09-03T01:02:00.000Z",
  );

  await fixture.controller.refresh();
  assert.equal(fixture.calls.length, 4);
  assert.equal(fixture.document.getElementById("analytics-stale").hidden, true);
  assert.equal(fixture.document.getElementById("analytics-updated").textContent, "fmt:2026-09-03T01:05:00.000Z");
});


test("uncached window loading and failure never display another window and can recover", async () => {
  const firstSevenDay = deferred();
  let sevenDayCalls = 0;
  const fixture = mountFixture({fetch: async (url) => {
    if (url.endsWith("/24h")) return response(analyticsPayload());
    sevenDayCalls += 1;
    if (sevenDayCalls === 1) return firstSevenDay.promise;
    return response(analyticsPayload({
      window: "7d",
      generated_at: "2026-09-03T01:04:00Z",
      guardian: {confirmed_count: 5},
    }));
  }});
  await fixture.controller.activate();
  assert.equal(fixture.document.getElementById("analytics-environment-kpi").children[1].textContent, "75.0%");

  const firstSelection = fixture.controller.selectWindow("7d");
  assert.equal(fixture.document.getElementById("analytics-environment-kpi").children[1].textContent, "正在读取…");
  assert.equal(fixture.document.getElementById("analytics-trend").children.length, 0);
  assert.equal(fixture.document.getElementById("analytics-summary").textContent, "正在读取…");
  assert.equal(fixture.document.getElementById("analytics-table").children.length, 0);

  firstSevenDay.resolve({ok: false});
  assert.deepEqual(await firstSelection, {ok: false, error: "DASHBOARD_DATA_UNAVAILABLE"});
  assert.equal(fixture.document.getElementById("analytics-environment-kpi").children[1].textContent, "不可用");
  assert.equal(fixture.document.getElementById("analytics-trend").children.length, 0);
  assert.equal(fixture.document.getElementById("analytics-trend").textContent, "数据不可用");
  assert.equal(fixture.document.getElementById("analytics-summary").textContent, "数据不可用");
  assert.equal(fixture.document.getElementById("analytics-table").children.length, 0);
  assert.equal(fixture.document.getElementById("analytics-table").textContent, "数据不可用");

  assert.deepEqual((await fixture.controller.refresh()).ok, true);
  assert.equal(fixture.document.getElementById("analytics-guardian-kpi").children[1].textContent, "5");
  assert.equal(fixture.document.getElementById("analytics-trend").children[1].tagName, "canvas");
  assert.equal(fixture.document.getElementById("analytics-table").children[0].children[1].children.length, 168);
  assert.equal(fixture.document.getElementById("analytics-updated").textContent, "fmt:2026-09-03T01:04:00.000Z");
  assert.equal(fixture.document.getElementById("analytics-stale").hidden, true);
});


test("first failure marks analytics unavailable without fabricating zero metrics", async () => {
  const fixture = mountFixture({fetch: async () => {
    throw new Error("private dashboard failure");
  }});

  const result = await fixture.controller.activate();

  assert.deepEqual(result, {ok: false, error: "DASHBOARD_DATA_UNAVAILABLE"});
  assert.equal(fixture.document.getElementById("analytics-updated").textContent, "数据不可用");
  assert.equal(fixture.document.getElementById("analytics-stale").hidden, true);
  assert.doesNotMatch(fixture.document.getElementById("analytics-updated").textContent, /private/);
});


test("window and refresh controls call only the mounted closed controller", async () => {
  const fixture = mountFixture();
  assert.equal(fixture.calls.length, 0);

  await Promise.all(fixture.document.windowButtons[1].dispatch("click"));
  assert.deepEqual(fixture.calls.map((call) => call.url), ["/api/dashboard/analytics/7d"]);

  await Promise.all(fixture.document.getElementById("analytics-refresh").dispatch("click"));
  assert.deepEqual(fixture.calls.map((call) => call.url), [
    "/api/dashboard/analytics/7d",
    "/api/dashboard/analytics/7d",
  ]);
});
