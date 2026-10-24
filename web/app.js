// Sajag UI: runs a call, ships each chunk to /api/analyze in order, and turns verdicts into a live, elder-friendly warning.
(function () {
  const CHUNK_SEC = 5;
  const { FileCall, MicCall, toBase64 } = window.SajagAudio;
  const $ = (id) => document.getElementById(id);

  let lang = localGet("sajag.lang") || "gu";
  let meta = null;
  let ctx = null;
  let call = null;
  let s = freshState();

  function freshState() {
    return { transcript: "", flags: new Set(), evidence: {}, modelRisk: 0, risk: 0, level: "SAFE",
             alerted: false, chunks: 0, latencies: [], queue: [], busy: false, ended: null, halted: false,
             warnedAt: null, title: "" };
  }

  function localGet(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }
  function localSet(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* private mode */ } }
  const t = (key) => (window.I18N[lang] && window.I18N[lang][key]) || window.I18N.en[key] || key;
  const fmt = (sec) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;

  // ---------- language ----------
  function applyLang() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll(".lang button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
    if (!call) $("callerName").textContent = t("noCall");
    else $("callerName").textContent = s.title;
    renderFlags();
    renderLevel();
  }

  // ---------- samples ----------
  async function loadSamples() {
    const list = await fetch("/api/samples").then((r) => r.json());
    const ul = $("samples");
    ul.textContent = "";
    for (const smp of list) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sample";
      const badge = document.createElement("span");
      badge.className = "badge " + (smp.expected === "SCAM" ? "b-scam" : "b-safe");
      badge.textContent = smp.expected === "SCAM" ? "scam" : "genuine";
      const lg = document.createElement("span");
      lg.className = "badge b-lang";
      lg.textContent = smp.language === "gu" ? "ગુજરાતી" : "हिंदी";
      const title = document.createElement("span");
      title.className = "sample-title";
      title.textContent = smp.title;
      btn.append(title, lg, badge);
      btn.addEventListener("click", () => playUrl(smp.url, smp.title));
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
    if (call && call.constructor === MicCall && !call.stopped) { call.stop(); return; }
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
    const el = call.elapsed || 0;
    $("callClock").textContent = fmt(el);
    $("progressBar").style.width = isFinite(call.duration) ? `${(100 * el) / call.duration}%` : "0%";
    if (!call.stopped) requestAnimationFrame(tickClock);
  }

  function onChunk(chunk) {
    if (s.halted) return;
    s.queue.push(chunk);
    pump();
  }

  function onEnd(reason) {
    s.ended = reason;
    $("hangBtn").disabled = true;
    $("micBtn").classList.remove("rec");
    $("phone").classList.remove("live");
    if (reason === "cut") { hideAlert(); showBanner("safe", t("callCut")); }
    maybeFinal();
  }

  function maybeFinal() {
    if (!s.ended || s.busy || s.queue.length || s.ended === "cut" || s.halted) return;
    showBanner(s.level === "SCAM" ? "scam" : "safe", s.level === "SCAM" ? t("callEndedScam") : t("callEndedSafe"));
  }

  // Chunks are analysed strictly in order, so each request carries the transcript of everything before it.
  async function pump() {
    if (s.busy) return;
    s.busy = true;
    const mine = s;
    while (mine.queue.length && !mine.halted) {
      const chunk = mine.queue.shift();
      try {
        await analyze(chunk, mine);
      } catch (err) {
        console.warn(err);
      }
    }
    mine.busy = false;
    if (mine === s) maybeFinal();
  }

  async function analyze(chunk, mine) {
    const body = {
      audio_b64: toBase64(chunk.wav), mime: "audio/wav", lang,
      t_start: chunk.t0, t_end: chunk.t1,
      state: { transcript: mine.transcript, flags: [...mine.flags], model_risk: mine.modelRisk },
    };
    const res = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (mine !== s) return; // a new call started meanwhile
    if (res.status === 503) { mine.halted = true; showBanner("caution", t("errNoKey")); return; }
    if (!res.ok) { showBanner("caution", t("errNet")); return; }
    const d = await res.json();
    if (mine !== s) return;

    mine.chunks += 1;
    mine.latencies.push(d.latency_ms);
    mine.modelRisk = d.model_risk;
    mine.risk = d.risk;
    mine.level = d.level;
    if (d.transcript) mine.transcript += (mine.transcript ? "\n" : "") + d.transcript;
    for (const f of d.flags) {
      mine.flags.add(f.code);
      (mine.evidence[f.code] = mine.evidence[f.code] || []).push({ text: f.evidence, source: f.source, at: chunk.t1 });
    }

    addChunk(d, chunk);
    addMarker(chunk.t1, d.level);
    renderFlags(); renderLevel(); renderStats();
    if (d.reasoning) { $("why").hidden = false; $("whyText").textContent = d.reasoning; }

    if (d.level === "SCAM" && !mine.alerted && !mine.ended) raiseAlert(chunk.t1, d);
    else if (d.level === "CAUTION" && !mine.alerted) showBanner("caution", meta.headlines.CAUTION[lang]);
  }

  // ---------- transcript ----------
  function addSystemLine(text) {
    const p = document.createElement("p");
    p.className = "sys";
    p.textContent = text;
    $("transcript").append(p);
  }

  function addChunk(d, chunk) {
    const box = $("transcript");
    box.querySelectorAll(".sys").forEach((n) => n.remove());
    if (!d.transcript) return;
    const group = document.createElement("div");
    group.className = "chunk" + (d.flags.length ? " hot" : "");
    for (const raw of d.transcript.split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      const m = line.match(/^(Caller|User|Speaker)\s*:\s*(.*)$/i);
      const who = m ? m[1].toLowerCase() : "speaker";
      const b = document.createElement("p");
      b.className = "bubble " + who;
      b.textContent = m ? m[2] : line;
      group.append(b);
    }
    if (d.english) {
      const g = document.createElement("p");
      g.className = "gloss";
      g.textContent = d.english;
      group.append(g);
    }
    const ts = document.createElement("span");
    ts.className = "ts";
    ts.textContent = `${fmt(chunk.t0)}–${fmt(chunk.t1)} · ${d.risk}`;
    group.append(ts);
    box.append(group);
    box.scrollTop = box.scrollHeight;
  }

  function addMarker(at, level) {
    if (!call || !isFinite(call.duration)) return;
    const i = document.createElement("i");
    i.className = "mk " + level.toLowerCase();
    i.style.left = `${Math.min(100, (100 * at) / call.duration)}%`;
    $("markers").append(i);
  }

  // ---------- guardian panel ----------
  function renderFlags() {
    if (!meta) return;
    const ul = $("flags");
    ul.textContent = "";
    for (const code of Object.keys(meta.labels)) {
      const li = document.createElement("li");
      const on = s.flags.has(code);
      li.className = "flag" + (on ? " on" : "");
      const name = document.createElement("span");
      name.className = "flag-name";
      name.textContent = meta.labels[code][lang];
      li.append(name);
      if (on) {
        const ev = s.evidence[code] && s.evidence[code][0];
        if (ev) {
          const q = document.createElement("q");
          q.textContent = ev.text;
          q.title = `${ev.source} · ${fmt(ev.at)}`;
          li.append(q);
        }
      }
      ul.append(li);
    }
  }

  function renderLevel() {
    const lvl = s.level.toLowerCase();
    const pill = $("levelPill");
    pill.className = "pill " + lvl;
    pill.textContent = t(lvl === "caution" ? "caution" : lvl);
    $("riskNum").textContent = s.risk;
    const fill = $("riskFill");
    fill.style.width = `${s.risk}%`;
    fill.className = lvl;
    $("phone").dataset.level = lvl;
  }

  function renderStats() {
    $("statChunks").textContent = s.chunks;
    const l = s.latencies;
    $("statLatency").textContent = l.length ? `${(l.reduce((a, b) => a + b, 0) / l.length / 1000).toFixed(1)} s` : "–";
    $("statWarned").textContent = s.warnedAt == null ? "–"
      : isFinite(call && call.duration) ? `${fmt(s.warnedAt)} / ${fmt(call.duration)}` : fmt(s.warnedAt);
  }

  // ---------- the warning ----------
  function topFlag() { return [...s.flags].sort((a, b) => weight(b) - weight(a))[0] || null; }
  function spokenText() {
    const top = topFlag();
    return top ? meta.explain[top][lang] : meta.headlines.SCAM[lang];
  }
  function weight(code) { return { OTP_REQUEST: 7, ARREST_THREAT: 6, MONEY_REQUEST: 5, REMOTE_ACCESS: 4, SECRECY: 3, AUTHORITY: 2, URGENCY: 1 }[code] || 0; }

  function raiseAlert(at) {
    s.alerted = true;
    s.warnedAt = at;
    renderStats();
    call.duck(0.12);
    $("alertHead").textContent = meta.headlines.SCAM[lang];
    $("alertSpoken").textContent = spokenText();
    const ul = $("alertReasons");
    ul.textContent = "";
    for (const code of [...s.flags].sort((a, b) => weight(b) - weight(a))) {
      const li = document.createElement("li");
      const b = document.createElement("strong");
      b.textContent = meta.labels[code][lang];
      const p = document.createElement("span");
      p.textContent = meta.explain[code][lang];
      li.append(b, p);
      ul.append(li);
    }
    $("alertFamily").href = "https://wa.me/?text=" + encodeURIComponent(t("familyMsg"));
    $("alert").hidden = false;
    $("alertHang").focus();
    if (navigator.vibrate) navigator.vibrate([300, 150, 300]);
    showBanner("scam", meta.headlines.SCAM[lang]);
    speak();
  }

  function hideAlert() {
    $("alert").hidden = true;
    if (call && !call.stopped) call.duck(0.6);
  }

  let speaking = null;
  // Only hand-written text is spoken: the headline plus the curated explanation for the most serious red flag.
  async function speak() {
    const top = topFlag();
    const text = meta.headlines.SCAM[lang] + (top ? " " + meta.explain[top][lang] : "");
    if (speaking) speaking.pause();
    const body = { lang, flag: top };
    try {
      const res = await fetch("/api/speak", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error(String(res.status));
      const url = URL.createObjectURL(await res.blob());
      speaking = new Audio(url);
      await speaking.play();
    } catch (_) {
      // Fallback: the browser's own voice. Only used for *speaking* the warning, never for listening to the call.
      if ("speechSynthesis" in window) {
        const u = new SpeechSynthesisUtterance(text);
        u.lang = { gu: "gu-IN", hi: "hi-IN", en: "en-IN" }[lang];
        u.rate = 0.9;
        speechSynthesis.cancel();
        speechSynthesis.speak(u);
      }
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
    lang = b.dataset.lang; localSet("sajag.lang", lang); applyLang();
  }));
  $("micBtn").addEventListener("click", startMic);
  $("fileIn").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) playFile(f); e.target.value = ""; });
  $("hangBtn").addEventListener("click", () => call && call.stop());
  $("alertHang").addEventListener("click", () => call && call.stop());
  $("alertClose").addEventListener("click", hideAlert);
  $("alertReplay").addEventListener("click", () => speak());
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("alert").hidden) hideAlert(); });

  (async function init() {
    meta = await fetch("/api/meta").then((r) => r.json());
    applyLang();
    await loadSamples();
    const h = await fetch("/api/health").then((r) => r.json()).catch(() => null);
    if (h && !h.gemini_configured) showBanner("caution", t("errNoKey"));
  })();
})();
