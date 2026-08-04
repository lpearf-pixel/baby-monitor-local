(function buildModule(root, factory) {
  'use strict';

  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.BabyMonitorHdPlayer = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function buildApi() {
  'use strict';

  const BLANK_IMAGE_SRC =
    'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';
  const LIVE_MJPEG_SRC = '/live.mjpeg';
  const PUBLIC_CODES = new Set([
    'HD_LOADING',
    'HD_ACTIVE',
    'HD_FALLBACK',
    'HD_UNSUPPORTED',
    'HD_BUSY',
  ]);

  function websocketUrl(location) {
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${scheme}//${location.host}/live-hd.ws`;
  }

  function createHdPlayer(environment) {
    const {
      MediaSource,
      WebSocket,
      URL,
      fetch,
      image,
      location,
      setTimeout,
      clearTimeout,
      statusElement,
      video,
      window,
    } = environment;
    let publicStatus = '';
    let desiredZoom = 1;
    let mode = 'idle';
    let destroyed = false;
    let retryBlocked = false;
    let generation = 0;
    let mediaSource = null;
    let sourceBuffer = null;
    let socket = null;
    let objectUrl = null;
    let transitionTimer = null;
    let restorePromise = null;
    let descriptionReceived = false;
    let pendingMime = null;
    let playRequested = false;
    let intentionallyClosing = false;
    const appendQueue = [];

    function setStatus(code) {
      publicStatus = PUBLIC_CODES.has(code) ? code : 'HD_FALLBACK';
      statusElement.textContent = publicStatus;
    }

    function clearStatus() {
      publicStatus = '';
      statusElement.textContent = '';
    }

    function clearTransitionTimer() {
      if (transitionTimer !== null) {
        clearTimeout(transitionTimer);
        transitionTimer = null;
      }
    }

    function show(element) {
      element.setAttribute('aria-hidden', 'false');
    }

    function hide(element) {
      element.setAttribute('aria-hidden', 'true');
    }

    function supported() {
      return Boolean(
        MediaSource &&
        WebSocket &&
        URL &&
        typeof MediaSource.isTypeSupported === 'function',
      );
    }

    function cleanupHd() {
      clearTransitionTimer();
      generation += 1;
      appendQueue.length = 0;
      descriptionReceived = false;
      pendingMime = null;
      playRequested = false;
      sourceBuffer = null;
      mediaSource = null;
      intentionallyClosing = true;
      if (socket !== null) {
        try {
          socket.close();
        } catch (_error) {
          // Cleanup is idempotent; public output remains redacted.
        }
        socket = null;
      }
      intentionallyClosing = false;
      try {
        video.pause();
      } catch (_error) {
        // Detached browser elements may not implement pause fully.
      }
      video.src = '';
      try {
        video.load();
      } catch (_error) {
        // Resetting a detached element is best-effort cleanup.
      }
      if (objectUrl !== null) {
        URL.revokeObjectURL(objectUrl);
        objectUrl = null;
      }
    }

    function preserveMjpeg(code) {
      retryBlocked = true;
      setStatus(code);
      if (image.src === BLANK_IMAGE_SRC) image.src = LIVE_MJPEG_SRC;
      show(image);
      hide(video);
      cleanupHd();
      mode = 'fallback';
    }

    function maintainLiveWindow() {
      if (!sourceBuffer || sourceBuffer.updating || sourceBuffer.buffered.length === 0) {
        return false;
      }
      const last = sourceBuffer.buffered.length - 1;
      const start = sourceBuffer.buffered.start(0);
      const end = sourceBuffer.buffered.end(last);
      if (end - video.currentTime > 2) video.currentTime = Math.max(start, end - 0.5);
      if (end - start > 20) {
        sourceBuffer.remove(start, end - 20);
        return true;
      }
      return false;
    }

    function pumpAppendQueue() {
      if (!sourceBuffer || sourceBuffer.updating) return;
      try {
        if (maintainLiveWindow()) return;
        const fragment = appendQueue.shift();
        if (fragment) {
          sourceBuffer.appendBuffer(fragment);
          requestPlayback();
        }
      } catch (_error) {
        preserveMjpeg('HD_FALLBACK');
      }
    }

    function requestPlayback() {
      if (playRequested) return;
      playRequested = true;
      try {
        const result = video.play();
        if (result && typeof result.catch === 'function') {
          result.catch(() => preserveMjpeg('HD_FALLBACK'));
        }
      } catch (_error) {
        preserveMjpeg('HD_FALLBACK');
      }
    }

    function createSourceBufferIfReady(currentGeneration) {
      if (
        currentGeneration !== generation ||
        !pendingMime ||
        !mediaSource ||
        mediaSource.readyState !== 'open' ||
        sourceBuffer
      ) {
        return;
      }
      try {
        sourceBuffer = mediaSource.addSourceBuffer(pendingMime);
        sourceBuffer.addEventListener('updateend', pumpAppendQueue);
        pumpAppendQueue();
      } catch (_error) {
        preserveMjpeg('HD_FALLBACK');
      }
    }

    function parseDescription(value) {
      if (typeof value !== 'string' || value.length > 4096) return null;
      try {
        const parsed = JSON.parse(value);
        if (
          !parsed ||
          typeof parsed !== 'object' ||
          Object.keys(parsed).sort().join(',') !== 'type,value' ||
          parsed.type !== 'mse' ||
          typeof parsed.value !== 'string' ||
          !MediaSource.isTypeSupported(parsed.value)
        ) {
          return null;
        }
        const match = /^video\/mp4; codecs="([^"]+)"$/.exec(parsed.value);
        if (!match) return null;
        const codecs = match[1].split(',').map((codec) => codec.trim());
        if (!codecs.length || !codecs.every((codec) => codec.startsWith('avc1.'))) {
          return null;
        }
        return parsed.value;
      } catch (_error) {
        return null;
      }
    }

    function parseServerError(value) {
      if (typeof value !== 'string' || value.length > 4096) return null;
      try {
        const parsed = JSON.parse(value);
        if (
          !parsed ||
          typeof parsed !== 'object' ||
          Object.keys(parsed).sort().join(',') !== 'type,value' ||
          parsed.type !== 'error' ||
          typeof parsed.value !== 'string'
        ) {
          return null;
        }
        return parsed.value === 'HD_BUSY' ? 'HD_BUSY' : 'HD_FALLBACK';
      } catch (_error) {
        return null;
      }
    }

    function restoreMjpeg({failure = false} = {}) {
      if (restorePromise) return restorePromise;
      if (mode !== 'active' && mode !== 'restoring') {
        if (mode === 'loading') cleanupHd();
        image.src = LIVE_MJPEG_SRC;
        show(image);
        hide(video);
        if (desiredZoom === 1) {
          mode = 'idle';
          clearStatus();
        }
        return Promise.resolve();
      }

      mode = 'restoring';
      clearTransitionTimer();
      image.src = LIVE_MJPEG_SRC;
      show(video);
      hide(image);
      restorePromise = new Promise((resolve) => {
        let settled = false;
        const finish = (ready) => {
          if (settled) return;
          settled = true;
          image.removeEventListener('load', onLoad);
          image.removeEventListener('error', onError);
          clearTransitionTimer();
          if (ready) {
            show(image);
            hide(video);
            cleanupHd();
            mode = desiredZoom === 1 ? 'idle' : 'fallback';
            if (desiredZoom === 1 && !failure) clearStatus();
          } else {
            hide(image);
            show(video);
            setStatus('HD_FALLBACK');
            mode = 'active';
          }
          restorePromise = null;
          resolve();
          if (ready && desiredZoom > 1 && !failure) void startHd();
        };
        const onLoad = () => finish(true);
        const onError = () => finish(false);
        image.addEventListener('load', onLoad);
        image.addEventListener('error', onError);
        transitionTimer = setTimeout(() => finish(false), 8000);
      });
      return restorePromise;
    }

    function handleSocketFailure(currentGeneration, code = 'HD_FALLBACK') {
      if (currentGeneration !== generation || destroyed || intentionallyClosing) return;
      retryBlocked = true;
      setStatus(code);
      if (mode === 'active' || mode === 'restoring') {
        void restoreMjpeg({failure: true});
      } else {
        preserveMjpeg(code);
      }
    }

    function handleSocketMessage(event, currentGeneration) {
      if (currentGeneration !== generation || destroyed || mode !== 'loading') return;
      if (typeof event.data === 'string') {
        const serverError = parseServerError(event.data);
        if (serverError) {
          preserveMjpeg(serverError);
          return;
        }
        if (descriptionReceived) {
          preserveMjpeg('HD_FALLBACK');
          return;
        }
        const mime = parseDescription(event.data);
        if (!mime) {
          preserveMjpeg('HD_FALLBACK');
          return;
        }
        descriptionReceived = true;
        pendingMime = mime;
        createSourceBufferIfReady(currentGeneration);
        return;
      }
      if (!descriptionReceived || !(event.data instanceof ArrayBuffer)) {
        preserveMjpeg('HD_FALLBACK');
        return;
      }
      appendQueue.push(event.data.slice(0));
      createSourceBufferIfReady(currentGeneration);
      pumpAppendQueue();
    }

    function activateHd() {
      if (mode !== 'loading' || desiredZoom === 1 || destroyed) return;
      clearTransitionTimer();
      show(video);
      hide(image);
      image.src = BLANK_IMAGE_SRC;
      mode = 'active';
      setStatus('HD_ACTIVE');
    }

    video.addEventListener('playing', activateHd);

    async function startHd() {
      if (destroyed || desiredZoom === 1 || mode === 'loading' || mode === 'active') {
        return;
      }
      if (!supported()) {
        mode = 'fallback';
        retryBlocked = true;
        setStatus('HD_UNSUPPORTED');
        return;
      }

      mode = 'loading';
      setStatus('HD_LOADING');
      const currentGeneration = generation + 1;
      generation = currentGeneration;
      descriptionReceived = false;
      pendingMime = null;
      appendQueue.length = 0;
      playRequested = false;

      try {
        mediaSource = new MediaSource();
        objectUrl = URL.createObjectURL(mediaSource);
        video.src = objectUrl;
        mediaSource.addEventListener('sourceopen', () => {
          createSourceBufferIfReady(currentGeneration);
        });
        transitionTimer = setTimeout(
          () => handleSocketFailure(currentGeneration),
          8000,
        );

        const response = await fetch('/api/hd-session', {method: 'POST'});
        const payload = await response.json();
        if (currentGeneration !== generation || destroyed || desiredZoom === 1) return;
        if (response.status === 429 || payload.result === 'HD_BUSY') {
          preserveMjpeg('HD_BUSY');
          return;
        }
        if (!response.ok || typeof payload.ticket !== 'string' || !payload.ticket) {
          preserveMjpeg('HD_FALLBACK');
          return;
        }

        socket = new WebSocket(websocketUrl(location));
        socket.binaryType = 'arraybuffer';
        let ticketSent = false;
        socket.addEventListener('open', () => {
          if (ticketSent || currentGeneration !== generation) return;
          try {
            socket.send(payload.ticket);
            ticketSent = true;
          } catch (_error) {
            handleSocketFailure(currentGeneration);
          }
        });
        socket.addEventListener('message', (event) => {
          handleSocketMessage(event, currentGeneration);
        });
        socket.addEventListener('error', () => {
          handleSocketFailure(currentGeneration);
        });
        socket.addEventListener('close', () => {
          handleSocketFailure(currentGeneration);
        });
      } catch (_error) {
        if (currentGeneration === generation) preserveMjpeg('HD_FALLBACK');
      }
    }

    async function selectZoom(zoom) {
      desiredZoom = Number(zoom);
      if (desiredZoom === 1) {
        retryBlocked = false;
        return restoreMjpeg();
      }
      if (retryBlocked) return;
      if (restorePromise) {
        await restorePromise;
        if (desiredZoom > 1) return startHd();
        return;
      }
      return startHd();
    }

    function destroy() {
      if (destroyed) return;
      destroyed = true;
      cleanupHd();
      hide(video);
      if (image.src !== BLANK_IMAGE_SRC) show(image);
    }

    if (window && typeof window.addEventListener === 'function') {
      window.addEventListener('pagehide', destroy);
    }

    return {
      destroy,
      selectZoom,
      status: () => publicStatus,
    };
  }

  return {BLANK_IMAGE_SRC, createHdPlayer};
});
