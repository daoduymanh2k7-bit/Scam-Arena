const { test } = require('node:test');
const assert = require('node:assert/strict');
const CallStream = require('../static/js/call-stream.js');

function fixture() {
  const sockets = [], drafts = [];
  const stream = new CallStream(text => drafts.push(text), { createSocket: () => {
    const ws = { bufferedAmount: 0, sent: [], send(data) { this.sent.push(data); }, close() { this.closed = true; },
      event(data) { this.onmessage({ data: JSON.stringify(data) }); } };
    sockets.push(ws); return ws;
  } });
  return { stream, sockets, drafts };
}

test('queues PCM during handshake, shows drafts and waits for complete final', async () => {
  const { stream, sockets, drafts } = fixture();
  stream.start(); const ws = sockets[0];
  stream.offer(new Float32Array([0.5, -0.5]));
  assert.equal(ws.sent.length, 0);
  ws.event({ type: 'ready' });
  assert.equal(new DataView(ws.sent[0]).getInt16(0, true), 16384);
  ws.event({ type: 'draft', text: 'Tôi đồng ý' });
  assert.deepEqual(drafts, ['Tôi đồng ý']);
  const result = stream.finish();
  assert.equal(ws.sent[1], '{"type":"finish"}');
  ws.event({ type: 'draft', text: 'Không dùng câu này' });
  ws.event({ type: 'final', text: 'Tôi chưa đồng ý.' });
  assert.equal((await result).text, 'Tôi chưa đồng ý.');
  assert.equal(drafts.length, 1);
  assert.ok(ws.closed);
});

test('finish before ready flushes queued audio before finish control', async () => {
  const { stream, sockets } = fixture();
  stream.start(); stream.offer(new Float32Array(512));
  const result = stream.finish(); const ws = sockets[0];
  ws.event({ type: 'ready' });
  assert.ok(ws.sent[0] instanceof ArrayBuffer);
  assert.equal(ws.sent[1], '{"type":"finish"}');
  ws.event({ type: 'final', text: 'Được rồi.' });
  await result;
});

test('cancel and late replies cannot contaminate next utterance', async () => {
  const { stream, sockets, drafts } = fixture();
  stream.start(); const old = sockets[0];
  const pending = stream.finish();
  stream.cancel(); await assert.rejects(pending);
  stream.start();
  old.event({ type: 'draft', text: 'stale' });
  assert.equal(drafts.length, 0);
  assert.ok(old.closed);
  stream.cancel();
});

test('connection errors and excessive backpressure reject for REST fallback', async () => {
  for (const mode of ['network', 'backpressure']) {
    const { stream, sockets } = fixture();
    stream.start(); const ws = sockets[0]; const pending = stream.session.result;
    if (mode === 'network') ws.onerror();
    else { ws.bufferedAmount = 128001; stream.offer(new Float32Array(512)); }
    await assert.rejects(pending);
    assert.ok(stream.failed && ws.closed);
    stream.start(); assert.equal(sockets.length, 1);
  }
});
