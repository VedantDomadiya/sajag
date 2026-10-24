# Evaluation

## What we measure

For a scam guardian, "accuracy" alone is the wrong goal. A guardian that warns after the money has moved is useless,
and one that warns on every courier call gets uninstalled. So we measure three things per call:

| Metric | Definition | Target |
|---|---|---|
| **Correct verdict** | Peak level is `SCAM` for scam calls, and below `SCAM` for genuine calls. | 100% on the samples |
| **Time to warning** | Seconds into the call when the level first reaches `SCAM`, shown against the call length. | Before the call ends, ideally before the "money/OTP" step |
| **False alarms** | Genuine calls that reach `SCAM` at any chunk. | 0 |

Plus **Gemini latency** per chunk, which must stay under the 5-second chunk length for the queue to keep up.

## Method

`scripts/evaluate.py` replays each `.wav` in `samples/` through exactly the pipeline the browser uses:

1. Cut the call into 5-second chunks (the trailing piece is kept if it is at least 0.8 s).
2. Analyse chunks **in order**, each with the transcript and flags of everything before it.
3. Run the keyword rules on Gemini's transcript and English gloss.
4. Fuse with `risk.fuse()` and record risk, level and flags after every chunk.

```bash
uv run python scripts/evaluate.py            # warnings in Gujarati
uv run python scripts/evaluate.py --lang hi  # or Hindi
```

It prints a Markdown table (paste it below) and writes `eval-results.json` with the per-chunk timeline and the full
transcript for every call.

## Results

> Run `scripts/evaluate.py` and paste its table here. Note the model and date, because results vary by model version.

| Call | Expected | Sajag | Warned at | Red flags | Avg latency |
|---|---|---|---|---|---|
| _pending first run_ | | | | | |

## Unit tests (no API key)

`uv run pytest -q` covers the deterministic parts:

- Every flag has a weight, label and explanation in all three languages.
- The keyword rules find the expected flags in each scripted scam, and **nothing** in the genuine delivery call.
- The genuine bank call trips the `OTP` keyword but still fuses to `SAFE` (the two-key guarantee).
- Gemini alone can raise `SCAM`; rules alone cannot; the combo floor needs the model to agree; risk is sticky.
- A rule combo without the model's agreement still reaches `CAUTION` (prompt-injection backstop).
- The API fuses model and rule flags, carries client state, and rejects bad base64, wrong MIME types, unknown
  languages, oversized chunks, and requests without a configured key.
- `/api/speak` speaks curated text only; displayed model warnings with digits, links or addresses are dropped;
  upstream errors are not leaked; rate limits return 429.

## Threats to validity

- **Five scripted calls** demonstrate the flow, not field accuracy. Real calls are noisier, faster and more varied.
- **Synthetic voices.** TTS-generated calls are cleaner than a real phone line. Test with recordings of real (consented)
  calls and of people reading scam scripts over an actual phone before trusting the numbers.
- **Model drift.** Results depend on the Gemini model version. Pin `SAJAG_MODEL` when comparing runs.

Next steps for a proper benchmark: 50+ calls across the three scam types and common genuine calls (delivery, bank, family,
doctor, utility), recorded over real phone lines in Gujarati, Hindi and Hinglish, with time-to-warning plotted against the
moment of the first extraction request.
