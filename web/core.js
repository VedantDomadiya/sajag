// Pure helpers shared by the UI. No DOM, no network: unit-tested in tests/js/core.test.mjs.
(function (root) {
  /** Server-side context window (app/config.py CONTEXT_CHARS): sending more would only cost bandwidth. */
  const CONTEXT_CHARS = 2500;

  /** How serious each red flag is when choosing what to say first. Mirrors the weights in app/redflags.py. */
  const SEVERITY = { OTP_REQUEST: 7, ARREST_THREAT: 6, MONEY_REQUEST: 5, REMOTE_ACCESS: 4, SECRECY: 3, AUTHORITY: 2, URGENCY: 1 };

  /** @param {Iterable<string>} codes @returns {string[]} most serious first */
  function bySeverity(codes) {
    return [...codes].sort((a, b) => (SEVERITY[b] || 0) - (SEVERITY[a] || 0));
  }

  /** @param {Iterable<string>} codes @returns {string|null} */
  function topFlag(codes) {
    return bySeverity(codes)[0] || null;
  }

  /** Keep only the tail of the transcript the server will actually read. @param {string} text */
  function trimContext(text) {
    return text.length > CONTEXT_CHARS ? text.slice(-CONTEXT_CHARS) : text;
  }

  /** 75.4 -> "1:15" @param {number} sec */
  function fmt(sec) {
    return `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;
  }

  /**
   * Split Gemini's transcript into speaker-labelled lines.
   * @param {string} transcript e.g. "Caller: ...\nUser: ..."
   * @returns {{who: "caller"|"user"|"speaker", text: string}[]}
   */
  function parseTranscript(transcript) {
    const out = [];
    for (const raw of transcript.split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      const m = line.match(/^(Caller|User|Speaker)\s*:\s*(.*)$/i);
      out.push(m ? { who: m[1].toLowerCase(), text: m[2] } : { who: "speaker", text: line });
    }
    return out;
  }

  /**
   * What the warning says: the curated explanation for the scam type if Gemini recognised one, otherwise for the
   * most serious red flag. All text comes from /api/meta (hand-written), never from the model.
   */
  function warningText(meta, lang, codes, scamType) {
    if (scamType && scamType !== "NONE" && meta.scam_types[scamType]) return meta.scam_types[scamType][lang];
    const top = topFlag(codes);
    return top ? meta.explain[top][lang] : meta.headlines.SCAM[lang];
  }

  root.SajagCore = { CONTEXT_CHARS, SEVERITY, bySeverity, topFlag, trimContext, fmt, parseTranscript, warningText };
})(typeof window !== "undefined" ? window : globalThis);
