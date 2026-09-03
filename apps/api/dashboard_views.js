(function exposeDashboardViews(root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BabyMonitorDashboardViews = api;
})(globalThis, function createDashboardViewsApi() {
  "use strict";

  const sourceLabels = new Map([
    ["guardian", "Guardian"],
    ["environment", "环境"],
    ["system", "系统"],
  ]);
  const priorityLabels = new Map([
    ["critical", "高风险"],
    ["warning", "需检查"],
    ["info", "信息"],
  ]);
  const alertKindLabels = new Map([
    ["face_not_visible", "遮脸风险"],
    ["prone_candidate", "趴睡风险"],
    ["outside_candidate", "离床风险"],
    ["environment_range", "环境范围异常"],
    ["environment_unreadable", "环境读数不可用"],
    ["camera_status", "摄像头状态"],
    ["guardian_query_status", "Guardian 查询状态"],
    ["environment_query_status", "环境查询状态"],
    ["notification_queue_status", "通知队列状态"],
    ["calibration_status", "标定状态"],
  ]);
  const evidenceLabels = new Map([
    ["collecting", "采集中"],
    ["ready", "已就绪"],
    ["failed", "失败"],
    ["interrupted", "中断"],
    ["unavailable", "不可用"],
  ]);
  const notificationLabels = new Map([
    ["pending", "待发送"],
    ["delivered", "已送达"],
    ["rejected", "已拒绝"],
    ["mixed", "部分送达"],
    ["unavailable", "不可用"],
  ]);
  const resolutionLabels = new Map([
    ["explicit_safe", "已确认安全"],
    ["subject_outside", "目标已离开"],
  ]);
  const componentStateLabels = new Map([
    ["healthy", "正常"],
    ["degraded", "降级"],
    ["unavailable", "不可用"],
    ["disabled", "已禁用"],
  ]);
  const componentLabels = new Map([
    ["camera", "摄像头"],
    ["guardian_query", "Guardian 查询"],
    ["environment", "环境"],
    ["gauge_calibration", "温湿度计标定"],
    ["notification_queue", "通知队列"],
    ["visual", "视觉分析"],
    ["voice", "语音"],
    ["camera_reply", "摄像头回复"],
  ]);
  const reasonLabels = new Map([
    ["temperature_low", "温度偏低"], ["temperature_high", "温度偏高"],
    ["temperature_critical_low", "温度严重偏低"], ["temperature_critical_high", "温度严重偏高"],
    ["humidity_low", "湿度偏低"], ["humidity_high", "湿度偏高"],
    ["humidity_critical_low", "湿度严重偏低"], ["humidity_critical_high", "湿度严重偏高"],
    ["reading_unavailable", "读数不可用"], ["no_new_reading", "没有新读数"],
    ["calibration_missing", "缺少标定"], ["calibration_invalid", "标定无效"],
    ["frame_source_unavailable", "画面来源不可用"], ["frame_stale", "画面已过期"],
    ["roi_out_of_bounds", "测量区域越界"], ["too_dark", "画面过暗"], ["glare", "眩光"],
    ["occluded", "被遮挡"], ["needle_not_found", "未找到指针"],
    ["insufficient_valid_frames", "有效画面不足"], ["inconsistent_frames", "画面不一致"],
    ["low_confidence", "置信度不足"], ["internal_error", "内部错误"],
    ["environment_no_reading", "没有环境读数"], ["camera_online", "摄像头在线"],
    ["camera_offline", "摄像头离线"], ["camera_unavailable", "摄像头不可用"],
    ["guardian_query_available", "Guardian 查询可用"], ["guardian_query_unavailable", "Guardian 查询不可用"],
    ["environment_available", "环境可用"], ["environment_unavailable", "环境不可用"],
    ["notification_queue_empty", "通知队列为空"], ["notification_queue_pending", "通知等待发送"],
    ["notification_query_unavailable", "通知查询不可用"], ["calibration_available", "标定可用"],
    ["camera_reply_disabled", "摄像头回复已禁用"], ["camera_reply_status_unavailable", "摄像头回复状态不可用"],
  ]);
  const alertKeys = [
    "adult_intervention_count", "alert_id", "evidence_state", "kind", "notification_state",
    "opened_at", "priority", "reason_codes", "recovered_at", "resolution_cause", "source",
    "state", "updated_at",
  ];
  const componentKeys = ["component_id", "reason_code", "state", "updated_at"];
  const environmentKeys = [
    "captured_at", "failure_reason", "fresh_until", "humidity_rh", "last_valid_captured_at",
    "last_valid_humidity_rh", "last_valid_temperature_c", "state", "temperature_c",
  ];
  const overviewKeys = [
    "attention", "components", "environment", "generated_at", "guardian_open_count",
    "open_alert_count", "recent_activity", "schema_version", "today_recovered_count",
  ];
  const alertListKeys = ["alerts", "generated_at", "schema_version"];
  const systemKeys = ["components", "generated_at", "schema_version"];
  const sourceFilters = new Set(["all", ...sourceLabels.keys()]);
  const stateFilters = new Set(["all", "open", "recovered"]);

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function hasExactKeys(value, keys) {
    if (!isRecord(value)) return false;
    const actual = Object.keys(value).sort();
    return actual.length === keys.length && actual.every((key, index) => key === keys[index]);
  }

  function validTimestamp(value) {
    return typeof value === "string" && /(?:Z|[+-]\d\d:\d\d)$/.test(value) && !Number.isNaN(Date.parse(value));
  }

  function validNullableTimestamp(value) {
    return value === null || validTimestamp(value);
  }

  function validNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function validNullableNumber(value) {
    return value === null || validNumber(value);
  }

  function nonNegativeInteger(value) {
    return Number.isInteger(value) && value >= 0;
  }

  function requireAlert(value) {
    if (!hasExactKeys(value, alertKeys) || typeof value.alert_id !== "string" ||
        value.alert_id.length < 1 || value.alert_id.length > 160 || !sourceLabels.has(value.source) ||
        !alertKindLabels.has(value.kind) || !["open", "recovered"].includes(value.state) ||
        !priorityLabels.has(value.priority) || !validTimestamp(value.opened_at) ||
        !validTimestamp(value.updated_at) || !validNullableTimestamp(value.recovered_at) ||
        !Array.isArray(value.reason_codes) || value.reason_codes.length > 8 ||
        !value.reason_codes.every((reason) => reasonLabels.has(reason)) ||
        (value.adult_intervention_count !== null && !nonNegativeInteger(value.adult_intervention_count)) ||
        (value.evidence_state !== null && !evidenceLabels.has(value.evidence_state)) ||
        (value.notification_state !== null && !notificationLabels.has(value.notification_state)) ||
        (value.resolution_cause !== null && !resolutionLabels.has(value.resolution_cause))) {
      throw new TypeError("closed dashboard alert required");
    }
    const openedAt = Date.parse(value.opened_at);
    const updatedAt = Date.parse(value.updated_at);
    if (updatedAt < openedAt || (value.state === "open" &&
        (value.recovered_at !== null || value.resolution_cause !== null)) ||
        (value.state === "recovered" && (value.recovered_at === null ||
        Date.parse(value.recovered_at) < openedAt || Date.parse(value.recovered_at) > updatedAt))) {
      throw new TypeError("closed dashboard alert required");
    }
  }

  function requireComponent(value) {
    if (!hasExactKeys(value, componentKeys) || !componentLabels.has(value.component_id) ||
        !componentStateLabels.has(value.state) || !reasonLabels.has(value.reason_code) ||
        !validTimestamp(value.updated_at)) {
      throw new TypeError("closed dashboard component required");
    }
  }

  function presentAlert(value) {
    requireAlert(value);
    return {
      alertId: value.alert_id,
      source: value.source,
      sourceLabel: sourceLabels.get(value.source),
      kind: value.kind,
      kindLabel: alertKindLabels.get(value.kind),
      state: value.state,
      stateLabel: value.state === "open" ? "未恢复" : "已恢复",
      priority: value.priority,
      priorityLabel: priorityLabels.get(value.priority),
      openedAt: value.opened_at,
      updatedAt: value.updated_at,
      recoveredAt: value.recovered_at,
      reasonLabels: value.reason_codes.map((reason) => reasonLabels.get(reason)),
      interventionCount: value.adult_intervention_count,
      evidenceLabel: value.evidence_state === null ? null : evidenceLabels.get(value.evidence_state),
      notificationLabel: value.notification_state === null ? null : notificationLabels.get(value.notification_state),
      resolutionLabel: value.resolution_cause === null ? null : resolutionLabels.get(value.resolution_cause),
    };
  }

  function presentComponent(value) {
    requireComponent(value);
    return {
      componentId: value.component_id,
      componentLabel: componentLabels.get(value.component_id),
      state: value.state,
      stateLabel: componentStateLabels.get(value.state),
      reasonLabel: reasonLabels.get(value.reason_code),
      updatedAt: value.updated_at,
    };
  }

  function requireEnvironment(value) {
    if (!hasExactKeys(value, environmentKeys) || !["available", "unavailable"].includes(value.state) ||
        !validNullableNumber(value.temperature_c) || !validNullableNumber(value.humidity_rh) ||
        !validNullableTimestamp(value.captured_at) || !validNullableTimestamp(value.fresh_until) ||
        (value.failure_reason !== null && !reasonLabels.has(value.failure_reason)) ||
        !validNullableNumber(value.last_valid_temperature_c) ||
        !validNullableNumber(value.last_valid_humidity_rh) || !validNullableTimestamp(value.last_valid_captured_at)) {
      throw new TypeError("closed dashboard overview required");
    }
    const currentValues = [value.temperature_c, value.humidity_rh, value.captured_at, value.fresh_until];
    const currentMeasurements = [value.temperature_c, value.humidity_rh];
    const lastValues = [value.last_valid_temperature_c, value.last_valid_humidity_rh, value.last_valid_captured_at];
    if ((value.state === "available" && (currentValues.some((item) => item === null) ||
        value.failure_reason !== null || Date.parse(value.fresh_until) <= Date.parse(value.captured_at))) ||
        (value.state === "unavailable" && currentMeasurements.some((item) => item !== null)) ||
        (lastValues.some((item) => item === null) && lastValues.some((item) => item !== null))) {
      throw new TypeError("closed dashboard overview required");
    }
  }

  function presentEnvironment(value) {
    requireEnvironment(value);
    return {
      currentText: value.state === "available"
        ? formatValues(value.temperature_c, value.humidity_rh) : "不可用",
      detailText: value.state === "available" ? "当前读数有效" : reasonLabels.get(value.failure_reason),
      lastValidText: value.last_valid_temperature_c === null ? "无最近有效读数"
        : formatValues(value.last_valid_temperature_c, value.last_valid_humidity_rh),
      lastValidCapturedAt: value.last_valid_captured_at,
    };
  }

  function presentOverview(payload) {
    if (!hasExactKeys(payload, overviewKeys) || payload.schema_version !== 1 || !validTimestamp(payload.generated_at) ||
        !nonNegativeInteger(payload.open_alert_count) ||
        (payload.guardian_open_count !== null && !nonNegativeInteger(payload.guardian_open_count)) ||
        (payload.today_recovered_count !== null && !nonNegativeInteger(payload.today_recovered_count)) ||
        !Array.isArray(payload.components) || payload.components.length > 8 ||
        !Array.isArray(payload.recent_activity) || payload.recent_activity.length > 10 ||
        (payload.attention !== null && (!hasExactKeys(payload.attention, ["additional_open_count", "alert"]) ||
        !nonNegativeInteger(payload.attention.additional_open_count)))) {
      throw new TypeError("closed dashboard overview required");
    }
    const componentViews = payload.components.map(presentComponent);
    const recentActivity = payload.recent_activity.map(presentAlert);
    const attention = payload.attention === null ? null : {
      alert: presentAlert(payload.attention.alert),
      additionalOpenCount: payload.attention.additional_open_count,
    };
    if (new Set(componentViews.map((item) => item.componentId)).size !== componentViews.length ||
        new Set(recentActivity.map((item) => item.alertId)).size !== recentActivity.length) {
      throw new TypeError("closed dashboard overview required");
    }
    const componentsNeedAttention = componentViews.some((item) => item.state === "degraded" || item.state === "unavailable");
    const healthText = attention?.alert.priority === "critical" ? "存在已确认高风险警报"
      : attention ? "存在需检查的警报"
      : componentsNeedAttention ? "系统组件需要检查"
      : "当前未发现未恢复警报";
    return {
      generatedAt: payload.generated_at,
      attention,
      openAlertCount: payload.open_alert_count,
      guardianOpenCount: payload.guardian_open_count,
      todayRecoveredCount: payload.today_recovered_count,
      environment: presentEnvironment(payload.environment),
      components: componentViews,
      recentActivity,
      healthText,
    };
  }

  function presentAlerts(payload) {
    if (!hasExactKeys(payload, alertListKeys) || payload.schema_version !== 1 || !validTimestamp(payload.generated_at) ||
        !Array.isArray(payload.alerts) || payload.alerts.length > 100) {
      throw new TypeError("closed dashboard alert list required");
    }
    const alerts = payload.alerts.map(presentAlert);
    if (new Set(alerts.map((item) => item.alertId)).size !== alerts.length) {
      throw new TypeError("closed dashboard alert list required");
    }
    return {generatedAt: payload.generated_at, alerts};
  }

  function presentSystem(payload) {
    if (!hasExactKeys(payload, systemKeys) || payload.schema_version !== 1 || !validTimestamp(payload.generated_at) ||
        !Array.isArray(payload.components) || payload.components.length > 8) {
      throw new TypeError("closed dashboard system required");
    }
    const components = payload.components.map(presentComponent);
    if (new Set(components.map((item) => item.componentId)).size !== components.length) {
      throw new TypeError("closed dashboard system required");
    }
    return {generatedAt: payload.generated_at, components};
  }

  function formatValues(temperature, humidity) {
    return `${Number(temperature).toFixed(1)}°C · ${Number(humidity).toFixed(1)}%RH`;
  }

  function formatTimestamp(timestamp, options) {
    const formatter = options?.dateFormatter || new Intl.DateTimeFormat(undefined, {
      dateStyle: "short", timeStyle: "short",
    });
    return formatter.format(new Date(timestamp));
  }

  function setText(document, id, text) {
    const element = document.getElementById(id);
    if (element) element.textContent = text;
    return element;
  }

  function appendAlertRow(document, alertView, {highlighted = false} = {}) {
    const row = document.createElement("li");
    row.className = `dashboard-alert priority-${alertView.priority}${highlighted ? " is-target" : ""}`;
    row.dataset.alertId = alertView.alertId;
    row.dataset.alertSource = alertView.source;
    row.dataset.alertState = alertView.state;
    const title = document.createElement("strong");
    title.textContent = `${alertView.priorityLabel} · ${alertView.kindLabel} · ${alertView.stateLabel}`;
    const detail = document.createElement("p");
    detail.className = "muted";
    const details = [alertView.sourceLabel, ...alertView.reasonLabels];
    if (alertView.evidenceLabel) details.push(`证据：${alertView.evidenceLabel}`);
    if (alertView.notificationLabel) details.push(`通知：${alertView.notificationLabel}`);
    if (alertView.resolutionLabel) details.push(`恢复：${alertView.resolutionLabel}`);
    detail.textContent = details.join(" · ");
    const identifier = document.createElement("code");
    identifier.textContent = alertView.alertId;
    row.append(title, detail, identifier);
    return row;
  }

  function appendComponentRow(document, componentView, options) {
    const row = document.createElement("article");
    row.className = `component-card component-${componentView.state}`;
    row.dataset.componentId = componentView.componentId;
    const title = document.createElement("strong");
    title.textContent = `${componentView.componentLabel} · ${componentView.stateLabel}`;
    const detail = document.createElement("p");
    detail.className = "muted";
    detail.textContent = `${componentView.reasonLabel} · 更新时间：${formatTimestamp(componentView.updatedAt, options)}`;
    row.append(title, detail);
    return row;
  }

  function renderOverview(document, payload, options = {}) {
    const view = presentOverview(payload);
    const attention = document.getElementById("global-attention");
    if (attention) {
      attention.replaceChildren();
      attention.hidden = view.attention === null;
      if (view.attention) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "attention-button";
        button.dataset.alertTarget = view.attention.alert.alertId;
        button.textContent = `${view.attention.alert.priorityLabel}：${view.attention.alert.kindLabel}` +
          (view.attention.additionalOpenCount > 0
            ? ` · 另有 ${view.attention.additionalOpenCount} 项未恢复警报` : "");
        attention.append(button);
      }
    }
    const count = setText(document, "alert-count", String(view.openAlertCount));
    if (count) count.hidden = view.openAlertCount === 0;
    setText(document, "environment-current", view.environment.currentText);
    setText(document, "environment-detail", view.environment.detailText);
    setText(document, "environment-last-valid", view.environment.lastValidCapturedAt === null
      ? view.environment.lastValidText
      : `${view.environment.lastValidText} · ${formatTimestamp(view.environment.lastValidCapturedAt, options)}`);
    setText(document, "dashboard-health", view.healthText);
    setText(document, "overview-guardian-counts", `未恢复：${view.guardianOpenCount === null ? "不可用" : view.guardianOpenCount} · 今日已恢复：${view.todayRecoveredCount === null ? "不可用" : view.todayRecoveredCount}`);
    renderComponentCollection(document, "overview-components-list", view.components, options);
    renderAlertCollection(document, "overview-recent-list", view.recentActivity, null);
    setText(document, "overview-updated", formatTimestamp(view.generatedAt, options));
    clearStale(document, "overview");
    return view;
  }

  function renderAlerts(document, payload, options = {}) {
    const view = presentAlerts(payload);
    const sourceFilter = options.sourceFilter ?? "all";
    const stateFilter = options.stateFilter ?? "all";
    if (!sourceFilters.has(sourceFilter) || !stateFilters.has(stateFilter)) {
      throw new TypeError("closed dashboard alert filter required");
    }
    renderAlertCollection(document, "alerts-list", view.alerts, options.highlightAlertId ?? null);
    applyAlertFilters(document, sourceFilter, stateFilter);
    setText(document, "alerts-updated", formatTimestamp(view.generatedAt, options));
    clearStale(document, "alerts");
    return view;
  }

  function renderSystem(document, payload, options = {}) {
    const view = presentSystem(payload);
    renderComponentCollection(document, "system-components", view.components, options);
    setText(document, "system-updated", formatTimestamp(view.generatedAt, options));
    clearStale(document, "system");
    return view;
  }

  function renderAlertCollection(document, elementId, alerts, highlightedAlertId) {
    const list = document.getElementById(elementId);
    if (!list) return;
    if (alerts.length === 0) {
      renderListStatus(document, list, "暂无警报");
      return;
    }
    list.replaceChildren(...alerts.map((item) => appendAlertRow(document, item, {
      highlighted: highlightedAlertId === item.alertId,
    })));
  }

  function renderComponentCollection(document, elementId, components, options) {
    const container = document.getElementById(elementId);
    if (!container) return;
    if (components.length === 0) {
      container.replaceChildren();
      container.textContent = "暂无组件状态";
      return;
    }
    container.replaceChildren(...components.map((item) => appendComponentRow(document, item, options)));
  }

  function renderListStatus(document, list, text) {
    const item = document.createElement("li");
    item.className = "collection-status muted";
    item.textContent = text;
    list.replaceChildren(item);
  }

  function renderTextStatus(document, elementId, text) {
    const element = document.getElementById(elementId);
    if (!element) return;
    element.replaceChildren();
    element.textContent = text;
  }

  function filterAlerts(alerts, sourceFilter = "all", stateFilter = "all") {
    if (!sourceFilters.has(sourceFilter) || !stateFilters.has(stateFilter)) {
      throw new TypeError("closed dashboard alert filter required");
    }
    if (!Array.isArray(alerts)) throw new TypeError("closed dashboard alert required");
    return alerts.filter((alertView) => {
      if (!alertView || !sourceLabels.has(alertView.source) || !["open", "recovered"].includes(alertView.state)) {
        throw new TypeError("closed dashboard alert required");
      }
      return (sourceFilter === "all" || alertView.source === sourceFilter) &&
        (stateFilter === "all" || alertView.state === stateFilter);
    });
  }

  function applyAlertFilters(document, sourceFilter = "all", stateFilter = "all") {
    if (!sourceFilters.has(sourceFilter) || !stateFilters.has(stateFilter)) {
      throw new TypeError("closed dashboard alert filter required");
    }
    const list = document.getElementById("alerts-list");
    if (!list) return 0;
    let visibleCount = 0;
    for (const row of list.children) {
      const visible = sourceLabels.has(row.dataset.alertSource) && ["open", "recovered"].includes(row.dataset.alertState) &&
        (sourceFilter === "all" || row.dataset.alertSource === sourceFilter) &&
        (stateFilter === "all" || row.dataset.alertState === stateFilter);
      row.hidden = !visible;
      if (visible) visibleCount += 1;
    }
    return visibleCount;
  }

  function clearStale(document, section) {
    const stale = document.getElementById(`${section}-stale`);
    if (stale) {
      stale.hidden = true;
      stale.textContent = "";
    }
  }

  function markStale(document, section, lastSuccessAt = null, options = {}) {
    const stale = document.getElementById(`${section}-stale`);
    if (stale) {
      stale.hidden = false;
      stale.textContent = lastSuccessAt === null ? "数据可能已过期"
        : `数据可能已过期 · 上次更新：${formatTimestamp(lastSuccessAt, options)}`;
    }
  }

  function markUnavailable(document, section) {
    if (section === "overview") {
      const attention = document.getElementById("global-attention");
      if (attention) {
        attention.replaceChildren();
        attention.hidden = true;
      }
      const count = setText(document, "alert-count", "");
      if (count) count.hidden = true;
      setText(document, "dashboard-health", "总览数据不可用");
      setText(document, "environment-current", "不可用");
      setText(document, "environment-detail", "当前环境读数不可用");
      setText(document, "environment-last-valid", "无最近有效读数");
      setText(document, "overview-guardian-counts", "未恢复：不可用 · 今日已恢复：不可用");
      renderTextStatus(document, "overview-components-list", "组件状态不可用");
      const recent = document.getElementById("overview-recent-list");
      if (recent) renderListStatus(document, recent, "最近活动不可用");
    } else if (section === "alerts") {
      const alerts = document.getElementById("alerts-list");
      if (alerts) renderListStatus(document, alerts, "警报数据不可用");
      setText(document, "alerts-announcement", "警报数据不可用");
    } else if (section === "system") {
      renderTextStatus(document, "system-components", "系统状态不可用");
    }
    const target = document.getElementById(`${section}-updated`);
    if (target) target.textContent = "数据不可用";
    clearStale(document, section);
  }

  return {
    applyAlertFilters,
    filterAlerts,
    markStale,
    markUnavailable,
    presentAlerts,
    presentOverview,
    presentSystem,
    renderAlerts,
    renderOverview,
    renderSystem,
  };
});
