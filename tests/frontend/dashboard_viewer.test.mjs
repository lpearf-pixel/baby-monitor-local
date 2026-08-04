import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  clampPan,
  createViewerModel,
  mountDashboardViewer,
} = require('../../apps/api/dashboard_viewer.js');


class FakeEventTarget {
  constructor() {
    this.listeners = new Map();
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  dispatch(type, event = {}) {
    const suppliedTarget = event.target;
    const payload = {
      button: 0,
      pointerId: 1,
      preventDefault() {},
      ...event,
      currentTarget: this,
      target: suppliedTarget ?? this,
    };
    for (const listener of this.listeners.get(type) ?? []) {
      listener(payload);
    }
  }
}


class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  toggle(name, enabled) {
    if (enabled) this.values.add(name);
    else this.values.delete(name);
  }

  contains(name) {
    return this.values.has(name);
  }
}


class FakeElement extends FakeEventTarget {
  constructor(id, {dataset = {}, width = 0, height = 0} = {}) {
    super();
    this.id = id;
    this.dataset = dataset;
    this.clientWidth = width;
    this.clientHeight = height;
    this.offsetWidth = width;
    this.offsetHeight = height;
    this.attributes = new Map();
    this.classList = new FakeClassList();
    this.style = {};
    this.disabled = false;
    this.textContent = '';
    this.src = '';
    this.capturedPointer = null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  setPointerCapture(pointerId) {
    this.capturedPointer = pointerId;
  }

  releasePointerCapture(pointerId) {
    if (this.capturedPointer === pointerId) this.capturedPointer = null;
  }
}


class FakeDocument extends FakeEventTarget {
  constructor(elements, zoomButtons, ptzButtons) {
    super();
    this.elements = elements;
    this.zoomButtons = zoomButtons;
    this.ptzButtons = ptzButtons;
    this.fullscreenElement = null;
  }

  getElementById(id) {
    return this.elements.get(id) ?? null;
  }

  querySelectorAll(selector) {
    if (selector === '.zoom-button') return this.zoomButtons;
    if (selector === '.ptz-button') return this.ptzButtons;
    return [];
  }

  async exitFullscreen() {
    this.fullscreenElement = null;
    this.dispatch('fullscreenchange');
  }
}


function browserFixture({fullscreen = true, rejectFullscreen = false} = {}) {
  const viewer = new FakeElement('viewer', {width: 800, height: 450});
  const mediaPlane = new FakeElement('media-plane', {width: 800, height: 450});
  const liveImage = new FakeElement('live-image');
  liveImage.src = '/live.mjpeg';
  const hdVideo = new FakeElement('hd-video');
  const hdStatus = new FakeElement('hd-status');
  const fullscreenButton = new FakeElement('fullscreen');
  const ptzStatus = new FakeElement('ptz-status');
  const zoomButtons = [1, 2, 3].map(
    (zoom) => new FakeElement(`zoom-${zoom}`, {dataset: {zoom: String(zoom)}}),
  );
  const ptzButtons = ['up', 'down', 'left', 'right'].map(
    (direction) => new FakeElement(`ptz-${direction}`, {dataset: {direction}}),
  );
  const document = new FakeDocument(
    new Map([
      ['viewer', viewer],
      ['media-plane', mediaPlane],
      ['live-image', liveImage],
      ['hd-video', hdVideo],
      ['hd-status', hdStatus],
      ['fullscreen', fullscreenButton],
      ['ptz-status', ptzStatus],
    ]),
    zoomButtons,
    ptzButtons,
  );
  const window = new FakeEventTarget();
  const fullscreenCalls = [];
  if (fullscreen) {
    viewer.requestFullscreen = async () => {
      fullscreenCalls.push(viewer);
      if (rejectFullscreen) throw new Error('not allowed');
      document.fullscreenElement = viewer;
      document.dispatch('fullscreenchange');
    };
  }
  const timerCalls = [];
  return {
    document,
    fullscreenButton,
    fullscreenCalls,
    hdStatus,
    hdVideo,
    liveImage,
    mediaPlane,
    ptzButtons,
    ptzStatus,
    setTimeout(callback, milliseconds) {
      timerCalls.push({callback, milliseconds});
      return timerCalls.length;
    },
    timerCalls,
    viewer,
    window,
    zoomButtons,
  };
}


async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
}


test('clampPan keeps the zoomed plane covering the viewport', () => {
  assert.deepEqual(
    clampPan({
      x: 900,
      y: -900,
      zoom: 3,
      viewportWidth: 800,
      viewportHeight: 450,
      planeWidth: 800,
      planeHeight: 450,
    }),
    {x: 800, y: -450},
  );
});


test('1x always centers and a lower zoom clamps the current pan', () => {
  const rendered = [];
  const model = createViewerModel(
    () => ({
      viewportWidth: 800,
      viewportHeight: 450,
      planeWidth: 800,
      planeHeight: 450,
    }),
    (state) => rendered.push(state),
  );

  model.setZoom(3);
  model.dragBy(900, 900);
  assert.deepEqual(model.state(), {zoom: 3, x: 800, y: 450});

  model.setZoom(2);
  assert.deepEqual(model.state(), {zoom: 2, x: 400, y: 225});

  model.setZoom(1);
  assert.deepEqual(model.state(), {zoom: 1, x: 0, y: 0});
  assert.deepEqual(rendered.at(-1), {zoom: 1, x: 0, y: 0});
});


test('reclamp responds to a viewport resize without changing zoom', () => {
  let dimensions = {
    viewportWidth: 800,
    viewportHeight: 450,
    planeWidth: 800,
    planeHeight: 450,
  };
  const model = createViewerModel(() => dimensions, () => {});
  model.setZoom(3);
  model.dragBy(800, 450);

  dimensions = {
    viewportWidth: 1200,
    viewportHeight: 800,
    planeWidth: 1200,
    planeHeight: 675,
  };
  model.reclamp();

  assert.deepEqual(model.state(), {zoom: 3, x: 800, y: 450});
});


test('zoom buttons and pointer drag update the real media transform', () => {
  const fixture = browserFixture();
  mountDashboardViewer({...fixture, fetch: async () => {}});

  fixture.zoomButtons[2].dispatch('click');
  assert.equal(fixture.zoomButtons[2].getAttribute('aria-pressed'), 'true');
  assert.equal(fixture.zoomButtons[0].getAttribute('aria-pressed'), 'false');
  assert.match(fixture.mediaPlane.style.transform, /scale\(3\)/);
  assert.equal(fixture.viewer.classList.contains('is-zoomed'), true);

  fixture.viewer.dispatch('pointerdown', {clientX: 100, clientY: 100});
  fixture.viewer.dispatch('pointermove', {clientX: 1000, clientY: 1000});
  fixture.viewer.dispatch('pointerup');

  assert.equal(fixture.viewer.capturedPointer, null);
  assert.equal(fixture.viewer.classList.contains('is-dragging'), false);
  assert.match(
    fixture.mediaPlane.style.transform,
    /translate3d\(calc\(-50% \+ 800px\), calc\(-50% \+ 450px\), 0\) scale\(3\)/,
  );
});


test('fullscreen button and image double-click target only the viewer', async () => {
  const fixture = browserFixture();
  mountDashboardViewer({...fixture, fetch: async () => {}});

  fixture.fullscreenButton.dispatch('click');
  await flushPromises();
  assert.deepEqual(fixture.fullscreenCalls, [fixture.viewer]);
  assert.equal(fixture.fullscreenButton.getAttribute('aria-label'), '退出全屏');

  await fixture.document.exitFullscreen();
  fixture.liveImage.dispatch('dblclick');
  await flushPromises();
  assert.deepEqual(fixture.fullscreenCalls, [fixture.viewer, fixture.viewer]);
});


test('native fullscreen exit resets zoom and pan', async () => {
  const fixture = browserFixture();
  mountDashboardViewer({...fixture, fetch: async () => {}});
  fixture.zoomButtons[2].dispatch('click');
  fixture.viewer.dispatch('pointerdown', {clientX: 100, clientY: 100});
  fixture.viewer.dispatch('pointermove', {clientX: 500, clientY: 300});
  fixture.viewer.dispatch('pointerup');

  fixture.fullscreenButton.dispatch('click');
  await flushPromises();
  await fixture.document.exitFullscreen();

  assert.equal(fixture.zoomButtons[0].getAttribute('aria-pressed'), 'true');
  assert.equal(
    fixture.mediaPlane.style.transform,
    'translate3d(-50%, -50%, 0) scale(1)',
  );
  assert.equal(fixture.fullscreenButton.getAttribute('aria-label'), '进入全屏');
});


test('fullscreen rejection preserves zoom and the live stream source', async () => {
  const fixture = browserFixture({rejectFullscreen: true});
  mountDashboardViewer({...fixture, fetch: async () => {}});
  fixture.zoomButtons[1].dispatch('click');

  fixture.fullscreenButton.dispatch('click');
  await flushPromises();

  assert.match(fixture.mediaPlane.style.transform, /scale\(2\)/);
  assert.equal(fixture.liveImage.src, '/live.mjpeg');
  assert.equal(fixture.fullscreenButton.getAttribute('aria-label'), '进入全屏');
});


test('missing Fullscreen API disables only the fullscreen control', () => {
  const fixture = browserFixture({fullscreen: false});
  mountDashboardViewer({...fixture, fetch: async () => {}});

  assert.equal(fixture.fullscreenButton.disabled, true);
  assert.equal(fixture.fullscreenButton.getAttribute('aria-disabled'), 'true');
  fixture.zoomButtons[1].dispatch('click');
  assert.match(fixture.mediaPlane.style.transform, /scale\(2\)/);
});


test('one PTZ click sends one closed request and holds all buttons for cooldown', async () => {
  const fixture = browserFixture();
  const requests = [];
  let resolveFetch;
  const fetch = (...args) => {
    requests.push(args);
    return new Promise((resolve) => {
      resolveFetch = resolve;
    });
  };
  mountDashboardViewer({...fixture, fetch});

  fixture.ptzButtons[2].dispatch('pointerdown');
  assert.equal(requests.length, 0);
  fixture.ptzButtons[2].dispatch('click');
  fixture.ptzButtons[2].dispatch('click');

  assert.equal(requests.length, 1);
  assert.equal(requests[0][0], '/api/ptz/step');
  assert.deepEqual(requests[0][1], {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({direction: 'left'}),
  });
  assert.equal(fixture.ptzButtons.every((button) => button.disabled), true);

  resolveFetch({
    ok: true,
    async json() {
      return {result: 'PTZ_OK', cooldown_ms: 750};
    },
  });
  await flushPromises();

  assert.equal(fixture.ptzStatus.textContent, 'PTZ_OK');
  assert.equal(fixture.ptzButtons.every((button) => button.disabled), true);
  assert.equal(fixture.timerCalls.length, 1);
  assert.equal(fixture.timerCalls[0].milliseconds, 750);
  assert.equal(fixture.liveImage.src, '/live.mjpeg');

  fixture.timerCalls[0].callback();
  assert.equal(fixture.ptzButtons.every((button) => !button.disabled), true);
});


test('PTZ cooldown from the server is bounded to five seconds', async () => {
  const fixture = browserFixture();
  const fetch = async () => ({
    ok: true,
    async json() {
      return {result: 'PTZ_OK', cooldown_ms: 999999};
    },
  });
  mountDashboardViewer({...fixture, fetch});

  fixture.ptzButtons[0].dispatch('click');
  await flushPromises();

  assert.equal(fixture.timerCalls[0].milliseconds, 5000);
});


test('PTZ network and malformed responses fail closed without replacing video', async () => {
  const networkFixture = browserFixture();
  mountDashboardViewer({
    ...networkFixture,
    fetch: async () => {
      throw new Error('sensitive camera address');
    },
  });
  networkFixture.ptzButtons[1].dispatch('click');
  await flushPromises();

  assert.equal(networkFixture.ptzStatus.textContent, 'PTZ_UNAVAILABLE');
  assert.equal(networkFixture.ptzStatus.textContent.includes('sensitive'), false);
  assert.equal(networkFixture.liveImage.src, '/live.mjpeg');
  assert.equal(networkFixture.ptzButtons.every((button) => !button.disabled), true);

  const malformedFixture = browserFixture();
  mountDashboardViewer({
    ...malformedFixture,
    fetch: async () => ({
      ok: false,
      async json() {
        return {result: 'raw-device-response', detail: 'private-value'};
      },
    }),
  });
  malformedFixture.ptzButtons[3].dispatch('click');
  await flushPromises();

  assert.equal(malformedFixture.ptzStatus.textContent, 'PTZ_UNAVAILABLE');
  assert.equal(malformedFixture.ptzStatus.textContent.includes('private'), false);
  assert.equal(malformedFixture.liveImage.src, '/live.mjpeg');
});


test('stable disabled response is shown and immediately releases controls', async () => {
  const fixture = browserFixture();
  mountDashboardViewer({
    ...fixture,
    fetch: async () => ({
      ok: false,
      async json() {
        return {result: 'PTZ_DISABLED', cooldown_ms: 0};
      },
    }),
  });

  fixture.ptzButtons[3].dispatch('click');
  await flushPromises();

  assert.equal(fixture.ptzStatus.textContent, 'PTZ_DISABLED');
  assert.equal(fixture.ptzButtons.every((button) => !button.disabled), true);
  assert.equal(fixture.timerCalls.length, 0);
});


test('zoom changes and fullscreen exit notify one HD player without drag repeats', async () => {
  const fixture = browserFixture();
  const zooms = [];
  const hdPlayer = {selectZoom: (zoom) => zooms.push(zoom)};
  mountDashboardViewer({...fixture, fetch: async () => {}, hdPlayer});

  fixture.zoomButtons[1].dispatch('click');
  fixture.viewer.dispatch('pointerdown', {clientX: 100, clientY: 100});
  fixture.viewer.dispatch('pointermove', {clientX: 200, clientY: 150});
  fixture.viewer.dispatch('pointerup');
  fixture.zoomButtons[2].dispatch('click');
  fixture.fullscreenButton.dispatch('click');
  await flushPromises();
  await fixture.document.exitFullscreen();

  assert.deepEqual(zooms, [1, 2, 3, 1]);
});


test('viewer constructs the HD player from fixed page elements', () => {
  const fixture = browserFixture();
  const captured = [];
  fixture.window.BabyMonitorHdPlayer = {
    createHdPlayer(environment) {
      captured.push(environment);
      return {selectZoom() {}};
    },
  };

  mountDashboardViewer({...fixture, fetch: async () => {}});

  assert.equal(captured.length, 1);
  assert.equal(captured[0].image, fixture.liveImage);
  assert.equal(captured[0].video, fixture.hdVideo);
  assert.equal(captured[0].statusElement, fixture.hdStatus);
  assert.equal(captured[0].window, fixture.window);
});


test('HD video double-click uses the same viewer fullscreen action', async () => {
  const fixture = browserFixture();
  mountDashboardViewer({
    ...fixture,
    fetch: async () => {},
    hdPlayer: {selectZoom() {}},
  });

  fixture.hdVideo.dispatch('dblclick');
  await flushPromises();

  assert.deepEqual(fixture.fullscreenCalls, [fixture.viewer]);
});
