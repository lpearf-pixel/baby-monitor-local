import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  BLANK_IMAGE_SRC,
  createHdPlayer,
} = require('../../apps/api/hd_player.js');


class FakeEventTarget {
  constructor() {
    this.listeners = new Map();
  }

  addEventListener(type, listener, options = {}) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push({listener, once: Boolean(options.once)});
    this.listeners.set(type, listeners);
  }

  removeEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? [];
    this.listeners.set(type, listeners.filter((entry) => entry.listener !== listener));
  }

  dispatch(type, event = {}) {
    const listeners = [...(this.listeners.get(type) ?? [])];
    for (const entry of listeners) {
      entry.listener({type, target: this, ...event});
      if (entry.once) this.removeEventListener(type, entry.listener);
    }
  }
}


class FakeElement extends FakeEventTarget {
  constructor({playReject = false, playResults = []} = {}) {
    super();
    this.attributes = new Map();
    this.src = '';
    this.textContent = '';
    this.currentTime = 0;
    this.playCalls = 0;
    this.loadCalls = 0;
    this.playReject = playReject;
    this.playResults = [...playResults];
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  play() {
    this.playCalls += 1;
    if (this.playResults.length > 0) return this.playResults.shift();
    if (this.playReject) {
      return Promise.reject(new Error('autoplay rejected with private detail'));
    }
    return Promise.resolve();
  }

  load() {
    this.loadCalls += 1;
  }
}


class FakeWebSocket extends FakeEventTarget {
  constructor(url) {
    super();
    this.url = url;
    this.binaryType = '';
    this.sent = [];
    this.closeCalls = 0;
  }

  send(value) {
    this.sent.push(value);
  }

  close() {
    this.closeCalls += 1;
  }

  open() {
    this.dispatch('open');
  }

  message(data) {
    this.dispatch('message', {data});
  }

  fail() {
    this.dispatch('error');
  }

  serverClose() {
    this.dispatch('close');
  }
}


class FakeSourceBuffer extends FakeEventTarget {
  constructor() {
    super();
    this.updating = false;
    this.appended = [];
    this.removed = [];
    this.bufferedRanges = [];
    this.throwOnAppend = false;
    this.buffered = {
      get length() {
        return this.owner.bufferedRanges.length;
      },
      start(index) {
        return this.owner.bufferedRanges[index][0];
      },
      end(index) {
        return this.owner.bufferedRanges[index][1];
      },
      owner: this,
    };
  }

  appendBuffer(value) {
    if (this.throwOnAppend) throw new Error('private append detail');
    this.appended.push(value);
    this.updating = true;
  }

  remove(start, end) {
    this.removed.push([start, end]);
    if (this.bufferedRanges.length > 0) {
      const previousEnd = this.bufferedRanges[0][1];
      this.bufferedRanges[0] = [end, previousEnd];
    }
    this.updating = true;
  }

  finishUpdate() {
    this.updating = false;
    this.dispatch('updateend');
  }
}


class FakeMediaSource extends FakeEventTarget {
  static isTypeSupported(mime) {
    return mime.includes('avc1.');
  }

  constructor() {
    super();
    this.readyState = 'closed';
    this.sourceBuffers = [];
    this.mimeTypes = [];
  }

  addSourceBuffer(mime) {
    this.mimeTypes.push(mime);
    const sourceBuffer = new FakeSourceBuffer();
    this.sourceBuffers.push(sourceBuffer);
    return sourceBuffer;
  }

  open() {
    this.readyState = 'open';
    this.dispatch('sourceopen');
  }
}


function playerFixture({
  supported = true,
  response = null,
  playReject = false,
  playResults = [],
  mediaTypeSupported = (mime) => mime.includes('avc1.'),
} = {}) {
  const image = new FakeElement();
  image.src = '/live.mjpeg';
  image.setAttribute('aria-hidden', 'false');
  const video = new FakeElement({playReject, playResults});
  video.setAttribute('aria-hidden', 'true');
  const statusElement = new FakeElement();
  const sockets = [];
  const requests = [];
  const timerCalls = [];
  const mediaSources = [];
  const objectUrls = [];
  const revokedUrls = [];
  const window = new FakeEventTarget();
  const WebSocketClass = class extends FakeWebSocket {
    constructor(url) {
      super(url);
      sockets.push(this);
    }
  };
  const MediaSourceClass = class extends FakeMediaSource {
    static isTypeSupported(mime) {
      return mediaTypeSupported(mime);
    }

    constructor() {
      super();
      mediaSources.push(this);
    }
  };
  const environment = {
    image,
    video,
    statusElement,
    MediaSource: supported ? MediaSourceClass : null,
    WebSocket: supported ? WebSocketClass : null,
    URL: {
      createObjectURL() {
        const value = `blob:hd-player-${objectUrls.length + 1}`;
        objectUrls.push(value);
        return value;
      },
      revokeObjectURL(value) {
        revokedUrls.push(value);
      },
    },
    location: {
      protocol: 'http:',
      host: 'monitor.test:8080',
    },
    async fetch(url, options) {
      requests.push({url, options});
      return response ?? {
        ok: true,
        status: 201,
        async json() {
          return {ticket: 'opaque-ticket', expires_in: 10};
        },
      };
    },
    setTimeout(callback, milliseconds) {
      timerCalls.push({callback, milliseconds, cleared: false});
      return timerCalls.length;
    },
    clearTimeout(identifier) {
      const timer = timerCalls[identifier - 1];
      if (timer) timer.cleared = true;
    },
    window,
  };
  return {
    environment,
    image,
    mediaSources,
    objectUrls,
    requests,
    revokedUrls,
    sockets,
    statusElement,
    timerCalls,
    video,
    window,
  };
}


async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}


function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return {promise, reject, resolve};
}


test('1x creates no HD ticket or WebSocket', async () => {
  const fixture = playerFixture();
  const player = createHdPlayer(fixture.environment);

  player.selectZoom(1);
  await flushPromises();

  assert.equal(fixture.requests.length, 0);
  assert.equal(fixture.sockets.length, 0);
  assert.equal(fixture.image.src, '/live.mjpeg');
});


test('2x requests one ticket and sends it as the first WebSocket message', async () => {
  const fixture = playerFixture();
  const player = createHdPlayer(fixture.environment);

  player.selectZoom(2);
  await flushPromises();

  assert.deepEqual(fixture.requests, [{
    url: '/api/hd-session',
    options: {method: 'POST'},
  }]);
  assert.equal(fixture.sockets.length, 1);
  assert.equal(fixture.sockets[0].url, 'ws://monitor.test:8080/live-hd.ws');
  assert.equal(fixture.sockets[0].url.includes('opaque-ticket'), false);
  assert.equal(fixture.sockets[0].binaryType, 'arraybuffer');
  assert.deepEqual(fixture.sockets[0].sent, []);
  fixture.sockets[0].open();
  assert.deepEqual(fixture.sockets[0].sent, ['opaque-ticket']);
  assert.equal(fixture.statusElement.textContent, 'HD_LOADING');
});


test('2x to 3x reuses the same loading HD session', async () => {
  const fixture = playerFixture();
  const player = createHdPlayer(fixture.environment);

  player.selectZoom(2);
  await flushPromises();
  player.selectZoom(3);
  await flushPromises();

  assert.equal(fixture.requests.length, 1);
  assert.equal(fixture.sockets.length, 1);
});


test('missing browser MSE support preserves MJPEG and reports unsupported', async () => {
  const fixture = playerFixture({supported: false});
  const player = createHdPlayer(fixture.environment);

  player.selectZoom(2);
  await flushPromises();

  assert.equal(fixture.requests.length, 0);
  assert.equal(fixture.sockets.length, 0);
  assert.equal(fixture.image.src, '/live.mjpeg');
  assert.equal(fixture.image.getAttribute('aria-hidden'), 'false');
  assert.equal(fixture.statusElement.textContent, 'HD_UNSUPPORTED');
});


test('ticket capacity rejection reports only HD_BUSY and opens no socket', async () => {
  const fixture = playerFixture({
    response: {
      ok: false,
      status: 429,
      async json() {
        return {result: 'HD_BUSY', detail: 'must-not-render'};
      },
    },
  });
  const player = createHdPlayer(fixture.environment);

  player.selectZoom(2);
  await flushPromises();

  assert.equal(fixture.sockets.length, 0);
  assert.equal(fixture.statusElement.textContent, 'HD_BUSY');
  assert.equal(fixture.statusElement.textContent.includes('detail'), false);
  assert.equal(fixture.image.src, '/live.mjpeg');
});


async function beginMse(fixture, mime = 'video/mp4; codecs="avc1.640033"') {
  const player = createHdPlayer(fixture.environment);
  player.selectZoom(2);
  await flushPromises();
  const socket = fixture.sockets[0];
  socket.open();
  socket.message(JSON.stringify({type: 'mse', value: mime}));
  return {player, socket};
}


async function activateHd(fixture) {
  const active = await beginMse(fixture);
  fixture.mediaSources[0].open();
  active.socket.message(new Uint8Array([0, 1, 2]).buffer);
  fixture.video.dispatch('playing');
  return active;
}


test('HD layer waits for playing before replacing and releasing MJPEG', async () => {
  const fixture = playerFixture();
  const {socket} = await beginMse(fixture);

  assert.equal(fixture.mediaSources.length, 1);
  assert.equal(fixture.video.src, 'blob:hd-player-1');
  fixture.mediaSources[0].open();
  const sourceBuffer = fixture.mediaSources[0].sourceBuffers[0];
  socket.message(new Uint8Array([0, 1, 2]).buffer);

  assert.equal(sourceBuffer.appended.length, 1);
  assert.equal(fixture.image.src, '/live.mjpeg');
  assert.equal(fixture.image.getAttribute('aria-hidden'), 'false');
  assert.equal(fixture.video.getAttribute('aria-hidden'), 'true');
  fixture.video.dispatch('playing');

  assert.equal(fixture.image.src, BLANK_IMAGE_SRC);
  assert.equal(fixture.image.getAttribute('aria-hidden'), 'true');
  assert.equal(fixture.video.getAttribute('aria-hidden'), 'false');
  assert.equal(fixture.statusElement.textContent, 'HD_ACTIVE');
});


test('SourceBuffer appends fragments in arrival order without overlap', async () => {
  const fixture = playerFixture();
  const {socket} = await beginMse(fixture);
  fixture.mediaSources[0].open();
  const sourceBuffer = fixture.mediaSources[0].sourceBuffers[0];
  const first = new Uint8Array([1]).buffer;
  const second = new Uint8Array([2]).buffer;

  socket.message(first);
  socket.message(second);

  assert.deepEqual(sourceBuffer.appended, [first]);
  sourceBuffer.finishUpdate();
  assert.deepEqual(sourceBuffer.appended, [first, second]);
});


test('active HD playback continues appending later media fragments', async () => {
  const fixture = playerFixture();
  const {socket} = await activateHd(fixture);
  const sourceBuffer = fixture.mediaSources[0].sourceBuffers[0];
  sourceBuffer.finishUpdate();
  const later = new Uint8Array([9]).buffer;

  socket.message(later);

  assert.equal(fixture.statusElement.textContent, 'HD_ACTIVE');
  assert.deepEqual(
    new Uint8Array(sourceBuffer.appended.at(-1)),
    new Uint8Array(later),
  );
});


test('queued MSE fragments are bounded while SourceBuffer is busy', async () => {
  const fixture = playerFixture();
  const {socket} = await beginMse(fixture);
  fixture.mediaSources[0].open();
  socket.message(new Uint8Array([0]).buffer);

  for (let index = 0; index < 5; index += 1) {
    socket.message(new Uint8Array(4 * 1024 * 1024).buffer);
  }

  assert.equal(fixture.statusElement.textContent, 'HD_FALLBACK');
  assert.equal(fixture.image.src, '/live.mjpeg');
  assert.equal(socket.closeCalls, 1);
});


test('unsupported codec and binary-before-description fail closed on MJPEG', async () => {
  for (const firstMessage of [
    JSON.stringify({type: 'mse', value: 'video/mp4; codecs="hvc1.1.6"'}),
    new Uint8Array([7]).buffer,
  ]) {
    const fixture = playerFixture();
    const player = createHdPlayer(fixture.environment);
    player.selectZoom(2);
    await flushPromises();
    fixture.sockets[0].open();
    fixture.sockets[0].message(firstMessage);

    assert.equal(fixture.image.src, '/live.mjpeg');
    assert.equal(fixture.image.getAttribute('aria-hidden'), 'false');
    assert.equal(fixture.video.getAttribute('aria-hidden'), 'true');
    assert.equal(fixture.statusElement.textContent, 'HD_FALLBACK');
    assert.equal(fixture.sockets[0].closeCalls, 1);
  }
});


test('H.265 is rejected even when the browser reports that MIME as supported', async () => {
  const fixture = playerFixture({mediaTypeSupported: () => true});
  const player = createHdPlayer(fixture.environment);
  player.selectZoom(2);
  await flushPromises();
  fixture.sockets[0].open();

  fixture.sockets[0].message(JSON.stringify({
    type: 'mse',
    value: 'video/mp4; codecs="hvc1.1.6"',
  }));

  assert.equal(fixture.statusElement.textContent, 'HD_FALLBACK');
  assert.equal(fixture.image.src, '/live.mjpeg');
  assert.equal(fixture.sockets[0].closeCalls, 1);
});


test('fragment arriving before sourceopen waits for append before play', async () => {
  const fixture = playerFixture();
  const {socket} = await beginMse(fixture);

  socket.message(new Uint8Array([5]).buffer);

  assert.equal(fixture.video.playCalls, 0);
  fixture.mediaSources[0].open();
  assert.equal(fixture.mediaSources[0].sourceBuffers[0].appended.length, 1);
  assert.equal(fixture.video.playCalls, 1);
});


test('returning to 1x restores MJPEG before closing and clearing HD', async () => {
  const fixture = playerFixture();
  const {player, socket} = await activateHd(fixture);

  player.selectZoom(1);

  assert.equal(fixture.image.src, '/live.mjpeg');
  assert.equal(fixture.image.getAttribute('aria-hidden'), 'true');
  assert.equal(fixture.video.getAttribute('aria-hidden'), 'false');
  assert.equal(socket.closeCalls, 0);
  assert.deepEqual(fixture.revokedUrls, []);

  fixture.image.dispatch('load');

  assert.equal(fixture.image.getAttribute('aria-hidden'), 'false');
  assert.equal(fixture.video.getAttribute('aria-hidden'), 'true');
  assert.equal(socket.closeCalls, 1);
  assert.deepEqual(fixture.revokedUrls, ['blob:hd-player-1']);
  assert.equal(fixture.statusElement.textContent, '');
});


test('failed MJPEG return keeps the last HD frame and socket', async () => {
  const fixture = playerFixture();
  const {player, socket} = await activateHd(fixture);

  player.selectZoom(1);
  fixture.image.dispatch('error');

  assert.equal(fixture.image.getAttribute('aria-hidden'), 'true');
  assert.equal(fixture.video.getAttribute('aria-hidden'), 'false');
  assert.equal(socket.closeCalls, 0);
  assert.deepEqual(fixture.revokedUrls, []);
  assert.equal(fixture.statusElement.textContent, 'HD_FALLBACK');
});


test('HD socket loss restores MJPEG without changing the selected zoom', async () => {
  const fixture = playerFixture();
  const {player, socket} = await activateHd(fixture);

  socket.serverClose();

  assert.equal(fixture.image.src, '/live.mjpeg');
  assert.equal(fixture.video.getAttribute('aria-hidden'), 'false');
  fixture.image.dispatch('load');
  assert.equal(fixture.image.getAttribute('aria-hidden'), 'false');
  assert.equal(fixture.video.getAttribute('aria-hidden'), 'true');
  assert.equal(fixture.statusElement.textContent, 'HD_FALLBACK');

  player.selectZoom(3);
  await flushPromises();
  assert.equal(fixture.sockets.length, 1);
});


test('eight-second HD startup timeout preserves MJPEG and requires a 1x reset', async () => {
  const fixture = playerFixture();
  const player = createHdPlayer(fixture.environment);

  player.selectZoom(2);
  await flushPromises();

  const timeout = fixture.timerCalls.find((call) => call.milliseconds === 8000);
  assert.ok(timeout);
  timeout.callback();
  assert.equal(fixture.image.src, '/live.mjpeg');
  assert.equal(fixture.statusElement.textContent, 'HD_FALLBACK');
  assert.equal(fixture.sockets[0].closeCalls, 1);

  player.selectZoom(3);
  await flushPromises();
  assert.equal(fixture.sockets.length, 1);
  player.selectZoom(1);
  player.selectZoom(2);
  await flushPromises();
  assert.equal(fixture.sockets.length, 2);
});


test('autoplay rejection is redacted and leaves the current MJPEG visible', async () => {
  const fixture = playerFixture({playReject: true});
  const {socket} = await beginMse(fixture);
  fixture.mediaSources[0].open();
  socket.message(new Uint8Array([9]).buffer);
  await flushPromises();

  assert.equal(fixture.image.src, '/live.mjpeg');
  assert.equal(fixture.image.getAttribute('aria-hidden'), 'false');
  assert.equal(fixture.statusElement.textContent, 'HD_FALLBACK');
  assert.equal(fixture.statusElement.textContent.includes('private'), false);
});


test('old play rejection cannot tear down a newer active session', async () => {
  const oldPlay = deferred();
  const fixture = playerFixture({
    playResults: [oldPlay.promise, Promise.resolve()],
  });
  const first = await beginMse(fixture);
  fixture.mediaSources[0].open();
  first.socket.message(new Uint8Array([1]).buffer);

  await first.player.selectZoom(1);
  first.player.selectZoom(2);
  await flushPromises();
  const secondSocket = fixture.sockets[1];
  secondSocket.open();
  secondSocket.message(JSON.stringify({
    type: 'mse',
    value: 'video/mp4; codecs="avc1.640033"',
  }));
  fixture.mediaSources[1].open();
  secondSocket.message(new Uint8Array([2]).buffer);
  fixture.video.dispatch('playing');
  assert.equal(fixture.statusElement.textContent, 'HD_ACTIVE');

  oldPlay.reject(new Error('late private rejection'));
  await flushPromises();

  assert.equal(fixture.statusElement.textContent, 'HD_ACTIVE');
  assert.equal(secondSocket.closeCalls, 0);
  assert.equal(fixture.video.getAttribute('aria-hidden'), 'false');
});


test('old playing handler cannot activate a newer loading generation', async () => {
  const fixture = playerFixture();
  const first = await beginMse(fixture);
  fixture.mediaSources[0].open();
  first.socket.message(new Uint8Array([1]).buffer);
  const oldPlaying = fixture.video.listeners.get('playing')[0].listener;

  await first.player.selectZoom(1);
  first.player.selectZoom(2);
  await flushPromises();
  const secondSocket = fixture.sockets[1];
  secondSocket.open();
  secondSocket.message(JSON.stringify({
    type: 'mse',
    value: 'video/mp4; codecs="avc1.640033"',
  }));
  fixture.mediaSources[1].open();
  secondSocket.message(new Uint8Array([2]).buffer);

  oldPlaying({type: 'playing', target: fixture.video});

  assert.equal(fixture.statusElement.textContent, 'HD_LOADING');
  assert.equal(fixture.image.getAttribute('aria-hidden'), 'false');
  assert.equal(fixture.video.getAttribute('aria-hidden'), 'true');
});


test('old updateend handler cannot append into a newer SourceBuffer', async () => {
  const fixture = playerFixture();
  const first = await beginMse(fixture);
  fixture.mediaSources[0].open();
  const oldBuffer = fixture.mediaSources[0].sourceBuffers[0];
  first.socket.message(new Uint8Array([1]).buffer);
  const oldUpdateEnd = oldBuffer.listeners.get('updateend')[0].listener;

  await first.player.selectZoom(1);
  first.player.selectZoom(2);
  await flushPromises();
  const secondSocket = fixture.sockets[1];
  secondSocket.open();
  secondSocket.message(JSON.stringify({
    type: 'mse',
    value: 'video/mp4; codecs="avc1.640033"',
  }));
  fixture.mediaSources[1].open();
  const currentBuffer = fixture.mediaSources[1].sourceBuffers[0];
  const firstCurrent = new Uint8Array([2]).buffer;
  const queuedCurrent = new Uint8Array([3]).buffer;
  secondSocket.message(firstCurrent);
  secondSocket.message(queuedCurrent);
  currentBuffer.updating = false;

  oldUpdateEnd({type: 'updateend', target: oldBuffer});

  assert.deepEqual(currentBuffer.appended, [firstCurrent]);
});


test('active append failure keeps HD visible until MJPEG has loaded', async () => {
  const fixture = playerFixture();
  const {socket} = await activateHd(fixture);
  const sourceBuffer = fixture.mediaSources[0].sourceBuffers[0];
  sourceBuffer.updating = false;
  sourceBuffer.throwOnAppend = true;

  socket.message(new Uint8Array([7]).buffer);

  assert.equal(fixture.statusElement.textContent, 'HD_FALLBACK');
  assert.equal(fixture.image.src, '/live.mjpeg');
  assert.equal(fixture.image.getAttribute('aria-hidden'), 'true');
  assert.equal(fixture.video.getAttribute('aria-hidden'), 'false');
  assert.equal(socket.closeCalls, 0);

  fixture.image.dispatch('load');
  assert.equal(fixture.image.getAttribute('aria-hidden'), 'false');
  assert.equal(fixture.video.getAttribute('aria-hidden'), 'true');
  assert.equal(socket.closeCalls, 1);
});


test('MediaSource and SourceBuffer errors use the no-black fallback path', async () => {
  const loadingFixture = playerFixture();
  await beginMse(loadingFixture);
  loadingFixture.mediaSources[0].dispatch('error');
  assert.equal(loadingFixture.statusElement.textContent, 'HD_FALLBACK');
  assert.equal(loadingFixture.image.getAttribute('aria-hidden'), 'false');

  const activeFixture = playerFixture();
  const {socket} = await activateHd(activeFixture);
  activeFixture.mediaSources[0].sourceBuffers[0].dispatch('error');
  assert.equal(activeFixture.image.getAttribute('aria-hidden'), 'true');
  assert.equal(activeFixture.video.getAttribute('aria-hidden'), 'false');
  assert.equal(socket.closeCalls, 0);
});


test('server error after activation keeps HD visible until MJPEG has loaded', async () => {
  const fixture = playerFixture();
  const {socket} = await activateHd(fixture);

  socket.message(JSON.stringify({type: 'error', value: 'HD_FALLBACK'}));

  assert.equal(fixture.statusElement.textContent, 'HD_FALLBACK');
  assert.equal(fixture.image.src, '/live.mjpeg');
  assert.equal(fixture.image.getAttribute('aria-hidden'), 'true');
  assert.equal(fixture.video.getAttribute('aria-hidden'), 'false');
  assert.equal(socket.closeCalls, 0);
});


test('completed append trims to twenty seconds and seeks near the live edge', async () => {
  const fixture = playerFixture();
  const {socket} = await beginMse(fixture);
  fixture.mediaSources[0].open();
  const sourceBuffer = fixture.mediaSources[0].sourceBuffers[0];
  sourceBuffer.bufferedRanges = [[0, 25]];
  fixture.video.currentTime = 10;
  socket.message(new Uint8Array([4]).buffer);

  sourceBuffer.finishUpdate();

  assert.ok(fixture.video.currentTime >= 24 && fixture.video.currentTime < 25);
  assert.deepEqual(sourceBuffer.removed, [[0, 5]]);
});


test('destroy closes the socket and revokes the MediaSource URL', async () => {
  const fixture = playerFixture();
  const {player, socket} = await activateHd(fixture);

  player.destroy();

  assert.equal(socket.closeCalls, 1);
  assert.deepEqual(fixture.revokedUrls, ['blob:hd-player-1']);
});


test('pagehide automatically releases the active HD session', async () => {
  const fixture = playerFixture();
  const {socket} = await activateHd(fixture);

  fixture.window.dispatch('pagehide');

  assert.equal(socket.closeCalls, 1);
  assert.deepEqual(fixture.revokedUrls, ['blob:hd-player-1']);
  assert.equal(fixture.video.src, '');
});


test('BFCache page lifecycle releases HD and resumes without a destroyed player', async () => {
  const fixture = playerFixture();
  await activateHd(fixture);

  fixture.window.dispatch('pagehide', {persisted: true});

  assert.equal(fixture.sockets[0].closeCalls, 1);
  assert.equal(fixture.image.src, '/live.mjpeg');
  assert.equal(fixture.image.getAttribute('aria-hidden'), 'false');
  assert.equal(fixture.video.getAttribute('aria-hidden'), 'true');

  fixture.window.dispatch('pageshow', {persisted: true});
  await flushPromises();

  assert.equal(fixture.requests.length, 2);
  assert.equal(fixture.sockets.length, 2);
  assert.equal(fixture.statusElement.textContent, 'HD_LOADING');
});


test('stale MJPEG restore callback cannot tear down BFCache-resumed HD', async () => {
  const fixture = playerFixture();
  const {player} = await activateHd(fixture);
  player.selectZoom(1);
  const pendingZoom = player.selectZoom(2);
  const oldRestore = fixture.image.listeners.get('load')[0].listener;

  fixture.window.dispatch('pagehide', {persisted: true});
  fixture.window.dispatch('pageshow', {persisted: true});
  await pendingZoom;
  await flushPromises();
  const resumedSocket = fixture.sockets[1];

  oldRestore({type: 'load', target: fixture.image});

  assert.equal(fixture.statusElement.textContent, 'HD_LOADING');
  assert.equal(resumedSocket.closeCalls, 0);
});


test('BFCache does not retry an HD failure without a 1x reset', async () => {
  const fixture = playerFixture();
  const player = createHdPlayer(fixture.environment);
  player.selectZoom(2);
  await flushPromises();
  fixture.sockets[0].fail();
  assert.equal(fixture.statusElement.textContent, 'HD_FALLBACK');

  fixture.window.dispatch('pagehide', {persisted: true});
  fixture.window.dispatch('pageshow', {persisted: true});
  await flushPromises();

  assert.equal(fixture.requests.length, 1);
  assert.equal(fixture.sockets.length, 1);
  assert.equal(fixture.statusElement.textContent, 'HD_FALLBACK');
});


test('pending restore waiter cannot start HD while the page is suspended', async () => {
  const fixture = playerFixture();
  const {player} = await activateHd(fixture);
  player.selectZoom(1);
  const pendingZoom = player.selectZoom(2);

  fixture.window.dispatch('pagehide', {persisted: true});
  await flushPromises();

  assert.equal(fixture.requests.length, 1);
  assert.equal(fixture.sockets.length, 1);

  fixture.window.dispatch('pageshow', {persisted: true});
  await pendingZoom;
  await flushPromises();

  assert.equal(fixture.requests.length, 2);
  assert.equal(fixture.sockets.length, 2);
});


test('server-side connection limit reports HD_BUSY before an MSE description', async () => {
  const fixture = playerFixture();
  const player = createHdPlayer(fixture.environment);
  player.selectZoom(2);
  await flushPromises();
  const socket = fixture.sockets[0];
  socket.open();

  socket.message(JSON.stringify({type: 'error', value: 'HD_BUSY'}));

  assert.equal(player.status(), 'HD_BUSY');
  assert.equal(fixture.statusElement.textContent, 'HD_BUSY');
  assert.equal(fixture.image.src, '/live.mjpeg');
  assert.equal(socket.closeCalls, 1);
});


test('ticket send failure is redacted and falls back without an uncaught event error', async () => {
  const fixture = playerFixture();
  const player = createHdPlayer(fixture.environment);
  player.selectZoom(2);
  await flushPromises();
  const socket = fixture.sockets[0];
  socket.send = () => {
    throw new Error('private transport detail');
  };

  assert.doesNotThrow(() => socket.open());
  assert.equal(player.status(), 'HD_FALLBACK');
  assert.equal(fixture.statusElement.textContent.includes('private'), false);
  assert.equal(fixture.image.src, '/live.mjpeg');
});
