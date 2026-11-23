const { test } = require('node:test');
const assert = require('node:assert/strict');
const PartialSpeech = require('../static/js/call-partial.js');

test('one request in flight; finalization discards late draft text', async () => {
  let resolve, calls = 0, signal; const text = [];
  const preview = new PartialSpeech((data, abort) => {
    calls++; signal = abort; return new Promise(done => { resolve = done; });
  }, value => text.push(value));
  preview.start(); const pending = preview.offer('audio');
  await preview.offer('newer audio'); assert.equal(calls, 1);
  preview.stop(); assert.equal(signal.aborted, true);
  resolve({ text: 'late words' }); await pending;
  assert.deepEqual(text, []);
});

test('old call response cannot overwrite new call or clear its in-flight state', async () => {
  const resolvers = []; const texts = [];
  const preview = new PartialSpeech(() => new Promise(resolve => resolvers.push(resolve)), text => texts.push(text));
  preview.start(); const old = preview.offer('old');
  preview.start(); const current = preview.offer('current');
  resolvers[0]({ text: 'old' }); await old;
  assert.equal(preview.busy, true);
  resolvers[1]({ text: 'current' }); await current;
  assert.deepEqual(texts, ['current']);
});

test('busy previews are skipped, failed service switches to final-only capture', async () => {
  let status = 429, notices = 0, now = 0;
  const preview = new PartialSpeech(async () => { throw Object.assign(Error(), { status }); }, () => {}, () => notices++, () => now);
  preview.start(); await preview.offer('audio'); assert.equal(preview.available, true);
  now = 1100; status = 503; await preview.offer('audio'); assert.equal(preview.available, false);
  preview.start(); assert.equal(preview.active, false); assert.equal(notices, 1);
});

test('server pacing adapts without adding a second full delay after response', async () => {
  let now = 0, calls = 0;
  const preview = new PartialSpeech(async () => { calls++; now += 800; return { text: 'tạm', next_partial_ms: 1000 }; }, () => {}, () => {}, () => now);
  preview.start(); await preview.offer('audio');
  assert.equal(preview.canOffer(), false);
  now = 1000; assert.equal(preview.canOffer(), true);
  await preview.offer('audio'); assert.equal(calls, 2);
  preview.nextAt = now + 3000; assert.equal(preview.canOffer(), false);
  preview.stop(); assert.equal(preview.canOffer(), false);
});
