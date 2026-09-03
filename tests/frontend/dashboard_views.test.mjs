import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  applyAlertFilters,
  filterAlerts,
  presentAlerts,
  presentOverview,
  presentSystem,
  renderAlerts,
  renderOverview,
  renderSystem,
} = require('../../apps/api/dashboard_views.js');


const NOW = '2026-09-03T01:00:00Z';

function alert(overrides = {}) {
  return {
    alert_id: 'guardian:event-1',
    source: 'guardian',
    kind: 'face_not_visible',
    state: 'open',
    priority: 'critical',
    opened_at: '2026-09-03T00:50:00Z',
    updated_at: NOW,
    recovered_at: null,
    reason_codes: ['occluded'],
    adult_intervention_count: 0,
    evidence_state: 'collecting',
    notification_state: 'pending',
    resolution_cause: null,
    ...overrides,
  };
}

function component(overrides = {}) {
  return {
    component_id: 'camera',
    state: 'healthy',
    reason_code: 'camera_online',
    updated_at: NOW,
    ...overrides,
  };
}

function overviewPayload(overrides = {}) {
  return {
    schema_version: 1,
    generated_at: NOW,
    attention: null,
    open_alert_count: 0,
    guardian_open_count: 0,
    today_recovered_count: 0,
    environment: {
      state: 'available',
      temperature_c: 22.25,
      humidity_rh: 48.5,
      captured_at: NOW,
      fresh_until: '2026-09-03T01:05:00Z',
      failure_reason: null,
      last_valid_temperature_c: null,
      last_valid_humidity_rh: null,
      last_valid_captured_at: null,
    },
    components: [component()],
    recent_activity: [alert()],
    ...overrides,
  };
}

function alertPayload(alerts = [alert()]) {
  return {schema_version: 1, generated_at: NOW, alerts};
}

function systemPayload(components = [component()]) {
  return {schema_version: 1, generated_at: NOW, components};
}

class FakeElement {
  constructor(id = '') {
    this.id = id;
    this.children = [];
    this.className = '';
    this.dataset = {};
    this.attributes = new Map();
    this.hidden = false;
    this.textContent = '';
    this._innerHTMLWrites = 0;
  }

  set innerHTML(_value) {
    this._innerHTMLWrites += 1;
    throw new Error('innerHTML must not be used');
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
    this.textContent = '';
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }
}

class FakeDocument {
  constructor() {
    this.elements = new Map();
    for (const id of [
      'global-attention', 'alert-count', 'environment-current', 'environment-detail',
      'environment-last-valid', 'guardian-events', 'overview-components',
      'overview-recent', 'overview-guardian', 'dashboard-health', 'overview-updated', 'alerts-list',
      'alerts-updated', 'alerts-announcement', 'system-components', 'system-updated',
    ]) this.elements.set(id, new FakeElement(id));
  }

  createElement() {
    return new FakeElement();
  }

  getElementById(id) {
    return this.elements.get(id) ?? null;
  }
}

test('unavailable current never becomes the main reading', () => {
  const view = presentOverview(overviewPayload({
    environment: {
      state: 'unavailable',
      temperature_c: null,
      humidity_rh: null,
      captured_at: null,
      fresh_until: null,
      failure_reason: 'environment_no_reading',
      last_valid_temperature_c: 22,
      last_valid_humidity_rh: 48,
      last_valid_captured_at: '2026-09-03T00:55:00Z',
    },
  }));

  assert.equal(view.environment.currentText, '不可用');
  assert.equal(view.environment.lastValidText, '22.0°C · 48.0%RH');
  assert.doesNotMatch(view.environment.currentText, /22/);
});

test('unknown candidate alert is rejected instead of shown as confirmed', () => {
  assert.throws(
    () => presentAlerts(alertPayload([alert({kind: 'watch_candidate'})])),
    /closed dashboard alert/,
  );
});

test('closed dashboard payloads reject unexpected keys', () => {
  assert.throws(
    () => presentOverview(overviewPayload({candidate_state: 'watch'})),
    /closed dashboard overview/,
  );
  assert.throws(
    () => presentAlerts(alertPayload([alert({candidate_state: 'watch'})])),
    /closed dashboard alert/,
  );
  assert.throws(
    () => presentSystem(systemPayload([component({detail: 'private'})])),
    /closed dashboard component/,
  );
});

test('closed alert and component enum values receive labels', () => {
  const kinds = [
    'face_not_visible', 'prone_candidate', 'outside_candidate', 'environment_range',
    'environment_unreadable', 'camera_status', 'guardian_query_status',
    'environment_query_status', 'notification_queue_status', 'calibration_status',
  ];
  const evidenceStates = ['collecting', 'ready', 'failed', 'interrupted', 'unavailable'];
  const notificationStates = ['pending', 'delivered', 'rejected', 'mixed', 'unavailable'];
  const resolutionCauses = ['explicit_safe', 'subject_outside'];
  const componentStates = ['healthy', 'degraded', 'unavailable', 'disabled'];
  const reasonCodes = [
    'temperature_low', 'temperature_high', 'temperature_critical_low',
    'temperature_critical_high', 'humidity_low', 'humidity_high',
    'humidity_critical_low', 'humidity_critical_high', 'reading_unavailable',
    'no_new_reading', 'calibration_missing', 'calibration_invalid',
    'frame_source_unavailable', 'frame_stale', 'roi_out_of_bounds', 'too_dark',
    'glare', 'occluded', 'needle_not_found', 'insufficient_valid_frames',
    'inconsistent_frames', 'low_confidence', 'internal_error',
    'environment_no_reading', 'camera_online', 'camera_offline', 'camera_unavailable',
    'guardian_query_available', 'guardian_query_unavailable', 'environment_available',
    'environment_unavailable', 'notification_queue_empty', 'notification_queue_pending',
    'notification_query_unavailable', 'calibration_available', 'camera_reply_disabled',
    'camera_reply_status_unavailable',
  ];
  const labels = presentAlerts(alertPayload(kinds.map((kind, index) => alert({
    alert_id: `alert-${index}`,
    kind,
    state: index % 2 ? 'recovered' : 'open',
    recovered_at: index % 2 ? NOW : null,
    resolution_cause: index % 2 ? resolutionCauses[index % 2] : null,
    evidence_state: evidenceStates[index % evidenceStates.length],
    notification_state: notificationStates[index % notificationStates.length],
    reason_codes: [reasonCodes[index]],
  })))).alerts;

  assert.deepEqual(labels.map((item) => item.kindLabel).filter(Boolean).length, kinds.length);
  assert.deepEqual(labels.map((item) => item.evidenceLabel).filter(Boolean).length, kinds.length);
  assert.deepEqual(labels.map((item) => item.notificationLabel).filter(Boolean).length, kinds.length);
  assert.deepEqual(labels.filter((item) => item.resolutionLabel).length, kinds.length / 2);
  assert.deepEqual(
    presentSystem(systemPayload(componentStates.map((state, index) => component({
      component_id: ['camera', 'guardian_query', 'environment', 'gauge_calibration'][index],
      state,
      reason_code: reasonCodes[index],
    })))).components.map((item) => item.stateLabel).length,
    componentStates.length,
  );
  assert.equal(
    reasonCodes.filter((reasonCode) => presentAlerts(alertPayload([
      alert({reason_codes: [reasonCode]}),
    ])).alerts[0].reasonLabels.length === 1).length,
    reasonCodes.length,
  );
});

test('filters accept only closed values and preserve server order', () => {
  const alerts = presentAlerts(alertPayload([
    alert({alert_id: 'one', source: 'guardian', state: 'open'}),
    alert({alert_id: 'two', source: 'environment', state: 'recovered', recovered_at: NOW, resolution_cause: 'explicit_safe'}),
    alert({alert_id: 'three', source: 'system', state: 'open'}),
  ])).alerts;

  assert.deepEqual(filterAlerts(alerts, 'all', 'all').map((item) => item.alertId), ['one', 'two', 'three']);
  assert.deepEqual(filterAlerts(alerts, 'guardian', 'open').map((item) => item.alertId), ['one']);
  assert.deepEqual(filterAlerts(alerts, 'environment', 'recovered').map((item) => item.alertId), ['two']);
  assert.throws(() => filterAlerts(alerts, 'candidate', 'all'), /closed dashboard alert filter/);
  assert.throws(() => filterAlerts(alerts, 'all', 'watch'), /closed dashboard alert filter/);
});

test('rendering keeps malicious IDs in textContent and applies filters from trusted datasets', () => {
  const document = new FakeDocument();
  const maliciousId = '<img src=x onerror=alert(1)>';
  renderOverview(document, overviewPayload({
    attention: {alert: alert({alert_id: maliciousId}), additional_open_count: 0},
    open_alert_count: 1,
  }), {dateFormatter: {format: () => '本地时间'}});
  renderAlerts(document, alertPayload([
    alert({alert_id: maliciousId}),
    alert({alert_id: 'environment-1', source: 'environment'}),
  ]), {dateFormatter: {format: () => '本地时间'}, sourceFilter: 'guardian', stateFilter: 'all'});
  renderSystem(document, systemPayload(), {dateFormatter: {format: () => '本地时间'}});

  const attentionButton = document.getElementById('global-attention').children[0];
  const firstAlert = document.getElementById('alerts-list').children[0];
  assert.equal(attentionButton.dataset.alertTarget, maliciousId);
  assert.equal(firstAlert.dataset.alertId, maliciousId);
  assert.match(firstAlert.children.at(-1).textContent, /<img src=x/);
  assert.equal(firstAlert._innerHTMLWrites, 0);
  assert.equal(firstAlert.hidden, false);
  assert.equal(document.getElementById('alerts-list').children[1].hidden, true);
  assert.equal(document.getElementById('overview-updated').textContent, '本地时间');
  assert.equal(document.getElementById('alerts-updated').textContent, '本地时间');
  assert.equal(document.getElementById('system-updated').textContent, '本地时间');

  applyAlertFilters(document, 'all', 'all');
  assert.equal(document.getElementById('alerts-list').children[1].hidden, false);
});

test('nullable guardian counters stay unavailable while zero remains zero', () => {
  const document = new FakeDocument();
  renderOverview(document, overviewPayload({guardian_open_count: null, today_recovered_count: 0}), {
    dateFormatter: {format: () => '本地时间'},
  });
  assert.match(document.getElementById('overview-guardian').textContent, /未恢复：不可用/);
  assert.match(document.getElementById('overview-guardian').textContent, /今日已恢复：0/);
});
