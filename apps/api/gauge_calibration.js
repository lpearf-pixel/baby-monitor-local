(function exposeGaugeCalibration(root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BabyMonitorGaugeCalibration = api;
  if (root.document) {
    const mount = () => api.mountGaugeCalibration({
      document: root.document,
      fetch: root.fetch.bind(root),
      prompt: root.prompt.bind(root),
      alert: root.alert.bind(root),
    });
    if (root.document.readyState === "loading") {
      root.document.addEventListener("DOMContentLoaded", mount, {once: true});
    } else {
      mount();
    }
  }
})(globalThis, function createGaugeCalibrationApi() {
  "use strict";

  function clamp(value, low, high) {
    return Math.min(high, Math.max(low, value));
  }

  function viewportPointToSource(point, viewport) {
    if (![2, 3].includes(viewport.zoom)) throw new RangeError("zoom must be 2 or 3");
    const visible = 1 / viewport.zoom;
    const left = clamp(viewport.center_x - visible / 2, 0, 1 - visible);
    const top = clamp(viewport.center_y - visible / 2, 0, 1 - visible);
    return {
      x: left + clamp(point.x, 0, 1) * visible,
      y: top + clamp(point.y, 0, 1) * visible,
    };
  }

  function mapFace(face, viewport) {
    if (!face || face.marks.length < 3) throw new Error("each face requires three scale marks");
    return {
      center: viewportPointToSource(face.center, viewport),
      needle_tip: viewportPointToSource(face.needleTip, viewport),
      radius: face.radius / viewport.zoom,
      scale_marks: face.marks.map((mark) => ({
        point: viewportPointToSource(mark.point, viewport),
        angle_degrees: mark.angle_degrees,
        unwrapped_angle_degrees: mark.unwrapped_angle_degrees,
        value: mark.value,
      })),
    };
  }

  function buildCalibrationDraft(input) {
    if (!Array.isArray(input.corners) || input.corners.length !== 4) {
      throw new Error("four gauge corners are required");
    }
    const corners = input.corners.map((point) => viewportPointToSource(point, input.viewport));
    const xs = corners.map((point) => point.x);
    const ys = corners.map((point) => point.y);
    return {
      source_width: input.sourceWidth,
      source_height: input.sourceHeight,
      orientation: input.sourceWidth >= input.sourceHeight ? "landscape" : "portrait",
      zoom: input.viewport.zoom,
      center_x: input.viewport.center_x,
      center_y: input.viewport.center_y,
      gauge_quadrilateral: {
        top_left: corners[0],
        top_right: corners[1],
        bottom_right: corners[2],
        bottom_left: corners[3],
      },
      gauge_rect: {
        x: Math.min(...xs),
        y: Math.min(...ys),
        width: Math.max(...xs) - Math.min(...xs),
        height: Math.max(...ys) - Math.min(...ys),
      },
      humidity: mapFace(input.humidity, input.viewport),
      temperature: mapFace(input.temperature, input.viewport),
    };
  }

  const instructions = [
    "gauge corner 1 (top left)", "gauge corner 2 (top right)",
    "gauge corner 3 (bottom right)", "gauge corner 4 (bottom left)",
    "humidity center", "humidity needle tip",
    "humidity scale mark 1", "humidity scale mark 2", "humidity scale mark 3",
    "temperature center", "temperature needle tip",
    "temperature scale mark 1", "temperature scale mark 2", "temperature scale mark 3",
  ];

  function createWizardModel() {
    const entries = [];

    function addPoint(point, value) {
      if (entries.length >= instructions.length) throw new Error("wizard is complete");
      const isMark = [6, 7, 8, 11, 12, 13].includes(entries.length);
      if (isMark && !Number.isFinite(value)) throw new Error("scale mark requires a numeric value");
      entries.push({point: {x: point.x, y: point.y}, value: isMark ? Number(value) : null});
    }

    function undo() {
      entries.pop();
    }

    function face(start) {
      const center = entries[start].point;
      const needleTip = entries[start + 1].point;
      let previous = null;
      const marks = entries.slice(start + 2, start + 5).map((entry) => {
        let angle = Math.atan2(
          entry.point.y - center.y,
          entry.point.x - center.x,
        ) * 180 / Math.PI;
        angle = (angle + 360) % 360;
        let unwrapped = angle;
        while (previous !== null && unwrapped <= previous) unwrapped += 360;
        previous = unwrapped;
        return {
          point: entry.point,
          angle_degrees: angle,
          unwrapped_angle_degrees: unwrapped,
          value: entry.value,
        };
      });
      return {
        center,
        needleTip,
        radius: Math.hypot(needleTip.x - center.x, needleTip.y - center.y) / 0.8,
        marks,
      };
    }

    function buildInput({sourceWidth, sourceHeight, viewport}) {
      if (entries.length !== instructions.length) throw new Error("wizard is incomplete");
      return {
        sourceWidth,
        sourceHeight,
        viewport,
        corners: entries.slice(0, 4).map((entry) => entry.point),
        humidity: face(4),
        temperature: face(9),
      };
    }

    function state() {
      return {
        count: entries.length,
        ready: entries.length === instructions.length,
        instruction: entries.length < instructions.length
          ? instructions[entries.length]
          : "review and save",
      };
    }
    return {addPoint, buildInput, state, undo};
  }

  function mountGaugeCalibration(environment) {
    const button = environment.document.getElementById("gauge-calibration");
    const snapshotLink = environment.document.getElementById("snapshot-link");
    if (!button || !snapshotLink) return null;
    button.addEventListener("click", () => {
      const snapshotUrl = new URL(snapshotLink.getAttribute("href"), "https://local.invalid");
      const viewport = {
        zoom: Number(snapshotUrl.searchParams.get("zoom")),
        center_x: Number(snapshotUrl.searchParams.get("center_x")),
        center_y: Number(snapshotUrl.searchParams.get("center_y")),
      };
      if (![2, 3].includes(viewport.zoom)) {
        environment.alert("请先选择 2× 或 3× 并把表盘移到清晰位置。");
        return;
      }
      const wizard = createWizardModel();
      const dialog = environment.document.createElement("dialog");
      dialog.innerHTML = `
        <p data-role="instruction"></p>
        <img data-role="image" alt="本地冻结表盘标定图">
        <div><button data-role="undo" type="button">撤销</button>
        <button data-role="cancel" type="button">取消</button>
        <button data-role="save" type="button" disabled>保存标定</button></div>`;
      const image = dialog.querySelector('[data-role="image"]');
      const instruction = dialog.querySelector('[data-role="instruction"]');
      const save = dialog.querySelector('[data-role="save"]');
      const refresh = () => {
        instruction.textContent = wizard.state().instruction;
        save.disabled = !wizard.state().ready;
      };
      image.src = snapshotLink.getAttribute("href");
      image.addEventListener("click", (event) => {
        const rect = image.getBoundingClientRect();
        const point = {
          x: clamp((event.clientX - rect.left) / rect.width, 0, 1),
          y: clamp((event.clientY - rect.top) / rect.height, 0, 1),
        };
        const needsValue = [6, 7, 8, 11, 12, 13].includes(wizard.state().count);
        const value = needsValue
          ? Number(environment.prompt("输入该刻度值；按数值递增顺序标记。"))
          : undefined;
        try { wizard.addPoint(point, value); } catch (error) {
          environment.alert(String(error));
        }
        refresh();
      });
      dialog.querySelector('[data-role="undo"]').onclick = () => { wizard.undo(); refresh(); };
      dialog.querySelector('[data-role="cancel"]').onclick = () => dialog.remove();
      save.onclick = async () => {
        const input = wizard.buildInput({
          sourceWidth: image.naturalWidth * viewport.zoom,
          sourceHeight: image.naturalHeight * viewport.zoom,
          viewport,
        });
        const response = await environment.fetch("/api/gauge-calibration", {
          method: "PUT",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(buildCalibrationDraft(input)),
        });
        environment.alert(response.ok ? "标定已保存。" : "标定校验失败，请保留点位后重试。");
        if (response.ok) dialog.remove();
      };
      environment.document.body.appendChild(dialog);
      refresh();
      dialog.showModal();
    });
    return {button};
  }

  return {
    buildCalibrationDraft,
    createWizardModel,
    mountGaugeCalibration,
    viewportPointToSource,
  };
});
