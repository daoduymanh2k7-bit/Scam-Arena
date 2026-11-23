const { test } = require('node:test');
const assert = require('node:assert/strict');
const { Capture } = require('../static/js/call-microphone.js');

function fixture(overrides = {}) {
  const track = { enabled: true, stop() { this.stopped = true; } };
  const context = { state: 'running', resume: async () => {}, close: async () => { context.state = 'closed'; } };
  let options;
  const events = [];
  const vad = { processFrame: async () => {}, start: async () => {}, pause: async () => {},
    setOptions: () => {}, destroy: async () => { vad.destroyed = true; } };
  const capture = new Capture({ onSpeech: data => events.push(data), ...overrides.callbacks }, {
    context, getStream: async () => ({ getTracks: () => [track], getAudioTracks: () => [track] }),
    createVad: async value => { options = value; return vad; }, ...overrides.dependencies,
  });
  return { capture, track, context, events, vad, options: () => options };
}

test('one utterance closes capture until the next listening turn', async () => {
  const f = fixture();
  await f.capture.initialize(); await f.capture.setEnabled(true);
  await f.capture._queueFrame(async () => {
    f.options().onSpeechEnd(new Float32Array(1600));
    f.options().onSpeechEnd(new Float32Array(1600));
  });
  await f.capture.transitions;
  assert.equal(f.events.length, 1);
  assert.equal(f.events[0].rate, 16000);
  assert.equal(f.events[0].capture_method, 'Silero VAD v5');
  assert.equal(f.track.enabled, false);
  let processed = false;
  await f.capture._queueFrame(async () => { processed = true; });
  assert.equal(processed, false);
  await f.capture.setEnabled(true);
  await f.capture._queueFrame(async () => f.options().onSpeechEnd(new Float32Array(1600)));
  assert.equal(f.events.length, 2);
  await f.capture.destroy();
});

test('late inference cannot submit after mute or contaminate the next turn', async () => {
  const f = fixture(); await f.capture.initialize(); await f.capture.setEnabled(true);
  let finish, entered;
  const started = new Promise(resolve => { entered = resolve; });
  const pending = f.capture._queueFrame(async () => {
    entered(); await new Promise(resolve => { finish = resolve; });
    f.options().onSpeechEnd(new Float32Array(1600));
  });
  await started;
  f.capture.setEnabled(false); f.capture.setEnabled(true); finish();
  await pending; await f.capture.transitions;
  assert.equal(f.events.length, 0);
  assert.equal(f.track.enabled, true);
  await f.capture.destroy();
  assert.equal(f.track.stopped, true);
  assert.equal(f.context.state, 'closed');
  assert.equal(f.vad.destroyed, true);
});

test('hangup while permission is pending stops the eventual stream', async () => {
  let grant; const track = { stop() { this.stopped = true; } };
  const f = fixture({ dependencies: { getStream: () => new Promise(resolve => { grant = resolve; }) } });
  const initializing = f.capture.initialize();
  await Promise.resolve();
  const destroyed = f.capture.destroy();
  grant({ getTracks: () => [track], getAudioTracks: () => [track] });
  await initializing; await destroyed;
  assert.equal(track.stopped, true);
  assert.equal(f.context.state, 'closed');
  assert.equal(f.capture.ready, false);
});

test('enable during initialization preserves the requested microphone state', async () => {
  const f = fixture(); await f.capture.setEnabled(true);
  assert.equal(f.track.enabled, true);
  assert.equal(f.capture.ready, true);
  await f.capture.destroy();
});

test('model initialization failure uses an explicitly identified fallback', async () => {
  let fallback = 0; const messages = [];
  const f = fixture({ callbacks: { onFallback: () => fallback++ }, dependencies: {
    createVad: async () => { throw new Error('offline'); },
    createLegacy: async () => ({ port: { postMessage: message => messages.push(message) }, disconnect() {} }),
  } });
  await f.capture.initialize(); await f.capture.setEnabled(true);
  assert.equal(fallback, 1);
  assert.match(f.capture.method, /dự phòng/);
  assert.equal(messages.at(-1).enabled, true);
  await f.capture.destroy();
});

test('long speech flush submits once and closes the listening gate', async () => {
  const f = fixture(); await f.capture.initialize(); await f.capture.setEnabled(true);
  let flush = false;
  f.vad.setOptions = options => { flush = options.submitUserSpeechOnPause; };
  f.vad.pause = async () => { if (flush) f.options().onSpeechEnd(new Float32Array(16000)); };
  f.capture._flushLongSpeech(f.capture.cycle);
  await f.capture.transitions; await f.capture.transitions;
  assert.equal(f.events.length, 1);
  assert.equal(f.capture.enabled, false);
  assert.equal(flush, false);
  await f.capture.destroy();
});

test('endpoint timing uses only speech frames from the current turn', async () => {
  let now = 100;
  const f = fixture({ dependencies: { now: () => now } });
  await f.capture.initialize(); await f.capture.setEnabled(true);
  await f.capture._queueFrame(async () => f.options().onFrameProcessed({ isSpeech: 0.9 }));
  now = 500;
  await f.capture._queueFrame(async () => f.options().onSpeechEnd(new Float32Array(1600)));
  assert.equal(f.events[0].vad_wait_ms, 400);
  await f.capture.setEnabled(true);
  await f.capture._queueFrame(async () => f.options().onSpeechEnd(new Float32Array(1600)));
  assert.equal(f.events[1].vad_wait_ms, null);
  await f.capture.destroy();
});

test('draft audio includes pre-roll, grows at bounded intervals and stops on mute', async () => {
  const packets = [];
  const f = fixture({ callbacks: { onPartialAudio: data => packets.push(data) } });
  await f.capture.initialize(); await f.capture.setEnabled(true);
  const frame = new Float32Array(512).fill(0.2);
  const send = () => f.capture._queueFrame(async () => f.options().onFrameProcessed({ isSpeech: 0.9 }, frame));
  for (let i = 0; i < 15; i++) await send();
  assert.equal(packets.length, 0);
  await f.capture._queueFrame(async () => f.options().onSpeechStart());
  for (let i = 0; i < 30; i++) await send();
  assert.equal(packets.length, 1);
  assert.equal(packets[0].rate, 16000);
  assert.ok(packets[0].samples.length >= 19200);
  for (let i = 0; i < 70; i++) await send();
  assert.equal(packets.length, 2);
  assert.ok(packets[1].samples.length > packets[0].samples.length);
  await f.capture.setEnabled(false);
  for (let i = 0; i < 90; i++) await send();
  assert.equal(packets.length, 2);
  await f.capture.destroy();
});
