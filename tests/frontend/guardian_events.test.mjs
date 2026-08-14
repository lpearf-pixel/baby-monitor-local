import assert from "node:assert/strict";
import {createRequire} from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {
  mountGuardianEvents,
  presentGuardianEvents,
} = require("../../apps/api/guardian_events.js");


class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.className = "";
    this.hidden = false;
    this.textContent = "";
    this.attributes = new Map();
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
    this.textContent = "";
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
}


class FakeDocument {
  constructor() {
    this.elements = new Map([
      ["guardian-events", new FakeElement("ol")],
      ["guardian-events-stale", new FakeElement("p")],
    ]);
    this.elements.get("guardian-events-stale").hidden = true;
  }

  getElementById(id) {
    return this.elements.get(id) ?? null;
  }

  createElement(tagName) {
    return new FakeElement(tagName);
  }
}


function payload(events) {
  return {
    generated_at: "2026-08-13T12:00:00Z",
    events,
  };
}


function event(overrides = {}) {
  return {
    event_id: "event-1",
    risk_kind: "face_not_visible",
    state: "open",
    severity: "high",
    opened_at: "2026-08-13T11:58:00Z",
    updated_at: "2026-08-13T11:59:00Z",
    recovered_at: null,
    adult_intervention_count: 0,
    evidence_state: "collecting",
    ...overrides,
  };
}


test("presenter keeps server order and maps all closed status labels", () => {
  const view = presentGuardianEvents(payload([
    event({event_id: "open", evidence_state: "collecting"}),
    event({event_id: "ready", state: "recovered", evidence_state: "ready"}),
    event({event_id: "failed", state: "recovered", evidence_state: "failed"}),
    event({event_id: "interrupted", state: "recovered", evidence_state: "interrupted"}),
    event({event_id: "none", state: "recovered", evidence_state: "unavailable"}),
  ]));

  assert.deepEqual(view.map((item) => item.eventId), [
    "open", "ready", "failed", "interrupted", "none",
  ]);
  assert.deepEqual(view.map((item) => item.evidenceLabel), [
    "采集中", "已就绪", "失败", "中断", "无证据",
  ]);
  assert.equal(view[0].stateLabel, "未恢复");
  assert.equal(view[0].open, true);
  assert.equal(view[1].stateLabel, "已恢复");
  assert.equal(view[1].open, false);
});


test("mount loads immediately and schedules exactly a fifteen-second refresh", async () => {
  const document = new FakeDocument();
  const intervals = [];
  let fetchCalls = 0;

  const dashboard = mountGuardianEvents({
    document,
    fetch: async () => {
      fetchCalls += 1;
      return {ok: true, json: async () => payload([])};
    },
    setInterval: (callback, milliseconds) => {
      intervals.push({callback, milliseconds});
      return 1;
    },
  });

  assert.equal(fetchCalls, 1);
  assert.deepEqual(intervals.map((item) => item.milliseconds), [15000]);
  await dashboard.initialRefresh;
  assert.equal(document.getElementById("guardian-events").textContent, "暂无 Guardian 事件");
});


test("open event is emphasized and failed refresh retains the old list", async () => {
  const document = new FakeDocument();
  const intervals = [];
  let fetchCalls = 0;
  const dashboard = mountGuardianEvents({
    document,
    fetch: async () => {
      fetchCalls += 1;
      if (fetchCalls > 1) throw new Error("private failure detail");
      return {ok: true, json: async () => payload([event()])};
    },
    setInterval: (callback, milliseconds) => {
      intervals.push({callback, milliseconds});
      return 1;
    },
  });
  await dashboard.initialRefresh;

  const list = document.getElementById("guardian-events");
  const originalRow = list.children[0];
  assert.equal(originalRow.className, "guardian-event is-open");
  assert.equal(originalRow.attributes.get("data-event-state"), "open");

  await intervals[0].callback();

  assert.equal(list.children[0], originalRow);
  const stale = document.getElementById("guardian-events-stale");
  assert.equal(stale.hidden, false);
  assert.equal(stale.textContent, "数据可能已过期");
  assert.doesNotMatch(stale.textContent, /private failure detail/);
});
