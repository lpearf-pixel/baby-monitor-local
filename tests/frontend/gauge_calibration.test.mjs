import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  buildCalibrationDraft,
  createWizardModel,
  viewportPointToSource,
} = require('../../apps/api/gauge_calibration.js');


test('viewport points reverse to original source coordinates', () => {
  assert.deepEqual(
    viewportPointToSource(
      {x: 0.5, y: 0.5},
      {zoom: 2, center_x: 0.25, center_y: 0.5},
    ),
    {x: 0.25, y: 0.5},
  );
});


test('draft requires four corners and three marks per face', () => {
  assert.throws(
    () => buildCalibrationDraft({
      sourceWidth: 2560,
      sourceHeight: 1440,
      viewport: {zoom: 2, center_x: 0.5, center_y: 0.5},
      corners: [{x: 0.1, y: 0.1}],
      humidity: {center: {x: 0.3, y: 0.5}, needleTip: {x: 0.3, y: 0.4}, marks: []},
      temperature: {center: {x: 0.7, y: 0.5}, needleTip: {x: 0.7, y: 0.4}, marks: []},
    }),
    /four gauge corners/,
  );
});


test('draft contains geometry only and no client path or stream selector', () => {
  const face = (x) => ({
    center: {x, y: 0.5},
    needleTip: {x, y: 0.4},
    radius: 0.1,
    marks: [
      {point: {x: x - 0.05, y: 0.45}, angle_degrees: 20, unwrapped_angle_degrees: 20, value: 10},
      {point: {x, y: 0.4}, angle_degrees: 90, unwrapped_angle_degrees: 90, value: 20},
      {point: {x: x + 0.05, y: 0.45}, angle_degrees: 160, unwrapped_angle_degrees: 160, value: 30},
    ],
  });
  const draft = buildCalibrationDraft({
    sourceWidth: 2560,
    sourceHeight: 1440,
    viewport: {zoom: 2, center_x: 0.5, center_y: 0.5},
    corners: [
      {x: 0.1, y: 0.1}, {x: 0.9, y: 0.1},
      {x: 0.9, y: 0.9}, {x: 0.1, y: 0.9},
    ],
    humidity: face(0.3),
    temperature: face(0.7),
  });

  const serialized = JSON.stringify(draft);
  assert.equal(draft.zoom, 2);
  assert.equal(draft.source_width, 2560);
  for (const forbidden of ['path', 'stream', 'url', 'token', 'image']) {
    assert.doesNotMatch(serialized, new RegExp(forbidden, 'i'));
  }
});


test('wizard enforces ordered points, mark values, undo, and readiness', () => {
  const wizard = createWizardModel();
  const points = [
    [0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9],
    [0.3, 0.5], [0.3, 0.4],
    [0.25, 0.45], [0.3, 0.4], [0.35, 0.45],
    [0.7, 0.5], [0.7, 0.4],
    [0.65, 0.45], [0.7, 0.4], [0.75, 0.45],
  ];
  points.forEach(([x, y], index) => {
    const isMark = [6, 7, 8, 11, 12, 13].includes(index);
    wizard.addPoint({x, y}, isMark ? index : undefined);
  });
  assert.equal(wizard.state().ready, true);
  wizard.undo();
  assert.equal(wizard.state().ready, false);
  assert.match(wizard.state().instruction, /temperature scale mark 3/);
});
