(function exposeDashboardAnalytics(root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BabyMonitorDashboardAnalytics = api;
})(globalThis, function createDashboardAnalyticsApi() {
  "use strict";

  const windows = new Map([
    ["24h", {bucketCount: 288, durationMilliseconds: 86400000, intervalMilliseconds: 300000, label: "24小时"}],
    ["7d", {bucketCount: 168, durationMilliseconds: 604800000, intervalMilliseconds: 3600000, label: "7天"}],
  ]);
  const unavailableCode = "DASHBOARD_DATA_UNAVAILABLE";
  const maximumBucketCount = 288;
  const timestampPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
  const topLevelKeys = [
    "schema_version", "generated_at", "window", "started_at", "ended_at",
    "environment", "guardian",
  ];
  const environmentKeys = [
    "state", "sample_count", "available_count", "availability_rate",
    "incident_counts", "buckets",
  ];
  const guardianKeys = [
    "state", "confirmed_count", "recovered_count", "intervention_count",
    "recovery_median_seconds", "risk_counts", "evidence_counts", "notification_counts",
  ];
  const bucketKeys = [
    "started_at", "ended_at", "sample_count", "available_count", "availability_rate",
    "temperature_min_c", "temperature_median_c", "temperature_max_c",
    "humidity_min_rh", "humidity_median_rh", "humidity_max_rh",
  ];
  const riskKeys = ["face_not_visible", "prone_candidate", "outside_candidate"];
  const evidenceKeys = [
    "collecting", "ready", "failed", "interrupted", "retained_total", "missing", "ready_rate",
  ];
  const notificationKeys = ["pending", "delivered", "rejected", "terminal_total", "success_rate"];
  const incidentKeys = ["range_normal", "range_critical", "unreadable"];
  const temperatureFields = ["temperature_min_c", "temperature_median_c", "temperature_max_c"];
  const humidityFields = ["humidity_min_rh", "humidity_median_rh", "humidity_max_rh"];

  function analyticsPath(windowName) {
    if (!windows.has(windowName)) throw new TypeError("closed analytics window required");
    return `/api/dashboard/analytics/${windowName}`;
  }

  function requireExactObject(value, keys, message) {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new TypeError(message);
    const actual = Object.keys(value);
    if (actual.length !== keys.length || !keys.every((key) => actual.includes(key))) {
      throw new TypeError(message);
    }
    return value;
  }

  function requireCount(value, message) {
    if (!Number.isSafeInteger(value) || value < 0) throw new TypeError(message);
    return value;
  }

  function requireFinite(value, minimum, maximum, message) {
    if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) {
      throw new TypeError(message);
    }
    return value;
  }

  function requireNullableFinite(value, minimum, maximum, message) {
    if (value === null) return null;
    return requireFinite(value, minimum, maximum, message);
  }

  function requireTimestamp(value) {
    if (typeof value !== "string" || !timestampPattern.test(value)) {
      throw new TypeError("timezone-aware analytics timestamp required");
    }
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) {
      throw new TypeError("timezone-aware analytics timestamp required");
    }
    return date;
  }

  function requireRate(actual, numerator, denominator, message) {
    if (denominator === 0) {
      if (actual !== null) throw new TypeError(message);
      return;
    }
    requireFinite(actual, 0, 1, message);
    if (Math.abs(actual - numerator / denominator) > 1e-12) throw new TypeError(message);
  }

  function validateCountObject(value, keys, message) {
    requireExactObject(value, keys, message);
    for (const key of keys) requireCount(value[key], message);
    return value;
  }

  function validateMeasurementTriple(value, fields, availableCount, minimum, maximum, message) {
    const values = fields.map((field) => requireNullableFinite(value[field], minimum, maximum, message));
    if (availableCount === 0) {
      if (values.some((item) => item !== null)) throw new TypeError(message);
      return;
    }
    if (values.some((item) => item === null) || !(values[0] <= values[1] && values[1] <= values[2])) {
      throw new TypeError(message);
    }
  }

  function validateBucket(value) {
    const message = "closed dashboard trend bucket required";
    requireExactObject(value, bucketKeys, message);
    const startedAt = requireTimestamp(value.started_at);
    const endedAt = requireTimestamp(value.ended_at);
    if (endedAt <= startedAt) throw new TypeError(message);
    requireCount(value.sample_count, message);
    requireCount(value.available_count, message);
    if (value.available_count > value.sample_count) throw new TypeError(message);
    requireRate(value.availability_rate, value.available_count, value.sample_count, message);
    validateMeasurementTriple(value, temperatureFields, value.available_count, -50, 60, message);
    validateMeasurementTriple(value, humidityFields, value.available_count, 0, 100, message);
    return value;
  }

  function validateEvidence(value) {
    const message = "closed dashboard evidence counts required";
    requireExactObject(value, evidenceKeys, message);
    for (const key of evidenceKeys.slice(0, 6)) requireCount(value[key], message);
    if (value.retained_total !== value.collecting + value.ready + value.failed + value.interrupted) {
      throw new TypeError(message);
    }
    requireRate(value.ready_rate, value.ready, value.retained_total, message);
    return value;
  }

  function validateNotifications(value) {
    const message = "closed dashboard notification counts required";
    requireExactObject(value, notificationKeys, message);
    for (const key of notificationKeys.slice(0, 4)) requireCount(value[key], message);
    if (value.terminal_total !== value.delivered + value.rejected) throw new TypeError(message);
    requireRate(value.success_rate, value.delivered, value.terminal_total, message);
    return value;
  }

  function validateGuardian(value) {
    const message = "closed dashboard guardian analytics required";
    requireExactObject(value, guardianKeys, message);
    if (!new Set(["available", "unavailable"]).has(value.state)) throw new TypeError(message);
    requireCount(value.confirmed_count, message);
    requireCount(value.recovered_count, message);
    requireCount(value.intervention_count, message);
    requireNullableFinite(value.recovery_median_seconds, 0, Number.MAX_SAFE_INTEGER, message);
    validateCountObject(value.risk_counts, riskKeys, "closed dashboard risk counts required");
    validateEvidence(value.evidence_counts);
    validateNotifications(value.notification_counts);
    if (value.state === "unavailable") {
      const countValues = [
        value.confirmed_count, value.recovered_count, value.intervention_count,
        ...riskKeys.map((key) => value.risk_counts[key]),
        ...evidenceKeys.slice(0, 6).map((key) => value.evidence_counts[key]),
        ...notificationKeys.slice(0, 4).map((key) => value.notification_counts[key]),
      ];
      if (countValues.some((item) => item !== 0) || value.recovery_median_seconds !== null ||
          value.evidence_counts.ready_rate !== null || value.notification_counts.success_rate !== null) {
        throw new TypeError(message);
      }
    }
    return value;
  }

  function validateEnvironment(value, windowName, startedAt, endedAt) {
    const message = "closed dashboard environment analytics required";
    requireExactObject(value, environmentKeys, message);
    if (!new Set(["available", "unavailable"]).has(value.state)) throw new TypeError(message);
    requireCount(value.sample_count, message);
    requireCount(value.available_count, message);
    if (value.available_count > value.sample_count) throw new TypeError(message);
    validateCountObject(value.incident_counts, incidentKeys, "closed dashboard incident counts required");
    if (!Array.isArray(value.buckets) || value.buckets.length > maximumBucketCount) throw new TypeError(message);
    const buckets = value.buckets.map(validateBucket);
    if (value.state === "unavailable") {
      if (value.sample_count !== 0 || value.available_count !== 0 || value.availability_rate !== null ||
          buckets.length !== 0 || incidentKeys.some((key) => value.incident_counts[key] !== 0)) {
        throw new TypeError(message);
      }
      return buckets;
    }

    requireRate(value.availability_rate, value.available_count, value.sample_count, message);
    const definition = windows.get(windowName);
    if (buckets.length !== definition.bucketCount) throw new TypeError(message);
    if (Date.parse(buckets[0].started_at) !== startedAt.getTime() ||
        Date.parse(buckets.at(-1).ended_at) !== endedAt.getTime()) {
      throw new TypeError(message);
    }
    let sampleTotal = 0;
    let availableTotal = 0;
    for (let index = 0; index < buckets.length; index += 1) {
      const item = buckets[index];
      const bucketStart = Date.parse(item.started_at);
      const bucketEnd = Date.parse(item.ended_at);
      if (bucketEnd - bucketStart !== definition.intervalMilliseconds) throw new TypeError(message);
      if (index > 0 && Date.parse(buckets[index - 1].ended_at) !== bucketStart) throw new TypeError(message);
      sampleTotal += item.sample_count;
      availableTotal += item.available_count;
    }
    if (sampleTotal !== value.sample_count || availableTotal !== value.available_count) throw new TypeError(message);
    return buckets;
  }

  function formatTimestamp(value, options = {}) {
    const date = requireTimestamp(value);
    const dateFormatter = options.dateFormatter ?? new Intl.DateTimeFormat(undefined, {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
    if (!dateFormatter || typeof dateFormatter.format !== "function") {
      throw new TypeError("analytics date formatter required");
    }
    return dateFormatter.format(date);
  }

  function formatPercent(value) {
    return value === null ? "无数据" : `${(value * 100).toFixed(1)}%`;
  }

  function formatDuration(value) {
    if (value === null) return "无数据";
    const totalSeconds = Math.round(value);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return minutes === 0 ? `${seconds}秒` : `${minutes}分${seconds}秒`;
  }

  function measurementSummary(buckets) {
    const temperatures = buckets.flatMap((item) => temperatureFields.map((field) => item[field])).filter(Number.isFinite);
    const humidities = buckets.flatMap((item) => humidityFields.map((field) => item[field])).filter(Number.isFinite);
    if (temperatures.length === 0 && humidities.length === 0) return "温湿度无数据";
    const temperatureText = temperatures.length === 0 ? "温度无数据"
      : `温度 ${Math.min(...temperatures).toFixed(1)}–${Math.max(...temperatures).toFixed(1)}°C`;
    const humidityText = humidities.length === 0 ? "湿度无数据"
      : `湿度 ${Math.min(...humidities).toFixed(1)}–${Math.max(...humidities).toFixed(1)}%RH`;
    return `${temperatureText} · ${humidityText}`;
  }

  function presentAnalytics(payload, options = {}) {
    requireExactObject(payload, topLevelKeys, "closed dashboard analytics required");
    if (payload.schema_version !== 1 || !windows.has(payload.window)) {
      throw new TypeError("closed dashboard analytics required");
    }
    const generatedAt = requireTimestamp(payload.generated_at);
    const startedAt = requireTimestamp(payload.started_at);
    const endedAt = requireTimestamp(payload.ended_at);
    const definition = windows.get(payload.window);
    if (endedAt <= startedAt || endedAt.getTime() - startedAt.getTime() !== definition.durationMilliseconds) {
      throw new TypeError("closed dashboard analytics required");
    }
    const buckets = validateEnvironment(payload.environment, payload.window, startedAt, endedAt);
    validateGuardian(payload.guardian);
    const environmentAvailable = payload.environment.state === "available";
    const guardianAvailable = payload.guardian.state === "available";
    const evidence = payload.guardian.evidence_counts;
    const notifications = payload.guardian.notification_counts;
    const risk = payload.guardian.risk_counts;
    const incidents = payload.environment.incident_counts;

    return {
      availabilityText: environmentAvailable ? formatPercent(payload.environment.availability_rate) : "不可用",
      buckets,
      confirmedText: guardianAvailable ? String(payload.guardian.confirmed_count) : "不可用",
      evidenceText: guardianAvailable
        ? `证据就绪 ${evidence.ready}/${evidence.retained_total}（采集中 ${evidence.collecting} · 失败 ${evidence.failed} · 中断 ${evidence.interrupted} · 缺失 ${evidence.missing}）`
        : "不可用",
      generatedAt: payload.generated_at,
      generatedText: formatTimestamp(payload.generated_at, options),
      incidentText: environmentAvailable
        ? `范围 ${incidents.range_normal} · 严重 ${incidents.range_critical} · 不可读 ${incidents.unreadable}`
        : "不可用",
      interventionText: guardianAvailable ? String(payload.guardian.intervention_count) : "不可用",
      notificationSuccessText: guardianAvailable
        ? (notifications.success_rate === null
          ? "无数据"
          : `${formatPercent(notifications.success_rate)}（终态 ${notifications.terminal_total}）`)
        : "不可用",
      notificationText: guardianAvailable
        ? `已送达 ${notifications.delivered} · 已拒绝 ${notifications.rejected} · 待发送 ${notifications.pending}`
        : "不可用",
      recoveredText: guardianAvailable ? String(payload.guardian.recovered_count) : "不可用",
      recoveryMedianText: guardianAvailable ? formatDuration(payload.guardian.recovery_median_seconds) : "不可用",
      riskText: guardianAvailable
        ? `遮挡 ${risk.face_not_visible} · 俯卧 ${risk.prone_candidate} · 离床 ${risk.outside_candidate}`
        : "不可用",
      trendSummary: environmentAvailable ? measurementSummary(buckets) : "温湿度不可用",
      window: payload.window,
      windowLabel: definition.label,
    };
  }

  function drawAnalyticsTrend(canvas, buckets) {
    if (!canvas || typeof canvas.getContext !== "function" || !Array.isArray(buckets) ||
        buckets.length > maximumBucketCount) {
      throw new TypeError("closed dashboard analytics chart required");
    }
    const validated = buckets.map(validateBucket);
    const context = canvas.getContext("2d");
    if (!context) return false;
    const width = Number(canvas.width) || 900;
    const height = Number(canvas.height) || 260;
    const left = 36;
    const right = 12;
    const top = 12;
    const bottom = 24;
    const chartWidth = Math.max(1, width - left - right);
    const chartHeight = Math.max(1, height - top - bottom);
    context.clearRect(0, 0, width, height);
    context.strokeStyle = "#718096";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(left, top);
    context.lineTo(left, top + chartHeight);
    context.lineTo(left + chartWidth, top + chartHeight);
    context.stroke();

    const groups = [
      {
        fields: temperatureFields,
        colors: ["#60a5fa", "#2563eb", "#1d4ed8"],
      },
      {
        fields: humidityFields,
        colors: ["#6ee7b7", "#10b981", "#047857"],
      },
    ];
    for (const group of groups) {
      const values = validated.flatMap((item) => group.fields.map((field) => item[field])).filter(Number.isFinite);
      if (values.length === 0) continue;
      let minimum = Math.min(...values);
      let maximum = Math.max(...values);
      if (minimum === maximum) {
        minimum -= 0.5;
        maximum += 0.5;
      }
      for (const [fieldIndex, field] of group.fields.entries()) {
        let drawing = false;
        let hasPoint = false;
        context.strokeStyle = group.colors[fieldIndex];
        context.lineWidth = fieldIndex === 1 ? 2 : 1;
        context.beginPath();
        for (const [index, item] of validated.entries()) {
          const value = item[field];
          if (value === null) {
            drawing = false;
            continue;
          }
          const x = left + (validated.length <= 1 ? chartWidth / 2 : chartWidth * index / (validated.length - 1));
          const y = top + chartHeight - (value - minimum) / (maximum - minimum) * chartHeight;
          if (drawing) context.lineTo(x, y);
          else context.moveTo(x, y);
          drawing = true;
          hasPoint = true;
        }
        if (hasPoint) context.stroke();
      }
    }
    return true;
  }

  function createLabeledValue(document, label, value) {
    const heading = document.createElement("h3");
    heading.textContent = label;
    const paragraph = document.createElement("p");
    paragraph.textContent = value;
    return [heading, paragraph];
  }

  function renderKpi(document, id, label, value) {
    const element = document.getElementById(id);
    if (element) element.replaceChildren(...createLabeledValue(document, label, value));
  }

  function appendCell(document, row, tagName, text) {
    const cell = document.createElement(tagName);
    cell.textContent = text;
    row.append(cell);
  }

  function renderAnalytics(document, payload, options = {}) {
    const view = presentAnalytics(payload, options);
    renderKpi(document, "analytics-environment-kpi", "环境数据可用率", view.availabilityText);
    renderKpi(document, "analytics-guardian-kpi", "已确认 Guardian 事件", view.confirmedText);
    renderKpi(document, "analytics-notification-kpi", "恢复时长中位数", view.recoveryMedianText);
    renderKpi(document, "analytics-coverage-kpi", "成人介入次数", view.interventionText);

    const trend = document.getElementById("analytics-trend");
    if (trend) {
      const title = document.createElement("h3");
      title.textContent = `${view.windowLabel}温湿度趋势`;
      const canvas = document.createElement("canvas");
      canvas.width = 900;
      canvas.height = 260;
      canvas.setAttribute("aria-label", `${view.windowLabel}温湿度趋势图`);
      const fallback = document.createElement("p");
      fallback.textContent = view.trendSummary;
      trend.replaceChildren(title, canvas, fallback);
      drawAnalyticsTrend(canvas, view.buckets);
    }

    const summary = document.getElementById("analytics-summary");
    if (summary) {
      summary.textContent = `风险构成：${view.riskText}；已恢复 ${view.recoveredText}；环境事件：${view.incidentText}；${view.evidenceText}；通知成功率 ${view.notificationSuccessText}；${view.notificationText}`;
    }

    const tableContainer = document.getElementById("analytics-table");
    if (tableContainer) {
      const table = document.createElement("table");
      const head = document.createElement("thead");
      const headingRow = document.createElement("tr");
      for (const label of ["桶起始时间", "可用率", "温度中位数", "湿度中位数"]) {
        appendCell(document, headingRow, "th", label);
      }
      head.append(headingRow);
      const body = document.createElement("tbody");
      for (const item of view.buckets.slice(0, maximumBucketCount)) {
        const row = document.createElement("tr");
        appendCell(document, row, "td", formatTimestamp(item.started_at, options));
        appendCell(document, row, "td", formatPercent(item.availability_rate));
        appendCell(document, row, "td", item.temperature_median_c === null ? "无数据" : `${item.temperature_median_c.toFixed(1)}°C`);
        appendCell(document, row, "td", item.humidity_median_rh === null ? "无数据" : `${item.humidity_median_rh.toFixed(1)}%RH`);
        body.append(row);
      }
      table.append(head, body);
      tableContainer.replaceChildren(table);
    }

    const updated = document.getElementById("analytics-updated");
    if (updated) updated.textContent = view.generatedText;
    const stale = document.getElementById("analytics-stale");
    if (stale) {
      stale.hidden = true;
      stale.textContent = "";
    }
    return view;
  }

  function markUnavailable(document) {
    const updated = document.getElementById("analytics-updated");
    if (updated) updated.textContent = "数据不可用";
    const stale = document.getElementById("analytics-stale");
    if (stale) {
      stale.hidden = true;
      stale.textContent = "";
    }
  }

  function markStale(document, generatedAt, options) {
    const stale = document.getElementById("analytics-stale");
    if (!stale) return;
    stale.hidden = false;
    stale.textContent = `数据可能已过期 · 上次更新：${formatTimestamp(generatedAt, options)}`;
  }

  function mountDashboardAnalytics(environment) {
    const document = environment?.document;
    if (!document || typeof environment.fetch !== "function") return null;
    let currentWindow = "24h";
    const state = new Map([...windows.keys()].map((windowName) => [windowName, {
      cache: null,
      generation: 0,
      inFlight: null,
      lastSuccessAt: null,
    }]));
    const renderOptions = {dateFormatter: environment.dateFormatter};

    function updateButtons() {
      for (const button of document.querySelectorAll("[data-analytics-window]")) {
        button.setAttribute("aria-pressed", String(button.dataset.analyticsWindow === currentWindow));
      }
    }

    function renderCached(windowName) {
      const windowState = state.get(windowName);
      return renderAnalytics(document, windowState.cache, renderOptions);
    }

    function request(windowName) {
      const windowState = state.get(windowName);
      if (windowState.inFlight !== null) return windowState.inFlight;
      const generation = windowState.generation + 1;
      windowState.generation = generation;
      let requestPromise;
      requestPromise = (async () => {
        try {
          const response = await environment.fetch(analyticsPath(windowName));
          if (!response || response.ok !== true) throw new TypeError(unavailableCode);
          const payload = await response.json();
          const view = presentAnalytics(payload, renderOptions);
          if (view.window !== windowName) throw new TypeError(unavailableCode);
          if (generation !== windowState.generation) return {ok: false, superseded: true};
          windowState.cache = payload;
          windowState.lastSuccessAt = payload.generated_at;
          if (currentWindow === windowName) renderAnalytics(document, payload, renderOptions);
          return {ok: true, payload};
        } catch (_error) {
          if (generation === windowState.generation && currentWindow === windowName) {
            if (windowState.cache === null) markUnavailable(document);
            else markStale(document, windowState.lastSuccessAt, renderOptions);
          }
          return {ok: false, error: unavailableCode};
        } finally {
          if (windowState.inFlight === requestPromise) windowState.inFlight = null;
        }
      })();
      windowState.inFlight = requestPromise;
      return requestPromise;
    }

    function activate() {
      const windowState = state.get(currentWindow);
      if (windowState.cache !== null) {
        renderCached(currentWindow);
        return Promise.resolve({ok: true, cached: true, payload: windowState.cache});
      }
      return request(currentWindow);
    }

    function refresh() {
      return request(currentWindow);
    }

    function selectWindow(windowName) {
      analyticsPath(windowName);
      currentWindow = windowName;
      updateButtons();
      const windowState = state.get(windowName);
      if (windowState.cache !== null) {
        renderCached(windowName);
        return Promise.resolve({ok: true, cached: true, payload: windowState.cache});
      }
      return request(windowName);
    }

    for (const button of document.querySelectorAll("[data-analytics-window]")) {
      button.addEventListener("click", () => {
        const selection = selectWindow(button.dataset.analyticsWindow);
        if (selection && typeof selection.catch === "function") selection.catch(() => {});
        return selection;
      });
    }
    const refreshButton = document.getElementById("analytics-refresh");
    if (refreshButton) {
      refreshButton.addEventListener("click", () => {
        const result = refresh();
        if (result && typeof result.catch === "function") result.catch(() => {});
        return result;
      });
    }
    updateButtons();
    return {activate, refresh, selectWindow};
  }

  return {
    analyticsPath,
    drawAnalyticsTrend,
    mountDashboardAnalytics,
    presentAnalytics,
  };
});
