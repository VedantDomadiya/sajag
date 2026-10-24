// Sajag UI controller: runs a call, sends each chunk to the API strictly in order, and turns verdicts into a live,
// elder-friendly warning. Pure helpers live in core.js, network calls in api.js, audio capture in audio.js.
(function () {
  const CHUNK_SEC = 5;
  const { FileCall, MicCall, toBase64 } = window.SajagAudio;
  const { bySeverity, topFlag, fmt, parseTranscript, warningText } = window.SajagCore;
  const api = window.SajagApi;
  const $ = (id) => document.getElementById(id);

  let lang = localGet("sajag.lang") || "gu";
  let meta = null;
  let ctx = null;
  let call = null;
  let s = freshState();
  let lastFocus = null;
  let speaking = null;

  /** Everything we know about the current call. Replaced wholesale when a new call starts. */
  function freshState() {
    return {
      title: "", transcript: "", flags: new Set(), evidence: {}, scamType: "NONE",
      modelRisk: 0, risk: 0, level: "SAFE",
      queue: [], busy: false, ended: null, halted: false, alerted: false, warnedAt: null,
      chunks: 0, silent: 0, latencies: [],
    };
  }

  function localGet(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }
  function localSet(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* private mode */ } }
  const t = (key) => (window.I18N[lang] && window.I18N[lang][key]) || window.I18N.en[key] || key;

  // ---------- language and text size ----------
  function applyLang() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll("[data-i18n-label]").forEach((el) => el.setAttribute("aria-label", t(el.dataset.i18nLabel)));
    document.querySelectorAll(".lang button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
    $("callerName").textContent = call ? s.title : t("noCall");
    renderFlags();
    renderLevel();
  }

  function applyTextSize(size) {
    document.documentElement.dataset.textSize = size;
    document.querySelectorAll(".size button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.size === size)));
    localSet("sajag.size", size);
  }

  // ---------- call sources ----------
  async function loadSamples() {
    const ul = $("samples");
    ul.textContent = "";
    for (const smp of await api.samples()) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sample";
      const title = el("span", "sample-title", smp.title);
      const lg = el("span", "badge b-lang", smp.language === "gu" ? "ગુજરાતી" : "हिंदी");
      const badge = el("span", "badge " + (smp.expected === "SCAM" ? "b-scam" : "b-safe"), smp.expected === "SCAM" ? "scam" : "genuine");
      btn.append(title, lg, badge);
      btn.addEventListener("click", () => playUrl(smp.url, smp.title));
      const li = document.createElement("li");
      li.append(btn);
      ul.append(li);
    }
  }

  async function audioCtx() {
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") await ctx.resume();
    return ctx;
  }

  async function playUrl(url, title) {
    const c = await audioCtx();
    const buf = await fetch(url).then((r) => r.arrayBuffer()).then((ab) => c.decodeAudioData(ab));
    startCall(new FileCall(c, buf, CHUNK_SEC, onChunk, onEnd), title);
  }

  async function playFile(file) {
    const c = await audioCtx();
    const buf = await c.decodeAudioData(await file.arrayBuffer());
    startCall(new FileCall(c, buf, CHUNK_SEC, onChunk, onEnd), file.name);
  }

  async function startMic() {
    if (call instanceof MicCall && !call.stopped) { call.stop(); return; }
    const c = await audioCtx();
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: true } });
    } catch (err) {
      showBanner("caution", String(err.message || err));
      return;
    }
    startCall(new MicCall(c, stream, CHUNK_SEC, onChunk, onEnd), t("micLabel"));
    $("micBtn").classList.add("rec");
    $("micBtn").setAttribute("aria-pressed", "true");
  }

  // ---------- call lifecycle ----------
  function startCall(newCall, title) {
    if (call && !call.stopped) call.stop();
    s = freshState();
    s.title = title;
    call = newCall;
    $("callerName").textContent = title;
    $("transcript").textContent = "";
    addSystemLine(t("listening"));
    $("markers").textContent = "";
    $("hangBtn").disabled = false;
    $("phone").className = "phone live";
    $("why").hidden = true;
    hideBanner();
    renderFlags(); renderLevel(); renderStats();
    call.start();
    tickClock();
  }

  function tickClock() {
    if (!call) return;
    const elapsed = call.elapsed || 0;
    $("callClock").textContent = fmt(elapsed);
    $("progressBar").style.width = isFinite(call.duration) ? `${(100 * elapsed) / call.duration}%` : "0%";
    if (!call.stopped) requestAnimationFrame(tickClock);
  }

  function onChunk(chunk) {
    if (s.halted) return;
    if (chunk.silent) { s.silent += 1; renderStats(); return; } // nothing to hear: don't spend a Gemini call
    s.queue.push(chunk);
    pump();
  }

  function onEnd(reason) {
    s.ended = reason;
    $("hangBtn").disabled = true;
    $("micBtn").classList.remove("rec");
    $("micBtn").setAttribute("aria-pressed", "false");
    $("phone").classList.remove("live");
    if (reason === "cut") { hideAlert(); showBanner("safe", t("callCut")); }
    maybeFinal();
  }

  function maybeFinal() {
    if (!s.ended || s.busy || s.queue.length || s.ended === "cut" || s.halted) return;
    const scam = s.level === "SCAM";
    showBanner(scam ? "scam" : "safe", t(scam ? "callEndedScam" : "callEndedSafe"));
  }

  // Strictly in order: each request carries the transcript of everything before it.
  async function pump() {
    if (s.busy) return;
    s.busy = true;
    const mine = s;
    while (mine.queue.length && !mine.halted) {
      try {
        await analyze(mine.queue.shift(), mine);
      } catch (err) {
        console.warn(err);
      }
    }
    mine.busy = false;
    if (mine === s) maybeFinal();
  }

  async function analyze(chunk, mine) {
    const { status, data: d } = await api.analyzeChunk({
      wavB64: toBase64(chunk.wav), lang, t0: chunk.t0, t1: chunk.t1,
      transcript: mine.transcript, flags: [...mine.flags], modelRisk: mine.modelRisk,
    });
    if (mine !== s) return; // a new call started meanwhile
    if (status === 503) { mine.halted = true; showBanner("caution", t("errNoKey")); return; }
    if (status === 429) { showBanner("caution", t("errBusy")); return; }
    if (!d) { showBanner("caution", t("errNet")); return; }

    mine.chunks += 1;
    mine.latencies.push(d.latency_ms);
    mine.modelRisk = d.model_risk;
    mine.risk = d.risk;
    mine.level = d.level;
    if (d.scam_type && d.scam_type !== "NONE") mine.scamType = d.scam_type;
    if (d.transcript) mine.transcript += (mine.transcript ? "\n" : "") + d.transcript;
    for (const f of d.flags) {
      mine.flags.add(f.code);
      (mine.evidence[f.code] = mine.evidence[f.code] || []).push({ text: f.evidence, source: f.source, at: chunk.t1 });
    }

    addChunk(d, chunk);
    addMarker(chunk.t1, d.level);
    renderFlags(); renderLevel(); renderStats();
    if (mine.flags.size) {
      $("why").hidden = false;
      $("whyText").textContent = warningText(meta, lang, mine.flags, mine.scamType);
    }

    if (d.level === "SCAM" && !mine.alerted && !mine.ended) raiseAlert(chunk.t1);
    else if (d.level === "CAUTION" && !mine.alerted) showBanner("caution", meta.headlines.CAUTION[lang]);
  }

  // ---------- transcript ----------
  function el(tag, className, text) {
    const node = document.createElement(tag);
    node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function addSystemLine(text) {
    $("transcript").append(el("p", "sys", text));
  }

  function addChunk(d, chunk) {
    const box = $("transcript");
    box.querySelectorAll(".sys").forEach((n) => n.remove());
    if (!d.transcript) return;
    const group = el("div", "chunk" + (d.flags.length ? " hot" : ""));
    for (const line of parseTranscript(d.transcript)) {
      const bubble = el("p", "bubble " + line.who, line.text);
      bubble.setAttribute("aria-label", `${t(line.who === "user" ? "you" : "caller")}: ${line.text}`);
      group.append(bubble);
    }
    if (d.english) group.append(el("p", "gloss", d.english));
    group.append(el("span", "ts", `${fmt(chunk.t0)}–${fmt(chunk.t1)} · ${d.risk}`));
    box.append(group);
    box.scrollTop = box.scrollHeight;
  }

  function addMarker(at, level) {
    if (!call || !isFinite(call.duration)) return;
    const mark = el("i", "mk " + level.toLowerCase());
    mark.style.left = `${Math.min(100, (100 * at) / call.duration)}%`;
    $("markers").append(mark);
  }

  // ---------- guardian panel ----------
  function renderFlags() {
    if (!meta) return;
    const ul = $("flags");
    ul.textContent = "";
    for (const code of Object.keys(meta.labels)) {
      const on = s.flags.has(code);
      const li = el("li", "flag" + (on ? " on" : ""));
      li.append(el("span", "flag-name", meta.labels[code][lang]));
      const ev = on && s.evidence[code] && s.evidence[code][0];
      if (ev) {
        const q = el("q", "", ev.text);
        q.title = `${ev.source} · ${fmt(ev.at)}`;
        li.append(q);
      }
      li.setAttribute("aria-label", `${meta.labels[code][lang]}: ${t(on ? "heard" : "notHeard")}`);
      ul.append(li);
    }
  }

  function renderLevel() {
    const lvl = s.level.toLowerCase();
    const pill = $("levelPill");
    pill.className = "pill " + lvl;
    pill.textContent = t(lvl);
    $("riskNum").textContent = s.risk;
    const meter = $("riskMeter");
    meter.setAttribute("aria-valuenow", String(s.risk));
    meter.setAttribute("aria-valuetext", `${s.risk} / 100, ${t(lvl)}`);
    const fill = $("riskFill");
    fill.style.width = `${s.risk}%`;
    fill.className = lvl;
    $("phone").dataset.level = lvl;
  }

  function renderStats() {
    $("statChunks").textContent = s.silent ? `${s.chunks} (+${s.silent} ${t("silent")})` : String(s.chunks);
    const l = s.latencies;
    $("statLatency").textContent = l.length ? `${(l.reduce((a, b) => a + b, 0) / l.length / 1000).toFixed(1)} s` : "–";
    $("statWarned").textContent = s.warnedAt == null ? "–"
      : isFinite(call && call.duration) ? `${fmt(s.warnedAt)} / ${fmt(call.duration)}` : fmt(s.warnedAt);
  }

  // ---------- the warning ----------
  function raiseAlert(at) {
    s.alerted = true;
    s.warnedAt = at;
    renderStats();
    call.duck(0.12);
    $("alertHead").textContent = meta.headlines.SCAM[lang];
    $("alertSpoken").textContent = warningText(meta, lang, s.flags, s.scamType);
    const ul = $("alertReasons");
    ul.textContent = "";
    for (const code of bySeverity(s.flags)) {
      const li = document.createElement("li");
      li.append(el("strong", "", meta.labels[code][lang]), el("span", "", meta.explain[code][lang]));
      ul.append(li);
    }
    $("alertFamily").href = "https://wa.me/?text=" + encodeURIComponent(t("familyMsg"));
    lastFocus = document.activeElement;
    $("alert").hidden = false;
    $("alertHang").focus();
    if (navigator.vibrate) navigator.vibrate([300, 150, 300]);
    showBanner("scam", meta.headlines.SCAM[lang]);
    speak();
  }

  function hideAlert() {
    if ($("alert").hidden) return;
    $("alert").hidden = true;
    if (call && !call.stopped) call.duck(0.6);
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  // Keep keyboard focus inside the warning while it is open.
  function trapFocus(e) {
    if (e.key !== "Tab" || $("alert").hidden) return;
    const items = [...$("alert").querySelectorAll("a[href], button:not([disabled])")];
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { last.focus(); e.preventDefault(); }
    else if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault(); }
  }

  // Only hand-written text is spoken: the headline plus the curated explanation for the most serious red flag.
  async function speak() {
    const top = topFlag(s.flags);
    if (speaking) speaking.pause();
    try {
      speaking = new Audio(URL.createObjectURL(await api.speech(lang, top)));
      await speaking.play();
    } catch (_) {
      // Fallback: the browser's own voice. Only for *speaking* the warning, never for listening to the call.
      if (!("speechSynthesis" in window)) return;
      const u = new SpeechSynthesisUtterance(meta.headlines.SCAM[lang] + (top ? " " + meta.explain[top][lang] : ""));
      u.lang = { gu: "gu-IN", hi: "hi-IN", en: "en-IN" }[lang];
      u.rate = 0.9;
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
    }
  }

  // ---------- banner ----------
  function showBanner(kind, text) {
    const b = $("banner");
    b.className = "banner " + kind;
    b.textContent = text;
    b.hidden = false;
  }
  function hideBanner() { $("banner").hidden = true; }

  // ---------- wiring ----------
  document.querySelectorAll(".lang button").forEach((b) => b.addEventListener("click", () => {
    lang = b.dataset.lang;
    localSet("sajag.lang", lang);
    applyLang();
  }));
  document.querySelectorAll(".size button").forEach((b) => b.addEventListener("click", () => applyTextSize(b.dataset.size)));
  $("micBtn").addEventListener("click", startMic);
  $("fileIn").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) playFile(f); e.target.value = ""; });
  $("hangBtn").addEventListener("click", () => call && call.stop());
  $("alertHang").addEventListener("click", () => call && call.stop());
  $("alertClose").addEventListener("click", hideAlert);
  $("alertReplay").addEventListener("click", () => speak());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hideAlert();
    trapFocus(e);
  });

  (async function init() {
    applyTextSize(localGet("sajag.size") || "m");
    meta = await api.meta();
    applyLang();
    await loadSamples();
    const h = await api.health().catch(() => null);
    if (h && !h.gemini_configured) showBanner("caution", t("errNoKey"));
  })();
})();
