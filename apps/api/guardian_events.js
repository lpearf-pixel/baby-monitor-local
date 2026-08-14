(function exposeGuardianEvents(root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BabyMonitorGuardianEvents = api;
  if (root.document) {
    const mount = () => api.mountGuardianEvents({
      document: root.document,
      fetch: root.fetch.bind(root),
      setInterval: root.setInterval.bind(root),
    });
    if (root.document.readyState === "loading") {
      root.document.addEventListener("DOMContentLoaded", mount, {once: true});
    } else {
      mount();
    }
  }
})(globalThis, function createGuardianEventsApi() {
  "use strict";

  const riskLabels = new Map([
    ["face_not_visible", "遮脸风险"],
    ["prone_candidate", "趴睡风险"],
    ["outside_candidate", "离床风险"],
  ]);
  const evidenceLabels = new Map([
    ["collecting", "采集中"],
    ["ready", "已就绪"],
    ["failed", "失败"],
    ["interrupted", "中断"],
    ["unavailable", "无证据"],
  ]);
  const eventKeys = [
    "adult_intervention_count",
    "event_id",
    "evidence_state",
    "opened_at",
    "recovered_at",
    "risk_kind",
    "severity",
    "state",
    "updated_at",
  ];

  function requireClosedEvent(event) {
    if (!event || typeof event !== "object" || Array.isArray(event)) {
      throw new TypeError("closed guardian event required");
    }
    const keys = Object.keys(event).sort();
    if (keys.length !== eventKeys.length ||
        keys.some((key, index) => key !== eventKeys[index])) {
      throw new TypeError("closed guardian event required");
    }
    if (typeof event.event_id !== "string" ||
        event.event_id.length < 1 || event.event_id.length > 128 ||
        !riskLabels.has(event.risk_kind) ||
        !["open", "recovered"].includes(event.state) ||
        event.severity !== "high" ||
        typeof event.opened_at !== "string" ||
        typeof event.updated_at !== "string" ||
        (event.recovered_at !== null && typeof event.recovered_at !== "string") ||
        !Number.isInteger(event.adult_intervention_count) ||
        event.adult_intervention_count < 0 ||
        !evidenceLabels.has(event.evidence_state)) {
      throw new TypeError("valid guardian event required");
    }
  }

  function presentGuardianEvents(payload) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload) ||
        typeof payload.generated_at !== "string" ||
        !Array.isArray(payload.events) || payload.events.length > 20) {
      throw new TypeError("valid guardian event list required");
    }
    return payload.events.map((event) => {
      requireClosedEvent(event);
      return {
        eventId: event.event_id,
        riskLabel: riskLabels.get(event.risk_kind),
        stateLabel: event.state === "open" ? "未恢复" : "已恢复",
        open: event.state === "open",
        evidenceLabel: evidenceLabels.get(event.evidence_state),
        updatedAt: event.updated_at,
        interventionCount: event.adult_intervention_count,
      };
    });
  }

  function renderGuardianEvents(document, list, events) {
    if (events.length === 0) {
      list.replaceChildren();
      list.textContent = "暂无 Guardian 事件";
      return;
    }
    const rows = events.map((event) => {
      const row = document.createElement("li");
      row.className = event.open ? "guardian-event is-open" : "guardian-event";
      row.setAttribute("data-event-state", event.open ? "open" : "recovered");

      const title = document.createElement("strong");
      title.textContent = `${event.riskLabel} · ${event.stateLabel}`;
      const detail = document.createElement("p");
      detail.className = "muted";
      detail.textContent = `证据：${event.evidenceLabel} · 更新时间：${event.updatedAt}`;
      const identifier = document.createElement("code");
      identifier.textContent = event.eventId;
      row.append(title, detail, identifier);
      if (event.interventionCount > 0) {
        const intervention = document.createElement("p");
        intervention.className = "muted";
        intervention.textContent = `成人介入：${event.interventionCount}`;
        row.append(intervention);
      }
      return row;
    });
    list.replaceChildren(...rows);
  }

  function mountGuardianEvents(environment) {
    const list = environment.document.getElementById("guardian-events");
    const stale = environment.document.getElementById("guardian-events-stale");
    if (!list || !stale || typeof environment.setInterval !== "function") {
      return null;
    }

    async function refresh() {
      try {
        const response = await environment.fetch("/api/guardian/events");
        if (!response.ok) throw new Error("guardian events unavailable");
        const events = presentGuardianEvents(await response.json());
        renderGuardianEvents(environment.document, list, events);
        stale.hidden = true;
        stale.textContent = "";
        return true;
      } catch (_error) {
        stale.hidden = false;
        stale.textContent = "数据可能已过期";
        return false;
      }
    }

    const initialRefresh = refresh();
    const intervalId = environment.setInterval(refresh, 15000);
    return {initialRefresh, intervalId, refresh};
  }

  return {
    mountGuardianEvents,
    presentGuardianEvents,
    renderGuardianEvents,
  };
});
