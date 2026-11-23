const { test } = require('node:test');
const assert = require('node:assert/strict');
const CallLatency = require('../static/js/call-latency.js');

test('total ends at first playback and does not include reply audio duration', async () => {
  let now = 100;
  const timing = new CallLatency({ captured_at_ms: 100, vad_wait_ms: 400 }, () => now);
  await timing.measure('stt_ms', async () => { now += 900; });
  timing.stt_server_ms = 700;
  await timing.measure('reply_ms', async () => { now += 200; });
  await timing.measure('tts_ms', async () => { now += 300; });
  timing.beginPlayback(); now += 50; timing.audioStarted();
  assert.equal(timing.total_ms, 1850);
  assert.equal(timing.play_ms, 50);
  now += 10000; timing.audioStarted();
  assert.equal(timing.total_ms, 1850);
  assert.match(timing.description(), /HTTP còn lại ước tính: 200 ms/);
});

test('missing or failed timing is explicit rather than fabricated', async () => {
  let now = 0; const timing = new CallLatency({}, () => now);
  await assert.rejects(timing.measure('tts_ms', async () => { now = 10; throw Error('unavailable'); }));
  assert.equal(timing.tts_ms, 10);
  assert.match(timing.description(), /chưa đo được/);
  assert.doesNotMatch(timing.description(), /NaN/);
});
