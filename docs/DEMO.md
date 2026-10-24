# Demo runbook and pitch

A 3-minute live demo, with a checklist and a plan B.

## Before you present (5 minutes)

- [ ] `.env` has a working `GEMINI_API_KEY`; `curl localhost:8000/api/health` shows `"gemini_configured": true`.
- [ ] Run `uv run python scripts/evaluate.py` once. This warms up the model and gives you real numbers to quote.
- [ ] Laptop volume up, speakers (not headphones) so the room hears the call and the warning.
- [ ] Browser zoom 110–125% so the back row can read the transcript.
- [ ] Language set to **ગુજરાતી** or **हिंदी** depending on the room.
- [ ] Phone with a WhatsApp chat open, to show "Tell my family" landing.
- [ ] Play the genuine delivery call once (the audience doesn't need to see this, it just warms the browser audio).

## Script (3 minutes)

**0:00 · The hook (20 s)**
> "Imagine your grandmother picks up: 'Mumbai Cyber Crime. A parcel with drugs went out on your Aadhaar. You're under
> digital arrest. Don't tell anyone.' She is alone. That's the whole trick: the victim is alone on the call.
> Sajag means 'alert'. It's the second person on the call."

**0:20 · Play the digital-arrest call (60 s)**
Click **Digital arrest: fake Mumbai Cyber Crime officer**. Narrate over it, briefly:
> "Gemini is hearing this in 5-second pieces, Hindi straight from audio, no browser speech-to-text. Here's the
> transcript, here's the English. Watch the right side."

Point at the chips as they light: *claims to be police* → *threat of arrest* → *keep it secret*. When the screen turns red,
**stop talking** and let Sajag speak.

> "Look at 'Warned at': it fired while the call was still going, before the scammer finished asking for money."

Point at **Warned at 0:xx / 0:57** and at the reasons: "Police never arrest anyone over a video call." Tap
**Tell my family**.

**1:20 · Gujarati, OTP (30 s)**
Switch to **ગુજરાતી**, play **Fake KYC**.
> "Same idea, different scam, different language. It catches the OTP request and the CVV, and explains it in Gujarati."

**1:50 · Doesn't cry wolf (30 s)**
Play **Genuine: delivery person at the gate**.
> "This one also talks about a parcel and a payment, exactly the words a keyword filter would scream at. Sajag stays green.
> That's because Gemini understands the conversation, and our rules can only raise the alarm when the model agrees.
> We call it two keys."

Optional, if time: the genuine bank call that literally says "OTP".

**2:20 · How and what's next (40 s)**
> "Gemini 2.5 Flash does the listening, transcribing and judging in one call, with structured output. Gemini TTS speaks
> the warning. It's a stateless container for Cloud Run. Next: an Android app that sits on the real call, Gemini Live for
> streaming, Gemini Nano on-device for privacy, and alerts that reach a family member's phone."

Close: **"Cut the call. Call family. Call 1930."**

## Likely judge questions

| Question | Answer |
|---|---|
| Why not the Web Speech API? | It struggles with colloquial Gujarati, Hindi and code-mixing, and it only gives text. Gemini takes raw audio and returns transcript, translation and judgement in one call. |
| How fast is it? | Chunks are 5 s; Gemini's per-chunk latency is shown live ("Gemini latency") and reported by the evaluation script. A red flag reaches the screen one chunk plus that latency after it is spoken. |
| False positives? | Two keys: rules alone can never make a call red. Both genuine samples stay green, including a bank call that says "OTP". The red-flag explanations are hand-written, not generated. |
| Privacy? | Nothing is stored; the server is stateless. Audio goes to Gemini only for analysis. Roadmap: on-device first pass with Gemini Nano. |
| How does it hear a real call? | Today: phone on speaker next to the laptop ("Listen live"). Production: an Android app using call screening. |
| How would you measure it? | `scripts/evaluate.py`: accuracy, time to warning as a fraction of call length, per-chunk risk timeline. See EVALUATION.md. |

## Plan B

| Problem | Do this |
|---|---|
| Venue Wi-Fi is slow | Tether to a phone. Each chunk is only ~160 KB. |
| Gemini is rate-limited | Wait 30 s, replay. Keep `eval-results.json` open as evidence the pipeline ran end to end. |
| Browser blocks audio | Click anywhere on the page first (autoplay policy), then click the sample. |
| Mic permission blocked | Use a sample call; mic mode needs `localhost` or HTTPS. |
