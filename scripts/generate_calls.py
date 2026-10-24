"""Turn the call scripts in samples/scripts/*.json into 16 kHz mono .wav files in samples/.

Engines:
  gemini  Gemini multi-speaker TTS (two distinct voices, natural Gujarati and Hindi). Needs GEMINI_API_KEY.
  say     macOS built-in Hindi voice (Lekha), offline. Gujarati lines are read through the Hindi voice by mapping
          Gujarati letters onto Devanagari (the two Unicode blocks line up almost one to one). The caller's voice is
          pitched down so the two sides of the call sound different.

Usage:
  uv run python scripts/generate_calls.py                 # gemini if a key is set, else say
  uv run python scripts/generate_calls.py --engine say
  uv run python scripts/generate_calls.py --only 02_fake_kyc_gu
"""

import argparse
import asyncio
import io
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.speech import TTS_RATE, pcm_to_wav, resample_pcm16  # noqa: E402

OUT_RATE = 16_000
GAP_MS = 450
LEAD_MS = 600


def silence(ms: int, rate: int = OUT_RATE) -> bytes:
    return b"\x00\x00" * int(rate * ms / 1000)


def gu_to_deva(text: str) -> str:
    """Map Gujarati script (U+0A80..U+0AFF) onto Devanagari (U+0900..U+097F) so a Hindi voice can read it aloud."""
    return "".join(chr(ord(ch) - 0x180) if 0x0A80 <= ord(ch) <= 0x0AFF else ch for ch in text)


def read_wav_pcm(data: bytes) -> tuple[bytes, int]:
    with wave.open(io.BytesIO(data)) as w:
        assert w.getsampwidth() == 2 and w.getnchannels() == 1, "expected 16-bit mono"
        return w.readframes(w.getnframes()), w.getframerate()


# --- macOS `say` engine -------------------------------------------------------------------------------------------

def say_line(text: str, caller: bool) -> bytes:
    """Render one line with Lekha. The caller is spoken faster, then slowed and pitched down by ~16%."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "line.wav"
        rate = "205" if caller else "165"
        subprocess.run(
            ["say", "-v", "Lekha", "-r", rate, "-o", str(out), "--file-format=WAVE", "--data-format=LEI16@22050", text],
            check=True,
        )
        pcm, src_rate = read_wav_pcm(out.read_bytes())
    if caller:
        src_rate = int(src_rate * 0.84)  # reinterpreting at a lower rate lowers the pitch
    return resample_pcm16(pcm, src_rate, OUT_RATE)


def render_say(script: dict) -> bytes:
    parts = [silence(LEAD_MS)]
    for line in script["lines"]:
        text = gu_to_deva(line["text"]) if script["language"] == "gu" else line["text"]
        parts += [say_line(text, line["speaker"] == "Caller"), silence(GAP_MS)]
    return b"".join(parts)


# --- Gemini engine ------------------------------------------------------------------------------------------------

async def render_gemini(script: dict) -> bytes:
    from google.genai import types

    from app.analyzer import client

    speakers = script["speakers"]
    lang = {"gu": "Gujarati", "hi": "Hindi"}.get(script["language"], "Hindi")
    direction = "\n".join(f"- {name} is {s['style']}." for name, s in speakers.items())
    dialogue = "\n".join(f"{line['speaker']}: {line['text']}" for line in script["lines"])
    prompt = (
        f"Perform this phone call in natural, colloquial {lang} with realistic Indian accents.\n{direction}\n"
        f"Leave a short natural pause between turns.\n\n{dialogue}"
    )
    resp = await client().aio.models.generate_content(
        model=config.TTS_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                    speaker_voice_configs=[
                        types.SpeakerVoiceConfig(
                            speaker=name,
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=s["gemini_voice"])
                            ),
                        )
                        for name, s in speakers.items()
                    ]
                )
            ),
        ),
    )
    pcm = resp.candidates[0].content.parts[0].inline_data.data
    return silence(LEAD_MS) + resample_pcm16(pcm, TTS_RATE, OUT_RATE)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["gemini", "say"], default="gemini" if config.GEMINI_API_KEY else "say")
    ap.add_argument("--only", help="generate a single script by id, e.g. 01_digital_arrest_hi")
    args = ap.parse_args()

    scripts = sorted((config.SAMPLES_DIR / "scripts").glob("*.json"))
    if args.only:
        scripts = [p for p in scripts if p.stem == args.only]
    total = 0
    for path in scripts:
        script = json.loads(path.read_text(encoding="utf-8"))
        pcm = asyncio.run(render_gemini(script)) if args.engine == "gemini" else render_say(script)
        wav = pcm_to_wav(pcm, OUT_RATE)
        (config.SAMPLES_DIR / f"{path.stem}.wav").write_bytes(wav)
        total += len(wav)
        print(f"{path.stem}.wav  {len(pcm) / 2 / OUT_RATE:5.1f}s  {len(wav) / 1e6:.2f} MB  [{args.engine}]")
    print(f"total {total / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
