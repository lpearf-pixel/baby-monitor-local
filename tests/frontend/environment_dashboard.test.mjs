import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  presentEnvironment,
  presentIncidents,
  trendPath,
} = require('../../apps/api/environment_dashboard.js');


test('unavailable current never falls back to last valid values', () => {
  const view = presentEnvironment({
    current_available: false,
    current_reading: {
      state: 'unavailable',
      captured_at: '2026-08-05T12:00:00Z',
      failure_reason: 'glare',
      calibration_version: 'cal-2',
      confidence_state: 'unavailable',
    },
    temperature_c: null,
    humidity_rh: null,
    last_valid_reading: {
      state: 'available',
      captured_at: '2026-08-05T11:59:00Z',
      temperature_c: 22,
      humidity_rh: 48,
    },
  });

  assert.equal(view.currentText, '不可用');
  assert.match(view.detailText, /glare/);
  assert.equal(view.lastValidText, '22.0°C · 48.0%RH · 2026-08-05T11:59:00Z');
  assert.doesNotMatch(view.currentText, /22/);
});


test('fresh current displays both values and calibration metadata', () => {
  const view = presentEnvironment({
    current_available: true,
    current_reading: {
      state: 'available',
      captured_at: '2026-08-05T12:00:00Z',
      calibration_version: 'cal-2',
      confidence_state: 'high',
    },
    temperature_c: 23.25,
    humidity_rh: 51.5,
    last_valid_reading: null,
  });

  assert.equal(view.currentText, '23.3°C · 51.5%RH');
  assert.match(view.detailText, /high/);
  assert.match(view.detailText, /cal-2/);
});


test('trend gaps stay null instead of receiving a previous value', () => {
  const buckets = [
    {temperature_median: 22, humidity_median: 48},
    {temperature_median: null, humidity_median: null},
  ];
  const view = presentEnvironment({
    current_available: false,
    current_reading: null,
    last_valid_reading: null,
    trend: {buckets},
  });

  assert.deepEqual(view.trendPoints, [
    {temperature: 22, humidity: 48},
    {temperature: null, humidity: null},
  ]);
});


test('trend path accepts only 24h and 7d windows', () => {
  assert.equal(trendPath('24h'), '/api/environment/trends/24h');
  assert.equal(trendPath('7d'), '/api/environment/trends/7d');
  assert.throws(() => trendPath('365d'), /closed trend window/);
});


test('incident presentation keeps stable reasons and recovery state', () => {
  assert.deepEqual(
    presentIncidents([
      {kind: 'range', state: 'open', severity: 'critical', reasons: ['temperature_high']},
      {kind: 'unreadable', state: 'recovered', severity: 'normal', reasons: ['too_dark']},
    ]),
    [
      'range · open · critical · temperature_high',
      'unreadable · recovered · normal · too_dark',
    ],
  );
});
