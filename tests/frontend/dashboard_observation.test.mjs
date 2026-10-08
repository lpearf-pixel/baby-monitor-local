import assert from 'node:assert/strict';
import test from 'node:test';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {
  presentObservation,
  renderObservation,
} = require('../../apps/api/dashboard_observation.js');

const NOW = '2026-10-09T12:00:07Z';

function payload(overrides = {}) {
  return {
    schema_version: 1,
    state: 'available',
    baby_visibility: 'visible',
    input_frame_captured_at: '2026-10-09T12:00:06Z',
    result_completed_at: NOW,
    freshness: 'fresh',
    reason_code: 'none',
    written_at: NOW,
    ...overrides,
  };
}

test('recent observation presents visible without safety language', () => {
  const view = presentObservation(payload());
  assert.equal(view.label, '最近一次观察：宝宝可见');
  assert.match(view.detail, /帧采集时间/);
  assert.doesNotMatch(view.detail, /安全|持续/);
});

test('stale and failed states never present not_visible', () => {
  for (const state of ['stale', 'failed', 'no_result', 'worker_restarted']) {
    const view = presentObservation(payload({
      state,
      baby_visibility: state === 'stale' ? 'visible' : null,
      freshness: state === 'stale' ? 'stale' : 'unknown',
      reason_code: state === 'stale' ? 'review_expired' : state === 'failed' ? 'review_failed' : state === 'no_result' ? 'no_review_yet' : 'worker_restarted',
      input_frame_captured_at: state === 'stale' ? payload().input_frame_captured_at : null,
      result_completed_at: state === 'stale' ? NOW : null,
    }));
    assert.notEqual(view.label, '未观察到宝宝');
  }
});

test('rendering request failure is local and visibly not fresh', () => {
  const element = {textContent: '', dataset: {}};
  const document = {
    getElementById(id) {
      return id === 'recent-observation' ? element : null;
    },
  };
  renderObservation(document, null);
  assert.equal(element.textContent, '最近一次观察：当前不可用');
});
