(function exposeDashboardObservation(root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BabyMonitorDashboardObservation = api;
})(globalThis, function createDashboardObservationApi() {
  "use strict";

  const states = new Set(["available", "stale", "no_result", "failed", "worker_restarted"]);
  const visibility = new Set(["visible", "partial", "not_visible", "uncertain"]);
  const freshness = new Set(["fresh", "stale", "unknown"]);
  const reasons = new Set(["none", "no_review_yet", "review_expired", "review_failed", "review_timeout", "worker_restarted"]);
  const keys = [
    "baby_visibility", "freshness", "input_frame_captured_at", "reason_code",
    "result_completed_at", "schema_version", "state", "written_at",
  ];

  function exactObject(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
    const actual = Object.keys(value).sort();
    return actual.length === keys.length && actual.every((key, index) => key === keys.slice().sort()[index]);
  }

  function timestamp(value) {
    return typeof value === "string" && /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
  }

  function presentObservation(payload) {
    if (!exactObject(payload) || payload.schema_version !== 1 || !states.has(payload.state) ||
        (payload.baby_visibility !== null && !visibility.has(payload.baby_visibility)) ||
        !freshness.has(payload.freshness) || !reasons.has(payload.reason_code) || !timestamp(payload.written_at)) {
      throw new TypeError("closed visual observation required");
    }
    const available = payload.state === "available";
    const stale = payload.state === "stale";
    if ((available && (payload.baby_visibility === null || !timestamp(payload.input_frame_captured_at) || !timestamp(payload.result_completed_at) || payload.freshness !== "fresh" || payload.reason_code !== "none")) ||
        (stale && (payload.baby_visibility === null || !timestamp(payload.input_frame_captured_at) || !timestamp(payload.result_completed_at) || payload.freshness !== "stale" || payload.reason_code !== "review_expired")) ||
        (!available && !stale && (payload.baby_visibility !== null || payload.input_frame_captured_at !== null || payload.result_completed_at !== null || payload.freshness !== "unknown"))) {
      throw new TypeError("closed visual observation required");
    }
    if (payload.state === "no_result" && payload.reason_code !== "no_review_yet") throw new TypeError("closed visual observation required");
    if (payload.state === "failed" && !["review_failed", "review_timeout"].includes(payload.reason_code)) throw new TypeError("closed visual observation required");
    if (payload.state === "worker_restarted" && payload.reason_code !== "worker_restarted") throw new TypeError("closed visual observation required");

    const visibilityLabel = {
      visible: "宝宝可见",
      partial: "宝宝部分可见",
      not_visible: "未观察到宝宝",
      uncertain: "宝宝可见性不确定",
    }[payload.baby_visibility];
    let label = "暂无最近一次观察";
    if (payload.state === "available") label = `最近一次观察：${visibilityLabel}`;
    if (payload.state === "stale") label = `最近一次观察：${visibilityLabel}（已过期）`;
    if (payload.state === "failed") label = "最近一次观察：语义复核失败，未生成新结果";
    if (payload.state === "worker_restarted") label = "最近一次观察：视觉 worker 刚重启，等待新结果";
    const detail = payload.input_frame_captured_at && payload.result_completed_at
      ? `帧采集时间：${payload.input_frame_captured_at} · 结果完成时间：${payload.result_completed_at}`
      : "未生成新的语义结果";
    return {state: payload.state, label, detail, capturedAt: payload.input_frame_captured_at, completedAt: payload.result_completed_at};
  }

  function renderObservation(document, payload) {
    const element = document.getElementById("recent-observation");
    if (!element) return false;
    const rendered = payload === null
      ? {state: "unavailable", label: "最近一次观察：当前不可用"}
      : presentObservation(payload);
    element.textContent = rendered.label;
    if (element.dataset) element.dataset.state = rendered.state;
    const detail = document.getElementById("recent-observation-detail");
    if (detail) detail.textContent = rendered.detail;
    return true;
  }

  return {presentObservation, renderObservation};
});
