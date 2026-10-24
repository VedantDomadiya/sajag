// Unit tests for web/core.js (pure UI logic). Run: node --test tests/js/*.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const sandbox = { window: {}, String, Math };
vm.runInNewContext(readFileSync(new URL("../../web/core.js", import.meta.url), "utf8"), sandbox);
const core = sandbox.window.SajagCore;

const meta = {
  headlines: { SCAM: { en: "Warning! This is a scam call." } },
  explain: { OTP_REQUEST: { en: "Never share an OTP." }, AUTHORITY: { en: "Real police never ask for money." } },
  scam_types: { FAKE_KYC: { en: "This is a fake KYC scam." } },
};

test("red flags are ordered by severity", () => {
  assert.deepEqual([...core.bySeverity(["URGENCY", "OTP_REQUEST", "AUTHORITY"])], ["OTP_REQUEST", "AUTHORITY", "URGENCY"]);
  assert.equal(core.topFlag(new Set(["SECRECY", "ARREST_THREAT"])), "ARREST_THREAT");
  assert.equal(core.topFlag([]), null);
});

test("context is trimmed to what the server reads", () => {
  assert.equal(core.trimContext("short"), "short");
  const long = "x".repeat(core.CONTEXT_CHARS + 100) + "END";
  const out = core.trimContext(long);
  assert.equal(out.length, core.CONTEXT_CHARS);
  assert.ok(out.endsWith("END"));
});

test("time formatting", () => {
  assert.equal(core.fmt(0), "0:00");
  assert.equal(core.fmt(75.4), "1:15");
});

test("transcript lines are split by speaker", () => {
  const lines = core.parseTranscript("Caller: OTP बताइए\n\nUser: क्यों?\nno label");
  assert.deepEqual(JSON.parse(JSON.stringify(lines)), [
    { who: "caller", text: "OTP बताइए" },
    { who: "user", text: "क्यों?" },
    { who: "speaker", text: "no label" },
  ]);
});

test("warning text is always hand-written: scam type first, then top flag, then headline", () => {
  assert.equal(core.warningText(meta, "en", ["OTP_REQUEST"], "FAKE_KYC"), "This is a fake KYC scam.");
  assert.equal(core.warningText(meta, "en", ["AUTHORITY", "OTP_REQUEST"], "NONE"), "Never share an OTP.");
  assert.equal(core.warningText(meta, "en", [], "NONE"), "Warning! This is a scam call.");
  assert.equal(core.warningText(meta, "en", ["OTP_REQUEST"], "UNKNOWN_TYPE"), "Never share an OTP.");
});
