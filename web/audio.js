// Audio plumbing: play a call (file) or tap the microphone, and cut either into fixed-length chunks of 16 kHz mono WAV.
(function () {
  const TARGET_RATE = 16000;

  function toMono(buffer) {
    if (buffer.numberOfChannels === 1) return buffer.getChannelData(0);
    const a = buffer.getChannelData(0), b = buffer.getChannelData(1);
    const out = new Float32Array(a.length);
    for (let i = 0; i < a.length; i++) out[i] = (a[i] + b[i]) / 2;
    return out;
  }

  // Box-filter downsampler: averages each output window, which also acts as a cheap anti-alias filter for speech.
  function downsample(samples, srcRate) {
    if (srcRate === TARGET_RATE) return samples;
    const ratio = srcRate / TARGET_RATE;
    const out = new Float32Array(Math.floor(samples.length / ratio));
    for (let i = 0; i < out.length; i++) {
      const start = Math.floor(i * ratio), end = Math.min(samples.length, Math.floor((i + 1) * ratio));
      let sum = 0;
      for (let j = start; j < end; j++) sum += samples[j];
      out[i] = sum / Math.max(1, end - start);
    }
    return out;
  }

  function encodeWav(samples, srcRate) {
    const pcm = downsample(samples, srcRate);
    const buf = new ArrayBuffer(44 + pcm.length * 2);
    const v = new DataView(buf);
    const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    str(0, "RIFF"); v.setUint32(4, 36 + pcm.length * 2, true); str(8, "WAVE");
    str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, TARGET_RATE, true); v.setUint32(28, TARGET_RATE * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    str(36, "data"); v.setUint32(40, pcm.length * 2, true);
    for (let i = 0; i < pcm.length; i++) {
      const s = Math.max(-1, Math.min(1, pcm[i]));
      v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return buf;
  }

  function toBase64(arrayBuffer) {
    const bytes = new Uint8Array(arrayBuffer);
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(bin);
  }

  // Plays an AudioBuffer and emits a chunk every `chunkSec` of *played* audio, so analysis tracks what the user hears.
  class FileCall {
    constructor(ctx, buffer, chunkSec, onChunk, onEnd) {
      Object.assign(this, { ctx, buffer, chunkSec, onChunk, onEnd });
      this.mono = toMono(buffer);
      this.rate = buffer.sampleRate;
      this.gain = ctx.createGain();
      this.gain.connect(ctx.destination);
      this.nextCut = chunkSec;
      this.stopped = false;
    }
    get duration() { return this.buffer.duration; }
    get elapsed() { return Math.min(this.duration, this.ctx.currentTime - this.startedAt); }
    start() {
      this.src = this.ctx.createBufferSource();
      this.src.buffer = this.buffer;
      this.src.connect(this.gain);
      this.src.onended = () => this.finish();
      this.startedAt = this.ctx.currentTime + 0.05;
      this.src.start(this.startedAt);
      this.timer = setInterval(() => this.tick(), 100);
    }
    tick() {
      while (!this.stopped && this.elapsed >= this.nextCut) {
        this.emit(this.nextCut - this.chunkSec, this.nextCut);
        this.nextCut += this.chunkSec;
      }
    }
    emit(t0, t1) {
      const a = Math.floor(t0 * this.rate), b = Math.min(this.mono.length, Math.floor(t1 * this.rate));
      if (b - a < this.rate * 0.8) return; // skip slivers under 0.8 s
      this.onChunk({ wav: encodeWav(this.mono.subarray(a, b), this.rate), t0, t1: b / this.rate });
    }
    finish() {
      if (this.stopped) return;
      this.stopped = true;
      clearInterval(this.timer);
      this.emit(this.nextCut - this.chunkSec, this.duration); // trailing piece
      this.onEnd("ended");
    }
    duck(level) { this.gain.gain.setTargetAtTime(level, this.ctx.currentTime, 0.15); }
    stop() {
      if (this.stopped) return;
      this.stopped = true;
      clearInterval(this.timer);
      try { this.src.stop(); } catch (_) { /* already stopped */ }
      this.onEnd("cut");
    }
  }

  // Taps the microphone (phone on speaker next to the laptop) and emits a chunk every `chunkSec`.
  class MicCall {
    constructor(ctx, stream, chunkSec, onChunk, onEnd) {
      Object.assign(this, { ctx, stream, chunkSec, onChunk, onEnd });
      this.rate = ctx.sampleRate;
      this.parts = [];
      this.count = 0;
      this.t0 = 0;
      this.startedAt = ctx.currentTime;
      this.duration = Infinity;
    }
    get elapsed() { return this.ctx.currentTime - this.startedAt; }
    start() {
      this.source = this.ctx.createMediaStreamSource(this.stream);
      this.proc = this.ctx.createScriptProcessor(4096, 1, 1);
      const sink = this.ctx.createGain();
      sink.gain.value = 0; // keep the graph alive without echoing the mic
      this.proc.onaudioprocess = (e) => {
        this.parts.push(new Float32Array(e.inputBuffer.getChannelData(0)));
        this.count += e.inputBuffer.length;
        if (this.count >= this.chunkSec * this.rate) this.flush();
      };
      this.source.connect(this.proc); this.proc.connect(sink); sink.connect(this.ctx.destination);
    }
    flush() {
      if (!this.count) return;
      const all = new Float32Array(this.count);
      let o = 0;
      for (const p of this.parts) { all.set(p, o); o += p.length; }
      const t1 = this.t0 + this.count / this.rate;
      this.onChunk({ wav: encodeWav(all, this.rate), t0: this.t0, t1 });
      this.t0 = t1; this.parts = []; this.count = 0;
    }
    duck() { /* nothing to duck: the call plays on the phone itself */ }
    stop() {
      if (this.stopped) return;
      this.stopped = true;
      this.proc.disconnect(); this.source.disconnect();
      this.stream.getTracks().forEach((t) => t.stop());
      this.flush();
      this.onEnd("cut");
    }
  }

  window.SajagAudio = { FileCall, MicCall, toBase64 };
})();
