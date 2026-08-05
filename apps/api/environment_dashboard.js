(function exposeEnvironmentDashboard(root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BabyMonitorEnvironment = api;
  if (root.document) {
    const mount = () => api.mountEnvironmentDashboard({
      document: root.document,
      fetch: root.fetch.bind(root),
    });
    if (root.document.readyState === "loading") {
      root.document.addEventListener("DOMContentLoaded", mount, {once: true});
    } else {
      mount();
    }
  }
})(globalThis, function createEnvironmentDashboardApi() {
  "use strict";

  function formatValues(temperature, humidity) {
    return `${Number(temperature).toFixed(1)}°C · ${Number(humidity).toFixed(1)}%RH`;
  }

  function presentEnvironment(payload) {
    const current = payload.current_reading ?? null;
    const lastValid = payload.last_valid_reading ?? null;
    const currentText = payload.current_available
      ? formatValues(payload.temperature_c, payload.humidity_rh)
      : "不可用";
    const detailParts = [];
    if (current?.captured_at) detailParts.push(current.captured_at);
    if (current?.confidence_state) detailParts.push(current.confidence_state);
    if (current?.failure_reason) detailParts.push(current.failure_reason);
    if (current?.calibration_version) detailParts.push(current.calibration_version);
    const lastValidText = lastValid
      ? `${formatValues(lastValid.temperature_c, lastValid.humidity_rh)} · ${lastValid.captured_at}`
      : "无最近有效读数";
    const trendPoints = (payload.trend?.buckets ?? []).map((bucket) => ({
      temperature: bucket.temperature_median,
      humidity: bucket.humidity_median,
    }));
    return {
      currentText,
      detailText: detailParts.join(" · "),
      lastValidText,
      trendPoints,
    };
  }

  function trendPath(windowName) {
    if (!["24h", "7d"].includes(windowName)) {
      throw new RangeError("closed trend window required");
    }
    return `/api/environment/trends/${windowName}`;
  }

  function presentIncidents(incidents) {
    return incidents.map((incident) => [
      incident.kind,
      incident.state,
      incident.severity,
      (incident.reasons ?? []).join(","),
    ].join(" · "));
  }

  function drawTrend(canvas, buckets) {
    if (!canvas || typeof canvas.getContext !== "function") return;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.clearRect(0, 0, canvas.width, canvas.height);
    const series = [
      ["temperature_median", "#ff7675"],
      ["humidity_median", "#74b9ff"],
    ];
    for (const [field, color] of series) {
      context.beginPath();
      context.strokeStyle = color;
      let drawing = false;
      buckets.forEach((bucket, index) => {
        const value = bucket[field];
        if (value === null || value === undefined) {
          drawing = false;
          return;
        }
        const x = buckets.length <= 1 ? 0 : index * canvas.width / (buckets.length - 1);
        const y = canvas.height - Math.max(0, Math.min(100, Number(value))) * canvas.height / 100;
        if (!drawing) context.moveTo(x, y);
        else context.lineTo(x, y);
        drawing = true;
      });
      context.stroke();
    }
  }

  function mountEnvironmentDashboard(environment) {
    const currentElement = environment.document.getElementById("environment-current");
    if (!currentElement) return null;
    const detailElement = environment.document.getElementById("environment-detail");
    const lastValidElement = environment.document.getElementById("environment-last-valid");
    const canvas = environment.document.getElementById("environment-trend");
    const incidentsElement = environment.document.getElementById("environment-incidents");
    const hoursButton = environment.document.getElementById("environment-trend-24h");
    const daysButton = environment.document.getElementById("environment-trend-7d");
    let currentWindow = "24h";

    async function refresh() {
      const [currentResponse, trendResponse, incidentsResponse] = await Promise.all([
        environment.fetch("/api/environment/current"),
        environment.fetch(trendPath(currentWindow)),
        environment.fetch("/api/environment/incidents"),
      ]);
      if (!currentResponse.ok || !trendResponse.ok || !incidentsResponse.ok) {
        currentElement.textContent = "环境服务不可用";
        return;
      }
      const current = await currentResponse.json();
      const trend = await trendResponse.json();
      const incidents = await incidentsResponse.json();
      const view = presentEnvironment({...current, trend});
      currentElement.textContent = view.currentText;
      if (detailElement) detailElement.textContent = view.detailText;
      if (lastValidElement) lastValidElement.textContent = view.lastValidText;
      drawTrend(canvas, trend.buckets ?? []);
      if (incidentsElement) {
        const lines = presentIncidents(incidents.incidents ?? []);
        incidentsElement.textContent = lines.length ? lines.join("\n") : "无环境事件";
      }
    }
    if (hoursButton) hoursButton.addEventListener("click", () => {
      currentWindow = "24h";
      refresh().catch(() => {});
    });
    if (daysButton) daysButton.addEventListener("click", () => {
      currentWindow = "7d";
      refresh().catch(() => {});
    });
    refresh().catch(() => {
      currentElement.textContent = "环境服务不可用";
    });
    return {refresh};
  }

  return {
    drawTrend,
    mountEnvironmentDashboard,
    presentEnvironment,
    presentIncidents,
    trendPath,
  };
});
