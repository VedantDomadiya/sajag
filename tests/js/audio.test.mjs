// Unit tests for web/audio.js (chunking + WAV encoding). Run: node --test tests/js
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const src = readFileSync(new URL("../../web/audio.js", import.meta.url), "utf8");
const sandbox = { window: {}, btoa, Float32Array, ArrayBuffer, DataView, Uint8Array, String, Math, setInterval, clearInterval };
vm.runInNewContext(src, sandbox);
const { FileCall, toBase64, encodeWav, downsample, TARGET_RATE } = sandbox.window.SajagAudio;

test("downsample averages windows to 16 kHz", () => {
  const input = new Float32Array([0, 1, 0, 1, 0, 1]); // 48 kHz -> 16 kHz is a 3:1 ratio
  const out = downsample(input, 48000);
  assert.equal(out.length, 2);
  assert.ok(Math.abs(out[0] - 1 / 3) < 1e-6);
  assert.equal(downsample(input, TARGET_RATE), input); // already 16 kHz: untouched
});

test("encodeWav writes a valid 16-bit mono 16 kHz header and clamps samples", () => {
  const buf = encodeWav(new Float32Array([0, 0.5, -0.5, 2, -2]), 16000);
  const v = new DataView(buf);
  const tag = (o) => String.fromCharCode(...new Uint8Array(buf, o, 4));
  assert.equal(tag(0), "RIFF");
  assert.equal(tag(8), "WAVE");
  assert.equal(v.getUint16(22, true), 1); // mono
  assert.equal(v.getUint32(24, true), 16000);
  assert.equal(v.getUint16(34, true), 16); // bits per sample
  assert.equal(v.getUint32(40, true), 5 * 2);
  assert.equal(v.getInt16(44 + 3 * 2, true), 0x7fff); // 2 clamped to +1
  assert.equal(v.getInt16(44 + 4 * 2, true), -0x8000); // -2 clamped to -1
});

test("toBase64 matches Node's encoder, including large buffers", () => {
  const bytes = new Uint8Array(100_000).map((_, i) => i % 251);
  assert.equal(toBase64(bytes.buffer), Buffer.from(bytes).toString("base64"));
});

test("FileCall emits one chunk per 5 s of played audio, then the tail, then ends", () => {
  const rate = 16000;
  const seconds = 12.5;
  const data = new Float32Array(rate * seconds);
  const ctx = {
    currentTime: 0,
    destination: {},
    createGain: () => ({ connect() {}, gain: { setTargetAtTime() {} } }),
    createBufferSource: () => ({ connect() {}, start() {}, stop() {} }),
  };
  const buffer = { numberOfChannels: 1, sampleRate: rate, duration: seconds, getChannelData: () => data };
  const chunks = [];
  let ended = null;
  const call = new FileCall(ctx, buffer, 5, (c) => chunks.push(c), (why) => (ended = why));
  call.start();
  ctx.currentTime = 11; // playback has passed 5 s and 10 s
  call.tick();
  assert.deepEqual(chunks.map((c) => [c.t0, c.t1]), [[0, 5], [5, 10]]);
  call.finish(); // natural end: emits the 2.5 s tail
  assert.deepEqual(chunks.at(-1).t0, 10);
  assert.equal(ended, "ended");
  assert.equal(chunks.length, 3);
});

test("FileCall skips slivers shorter than 0.8 s", () => {
  const rate = 16000;
  const data = new Float32Array(rate * 5.5);
  const ctx = { currentTime: 0, destination: {}, createGain: () => ({ connect() {}, gain: { setTargetAtTime() {} } }), createBufferSource: () => ({ connect() {}, start() {}, stop() {} }) };
  const chunks = [];
  const call = new FileCall(ctx, { numberOfChannels: 1, sampleRate: rate, duration: 5.5, getChannelData: () => data }, 5, (c) => chunks.push(c), () => {});
  call.start();
  ctx.currentTime = 5.2;
  call.tick();
  call.finish();
  assert.equal(chunks.length, 1); // the 0.5 s tail is dropped
});
