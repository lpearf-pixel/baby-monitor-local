(function exposeDashboardViewer(root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.BabyMonitorViewer = api;
  if (root.document) {
    const mount = () => api.mountDashboardViewer({
      document: root.document,
      window: root,
      fetch: root.fetch.bind(root),
      setTimeout: root.setTimeout.bind(root),
      clearTimeout: root.clearTimeout.bind(root),
    });
    if (root.document.readyState === "loading") {
      root.document.addEventListener("DOMContentLoaded", mount, {once: true});
    } else {
      mount();
    }
  }
})(globalThis, function createDashboardViewerApi() {
  "use strict";

  function clamp(value, lower, upper) {
    return Math.min(upper, Math.max(lower, value));
  }

  function clampPan({
    x,
    y,
    zoom,
    viewportWidth,
    viewportHeight,
    planeWidth,
    planeHeight,
  }) {
    if (zoom === 1) {
      return {x: 0, y: 0};
    }
    const maxX = Math.max(0, (planeWidth * zoom - viewportWidth) / 2);
    const maxY = Math.max(0, (planeHeight * zoom - viewportHeight) / 2);
    return {
      x: clamp(x, -maxX, maxX),
      y: clamp(y, -maxY, maxY),
    };
  }

  function createViewerModel(measure, render) {
    let current = {zoom: 1, x: 0, y: 0};

    function emit() {
      render({...current});
    }

    function reclamp() {
      const pan = clampPan({...current, ...measure()});
      current = {...current, ...pan};
      emit();
    }

    function setZoom(zoom) {
      if (![1, 2, 3].includes(zoom)) {
        throw new RangeError("zoom must be 1, 2, or 3");
      }
      current = {...current, zoom};
      reclamp();
    }

    function dragBy(x, y) {
      if (current.zoom === 1) {
        return;
      }
      current = {...current, x: current.x + x, y: current.y + y};
      reclamp();
    }

    function reset() {
      current = {zoom: 1, x: 0, y: 0};
      emit();
    }

    emit();
    return {
      dragBy,
      reclamp,
      reset,
      setZoom,
      state: () => ({...current}),
    };
  }

  function mountDashboardViewer(environment) {
    const document = environment.document;
    const window = environment.window;
    const viewer = document.getElementById("viewer");
    const mediaPlane = document.getElementById("media-plane");
    const liveImage = document.getElementById("live-image");
    const hdVideo = document.getElementById("hd-video");
    const hdStatus = document.getElementById("hd-status");
    const fullscreenButton = document.getElementById("fullscreen");
    const ptzStatus = document.getElementById("ptz-status");
    const zoomButtons = Array.from(document.querySelectorAll(".zoom-button"));
    const ptzButtons = Array.from(document.querySelectorAll(".ptz-button"));

    if (!viewer || !mediaPlane || !liveImage || !fullscreenButton) {
      return null;
    }

    let hdPlayer = environment.hdPlayer || null;
    const hdFactory = window.BabyMonitorHdPlayer?.createHdPlayer;
    if (!hdPlayer && hdVideo && hdStatus && typeof hdFactory === "function") {
      hdPlayer = hdFactory({
        MediaSource: window.MediaSource,
        WebSocket: window.WebSocket,
        URL: window.URL,
        fetch: environment.fetch,
        image: liveImage,
        location: window.location,
        setTimeout: environment.setTimeout,
        clearTimeout: environment.clearTimeout || (() => {}),
        statusElement: hdStatus,
        video: hdVideo,
        window,
      });
    }

    let lastMediaZoom = null;

    function selectMediaZoom(zoom) {
      if (!hdPlayer || lastMediaZoom === zoom) return;
      lastMediaZoom = zoom;
      try {
        const result = hdPlayer.selectZoom(zoom);
        if (result && typeof result.catch === "function") result.catch(() => {});
      } catch (_error) {
        return;
      }
    }

    function measure() {
      return {
        viewportWidth: viewer.clientWidth,
        viewportHeight: viewer.clientHeight,
        planeWidth: mediaPlane.offsetWidth,
        planeHeight: mediaPlane.offsetHeight,
      };
    }

    function render(state) {
      if (state.x === 0 && state.y === 0) {
        mediaPlane.style.transform =
          `translate3d(-50%, -50%, 0) scale(${state.zoom})`;
      } else {
        mediaPlane.style.transform =
          `translate3d(calc(-50% + ${state.x}px), ` +
          `calc(-50% + ${state.y}px), 0) scale(${state.zoom})`;
      }
      viewer.classList.toggle("is-zoomed", state.zoom > 1);
      for (const button of zoomButtons) {
        button.setAttribute(
          "aria-pressed",
          String(Number(button.dataset.zoom) === state.zoom),
        );
      }
      selectMediaZoom(state.zoom);
    }

    const model = createViewerModel(measure, render);

    for (const button of zoomButtons) {
      button.addEventListener("click", () => {
        model.setZoom(Number(button.dataset.zoom));
      });
    }

    let pointerId = null;
    let lastX = 0;
    let lastY = 0;

    viewer.addEventListener("pointerdown", (event) => {
      if (
        model.state().zoom === 1 ||
        event.button !== 0 ||
        (event.target !== viewer && event.target.closest?.("button"))
      ) {
        return;
      }
      pointerId = event.pointerId;
      lastX = event.clientX;
      lastY = event.clientY;
      viewer.setPointerCapture(pointerId);
      viewer.classList.toggle("is-dragging", true);
      event.preventDefault();
    });

    viewer.addEventListener("pointermove", (event) => {
      if (event.pointerId !== pointerId) return;
      model.dragBy(event.clientX - lastX, event.clientY - lastY);
      lastX = event.clientX;
      lastY = event.clientY;
      event.preventDefault();
    });

    function finishDrag(event) {
      if (event.pointerId !== pointerId) return;
      viewer.releasePointerCapture(pointerId);
      pointerId = null;
      viewer.classList.toggle("is-dragging", false);
    }

    viewer.addEventListener("pointerup", finishDrag);
    viewer.addEventListener("pointercancel", finishDrag);
    window.addEventListener("resize", model.reclamp);

    const fullscreenAvailable =
      typeof viewer.requestFullscreen === "function" &&
      typeof document.exitFullscreen === "function";
    let wasFullscreen = false;

    function updateFullscreenState() {
      const isFullscreen = document.fullscreenElement === viewer;
      fullscreenButton.setAttribute(
        "aria-label",
        isFullscreen ? "退出全屏" : "进入全屏",
      );
      fullscreenButton.textContent = isFullscreen ? "退出全屏" : "全屏";
      if (wasFullscreen && !isFullscreen) {
        model.reset();
      }
      wasFullscreen = isFullscreen;
    }

    async function toggleFullscreen() {
      if (!fullscreenAvailable) return;
      try {
        if (document.fullscreenElement === viewer) {
          await document.exitFullscreen();
        } else {
          await viewer.requestFullscreen();
        }
      } catch (_error) {
        return;
      }
    }

    if (!fullscreenAvailable) {
      fullscreenButton.disabled = true;
      fullscreenButton.setAttribute("aria-disabled", "true");
    }
    fullscreenButton.addEventListener("click", toggleFullscreen);
    liveImage.addEventListener("dblclick", toggleFullscreen);
    if (hdVideo) hdVideo.addEventListener("dblclick", toggleFullscreen);
    document.addEventListener("fullscreenchange", updateFullscreenState);
    updateFullscreenState();

    const stablePtzCodes = new Set([
      "PTZ_OK",
      "PTZ_BUSY",
      "PTZ_DISABLED",
      "PTZ_UNAVAILABLE",
      "PTZ_TIMEOUT",
    ]);
    const closedDirections = new Set(["up", "down", "left", "right"]);
    let ptzPending = false;

    function setPtzDisabled(disabled) {
      for (const button of ptzButtons) {
        button.disabled = disabled;
      }
    }

    async function sendPtzStep(direction) {
      if (ptzPending || !closedDirections.has(direction)) return;
      ptzPending = true;
      setPtzDisabled(true);
      let code = "PTZ_UNAVAILABLE";
      let cooldownMs = 0;
      try {
        const response = await environment.fetch("/api/ptz/step", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({direction}),
        });
        const payload = await response.json();
        if (stablePtzCodes.has(payload?.result)) {
          code = payload.result;
        }
        if (code === "PTZ_OK") {
          const requestedCooldown = Number(payload?.cooldown_ms);
          if (Number.isFinite(requestedCooldown)) {
            cooldownMs = clamp(Math.round(requestedCooldown), 0, 5000);
          }
        }
      } catch (_error) {
        code = "PTZ_UNAVAILABLE";
      }

      if (ptzStatus) ptzStatus.textContent = code;
      if (cooldownMs > 0) {
        environment.setTimeout(() => {
          ptzPending = false;
          setPtzDisabled(false);
        }, cooldownMs);
      } else {
        ptzPending = false;
        setPtzDisabled(false);
      }
    }

    for (const button of ptzButtons) {
      button.addEventListener("click", () => sendPtzStep(button.dataset.direction));
    }

    return {hdPlayer, model};
  }

  return {clampPan, createViewerModel, mountDashboardViewer};
});
