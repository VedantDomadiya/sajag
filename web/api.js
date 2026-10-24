// Thin wrappers over the Sajag HTTP API. All network access in the UI goes through here.
(function () {
  const { trimContext } = window.SajagCore;
  const JSON_HEADERS = { "Content-Type": "application/json" };

  async function getJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url}: ${res.status}`);
    return res.json();
  }

  /**
   * Send one chunk with the call state. Resolves to {status, data}; data is null unless status is 200.
   * @param {{wavB64: string, lang: string, t0: number, t1: number, transcript: string, flags: string[], modelRisk: number}} c
   */
  async function analyzeChunk(c) {
    const body = {
      audio_b64: c.wavB64,
      mime: "audio/wav",
      lang: c.lang,
      t_start: c.t0,
      t_end: c.t1,
      state: { transcript: trimContext(c.transcript), flags: c.flags, model_risk: c.modelRisk },
    };
    const res = await fetch("/api/analyze", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });
    return { status: res.status, data: res.ok ? await res.json() : null };
  }

  /** Spoken warning (Gemini TTS) for a red-flag code. Resolves to an audio Blob, or throws. */
  async function speech(lang, flag) {
    const res = await fetch("/api/speak", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ lang, flag }) });
    if (!res.ok) throw new Error(`speak: ${res.status}`);
    return res.blob();
  }

  window.SajagApi = {
    meta: () => getJSON("/api/meta"),
    samples: () => getJSON("/api/samples"),
    health: () => getJSON("/api/health"),
    analyzeChunk,
    speech,
  };
})();
