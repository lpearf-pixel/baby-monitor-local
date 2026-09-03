import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
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
  constructor(id = '', tagName = 'div') {
    this.id = id;
    this.tagName = tagName;
    this.children = [];
    this.className = '';
    this.dataset = {};
    this.attributes = new Map();
    this.hidden = false;
    this._textContent = '';
    this._innerHTMLWrites = 0;
  }

  get textContent() {
    return this._textContent;
  }

  set textContent(value) {
    this._textContent = String(value);
    this.children = [];
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
    this._textContent = '';
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
      'environment-last-valid', 'overview-guardian-counts', 'dashboard-health', 'overview-updated', 'alerts-list',
      'overview-stale', 'alerts-updated', 'alerts-stale', 'alerts-announcement',
      'system-components', 'system-updated', 'system-stale',
    ]) this.elements.set(id, new FakeElement(id));

    const guardian = new FakeElement('overview-guardian', 'section');
    const guardianTitle = new FakeElement('overview-guardian-title', 'h2');
    guardian.setAttribute('aria-labelledby', guardianTitle.id);
    guardian.append(guardianTitle, this.elements.get('overview-guardian-counts'));
    this.elements.set(guardian.id, guardian);
    this.elements.set(guardianTitle.id, guardianTitle);

    const components = new FakeElement('overview-components', 'section');
    const componentsTitle = new FakeElement('overview-components-title', 'h2');
    const componentList = new FakeElement('overview-components-list', 'div');
    components.setAttribute('aria-labelledby', componentsTitle.id);
    components.append(componentsTitle, componentList);
    this.elements.set(components.id, components);
    this.elements.set(componentsTitle.id, componentsTitle);
    this.elements.set(componentList.id, componentList);

    const recent = new FakeElement('overview-recent', 'section');
    const recentTitle = new FakeElement('overview-recent-title', 'h2');
    const recentList = new FakeElement('overview-recent-list', 'ol');
    recent.setAttribute('aria-labelledby', recentTitle.id);
    recent.append(recentTitle, recentList);
    this.elements.set(recent.id, recent);
    this.elements.set(recentTitle.id, recentTitle);
    this.elements.set(recentList.id, recentList);
  }

  createElement(tagName) {
    return new FakeElement('', tagName);
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

test('production-shaped unavailable environment keeps timestamps separate from current values', () => {
  const view = presentOverview(overviewPayload({
    environment: {
      state: 'unavailable',
      temperature_c: null,
      humidity_rh: null,
      captured_at: '2026-09-03T00:59:00Z',
      fresh_until: '2026-09-03T01:00:00Z',
      failure_reason: 'reading_unavailable',
      last_valid_temperature_c: 22,
      last_valid_humidity_rh: 48,
      last_valid_captured_at: '2026-09-03T00:55:00Z',
    },
  }));

  assert.equal(view.environment.currentText, '不可用');
  assert.equal(view.environment.lastValidCapturedAt, '2026-09-03T00:55:00Z');
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
  assert.equal(
    presentAlerts(alertPayload([alert({
      state: 'recovered', recovered_at: NOW, resolution_cause: 'explicit_safe',
    })])).alerts[0].resolutionLabel,
    '已确认安全',
  );
  assert.equal(
    presentAlerts(alertPayload([alert({
      state: 'recovered', recovered_at: NOW, resolution_cause: 'subject_outside',
    })])).alerts[0].resolutionLabel,
    '目标已离开',
  );
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

test('rendering keeps malicious IDs in textContent, highlights only an exact ID, and applies filters from trusted datasets', () => {
  const document = new FakeDocument();
  const maliciousId = '<img src=x onerror=alert(1)>';
  renderOverview(document, overviewPayload({
    attention: {alert: alert({alert_id: maliciousId}), additional_open_count: 0},
    open_alert_count: 1,
  }), {dateFormatter: {format: () => '本地时间'}});
  renderAlerts(document, alertPayload([
    alert({alert_id: maliciousId}),
    alert({alert_id: 'environment-1', source: 'environment'}),
    alert({alert_id: 'environment-10', source: 'system'}),
  ]), {
    dateFormatter: {format: () => '本地时间'}, sourceFilter: 'guardian', stateFilter: 'all',
    highlightAlertId: 'environment-1',
  });
  renderSystem(document, systemPayload(), {dateFormatter: {format: () => '本地时间'}});

  const attentionButton = document.getElementById('global-attention').children[0];
  const firstAlert = document.getElementById('alerts-list').children[0];
  assert.equal(attentionButton.dataset.alertTarget, maliciousId);
  assert.equal(firstAlert.dataset.alertId, maliciousId);
  assert.match(firstAlert.children.at(-1).textContent, /<img src=x/);
  assert.equal(firstAlert._innerHTMLWrites, 0);
  assert.equal(firstAlert.hidden, false);
  assert.equal(document.getElementById('alerts-list').children[1].hidden, true);
  assert.equal(document.getElementById('alerts-list').children[1].className.includes('is-target'), true);
  assert.equal(document.getElementById('alerts-list').children[2].className.includes('is-target'), false);
  assert.equal(document.getElementById('overview-updated').textContent, '本地时间');
  assert.equal(document.getElementById('alerts-updated').textContent, '本地时间');
  assert.equal(document.getElementById('system-updated').textContent, '本地时间');

  applyAlertFilters(document, 'all', 'all');
  assert.equal(document.getElementById('alerts-list').children[1].hidden, false);
});

test('overview attention includes only a nonzero additional open count', () => {
  const document = new FakeDocument();
  renderOverview(document, overviewPayload({
    attention: {alert: alert(), additional_open_count: 0}, open_alert_count: 1,
  }), {dateFormatter: {format: () => '本地时间'}});
  assert.doesNotMatch(document.getElementById('global-attention').children[0].textContent, /另有/);

  renderOverview(document, overviewPayload({
    attention: {alert: alert(), additional_open_count: 2}, open_alert_count: 3,
  }), {dateFormatter: {format: () => '本地时间'}});
  assert.match(document.getElementById('global-attention').children[0].textContent, /另有 2 项未恢复警报/);
});

test('overview health summary gives confirmed critical then warning then component degradation precedence', () => {
  assert.equal(
    presentOverview(overviewPayload({
      attention: {alert: alert({priority: 'critical'}), additional_open_count: 0},
      components: [component({state: 'unavailable', reason_code: 'camera_unavailable'})],
    })).healthText,
    '存在已确认高风险警报',
  );
  assert.equal(
    presentOverview(overviewPayload({
      attention: {alert: alert({priority: 'warning'}), additional_open_count: 0},
      components: [component({state: 'unavailable', reason_code: 'camera_unavailable'})],
    })).healthText,
    '存在需检查的警报',
  );
  assert.equal(
    presentOverview(overviewPayload({
      components: [component({state: 'degraded', reason_code: 'camera_offline'})],
    })).healthText,
    '系统组件需要检查',
  );
  assert.equal(presentOverview(overviewPayload()).healthText, '当前未发现未恢复警报');
});

test('rendered overview retains last-valid time and rendered components use the injected formatter', () => {
  const document = new FakeDocument();
  const formatter = {format: (date) => `本地 ${date.toISOString()}`};
  renderOverview(document, overviewPayload({
    environment: {
      state: 'unavailable', temperature_c: null, humidity_rh: null,
      captured_at: '2026-09-03T00:59:00Z', fresh_until: NOW,
      failure_reason: 'reading_unavailable', last_valid_temperature_c: 22,
      last_valid_humidity_rh: 48, last_valid_captured_at: '2026-09-03T00:55:00Z',
    },
  }), {dateFormatter: formatter});
  renderSystem(document, systemPayload(), {dateFormatter: formatter});

  assert.equal(
    document.getElementById('environment-last-valid').textContent,
    '22.0°C · 48.0%RH · 本地 2026-09-03T00:55:00.000Z',
  );
  assert.match(
    document.getElementById('overview-components-list').children[0].children[1].textContent,
    /本地 2026-09-03T01:00:00.000Z/,
  );
  assert.match(
    document.getElementById('system-components').children[0].children[1].textContent,
    /本地 2026-09-03T01:00:00.000Z/,
  );
});

test('overview rendering preserves labelled section headings and uses dedicated valid collection containers', () => {
  const document = new FakeDocument();
  const guardian = document.getElementById('overview-guardian');
  const components = document.getElementById('overview-components');
  const recent = document.getElementById('overview-recent');
  const guardianHeading = guardian.children[0];
  const componentsHeading = components.children[0];
  const recentHeading = recent.children[0];

  renderOverview(document, overviewPayload(), {dateFormatter: {format: () => '本地时间'}});

  assert.equal(guardian.getAttribute('aria-labelledby'), guardianHeading.id);
  assert.equal(components.getAttribute('aria-labelledby'), componentsHeading.id);
  assert.equal(recent.getAttribute('aria-labelledby'), recentHeading.id);
  assert.equal(guardian.children[0], guardianHeading);
  assert.equal(components.children[0], componentsHeading);
  assert.equal(recent.children[0], recentHeading);
  assert.match(document.getElementById('overview-guardian-counts').textContent, /未恢复：0/);
  assert.equal(document.getElementById('overview-components-list').tagName, 'div');
  assert.equal(document.getElementById('overview-components-list').children[0].tagName, 'article');
  assert.match(document.getElementById('overview-components-list').children[0].className, /component-card/);
  assert.match(document.getElementById('overview-components-list').children[0].className, /component-healthy/);
  assert.equal(document.getElementById('overview-recent-list').tagName, 'ol');
  assert.equal(document.getElementById('overview-recent-list').children[0].tagName, 'li');
});

test('first unavailable, later stale, and recovered renders preserve last valid content and transition state', () => {
  const document = new FakeDocument();
  const formatter = {format: (date) => `本地 ${date.toISOString()}`};

  document.getElementById('global-attention').append(new FakeElement('', 'button'));
  document.getElementById('alert-count').hidden = false;

  markUnavailable(document, 'overview');
  assert.equal(document.getElementById('overview-updated').textContent, '数据不可用');
  assert.equal(document.getElementById('overview-stale').hidden, true);
  assert.equal(document.getElementById('dashboard-health').textContent, '总览数据不可用');
  assert.equal(document.getElementById('environment-current').textContent, '不可用');
  assert.equal(document.getElementById('environment-detail').textContent, '当前环境读数不可用');
  assert.equal(document.getElementById('environment-last-valid').textContent, '无最近有效读数');
  assert.match(document.getElementById('overview-guardian-counts').textContent, /未恢复：不可用/);
  assert.match(document.getElementById('overview-guardian-counts').textContent, /今日已恢复：不可用/);
  assert.equal(document.getElementById('overview-components-list').textContent, '组件状态不可用');
  assert.equal(document.getElementById('overview-recent-list').children[0].tagName, 'li');
  assert.equal(document.getElementById('overview-recent-list').children[0].textContent, '最近活动不可用');
  assert.equal(document.getElementById('global-attention').hidden, true);
  assert.equal(document.getElementById('global-attention').children.length, 0);
  assert.equal(document.getElementById('alert-count').hidden, true);

  markUnavailable(document, 'alerts');
  assert.equal(document.getElementById('alerts-list').children[0].tagName, 'li');
  assert.equal(document.getElementById('alerts-list').children[0].textContent, '警报数据不可用');

  markUnavailable(document, 'system');
  assert.equal(document.getElementById('system-components').textContent, '系统状态不可用');

  renderOverview(document, overviewPayload(), {dateFormatter: formatter});
  renderAlerts(document, alertPayload(), {dateFormatter: formatter});
  renderSystem(document, systemPayload(), {dateFormatter: formatter});
  assert.equal(document.getElementById('overview-stale').hidden, true);
  assert.equal(document.getElementById('overview-updated').textContent, '本地 2026-09-03T01:00:00.000Z');
  assert.equal(document.getElementById('environment-current').textContent, '22.3°C · 48.5%RH');
  assert.equal(document.getElementById('overview-components-list').children[0].tagName, 'article');
  assert.equal(document.getElementById('overview-recent-list').children[0].dataset.alertId, 'guardian:event-1');
  assert.equal(document.getElementById('alerts-list').children[0].dataset.alertId, 'guardian:event-1');
  assert.equal(document.getElementById('system-components').children[0].dataset.componentId, 'camera');

  markStale(document, 'overview', NOW, {dateFormatter: formatter});
  assert.equal(document.getElementById('overview-stale').hidden, false);
  assert.equal(document.getElementById('overview-stale').textContent, '数据可能已过期 · 上次更新：本地 2026-09-03T01:00:00.000Z');
  assert.equal(document.getElementById('environment-current').textContent, '22.3°C · 48.5%RH');

  renderOverview(document, overviewPayload({generated_at: '2026-09-03T01:01:00Z'}), {dateFormatter: formatter});
  assert.equal(document.getElementById('overview-stale').hidden, true);
  assert.equal(document.getElementById('overview-stale').textContent, '');
  assert.equal(document.getElementById('overview-updated').textContent, '本地 2026-09-03T01:01:00.000Z');
});

test('nullable guardian counters stay unavailable while zero remains zero', () => {
  const document = new FakeDocument();
  renderOverview(document, overviewPayload({guardian_open_count: null, today_recovered_count: 0}), {
    dateFormatter: {format: () => '本地时间'},
  });
  assert.match(document.getElementById('overview-guardian-counts').textContent, /未恢复：不可用/);
  assert.match(document.getElementById('overview-guardian-counts').textContent, /今日已恢复：0/);
});
