"""Gemini text-to-speech for the spoken warning, plus small WAV helpers shared with the sample generator."""

import hashlib
import io
import struct
import wave

from google.genai import types

from . import config
from .analyzer import client

TTS_RATE = 24000  # Gemini TTS returns 16-bit mono PCM at 24 kHz

_cache: dict[str, bytes] = {}


def pcm_to_wav(pcm: bytes, rate: int = TTS_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def resample_pcm16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Linear-interpolation resampler for 16-bit mono PCM. Good enough for speech, no numpy needed."""
    if src_rate == dst_rate:
        return pcm
    n = len(pcm) // 2
    src = struct.unpack(f"<{n}h", pcm[: n * 2])
    out_n = int(n * dst_rate / src_rate)
    step = src_rate / dst_rate
    out = []
    for i in range(out_n):
        x = i * step
        j = int(x)
        frac = x - j
        a = src[j]
        b = src[j + 1] if j + 1 < n else a
        out.append(int(a + (b - a) * frac))
    return struct.pack(f"<{out_n}h", *out)


def _audio_bytes(resp: types.GenerateContentResponse) -> bytes:
    """Pull the PCM out of a TTS response, failing loudly (and safely) if Gemini returned no audio."""
    for candidate in resp.candidates or []:
        for part in (candidate.content.parts if candidate.content else None) or []:
            if part.inline_data and part.inline_data.data:
                return part.inline_data.data
    raise ValueError("Gemini TTS returned no audio")


async def speak(text: str, lang: str) -> bytes:
    """Return a WAV of `text` spoken calmly. Cached, because the same warning is often spoken more than once."""
    key = hashlib.sha256(f"{lang}|{text}".encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    style = "Say this slowly, calmly and clearly, like a caring grandchild warning their grandparent"
    resp = await client().aio.models.generate_content(
        model=config.TTS_MODEL,
        contents=f"{style}: {text}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=config.TTS_VOICE)
                )
            ),
        ),
    )
    wav = pcm_to_wav(_audio_bytes(resp))
    if len(_cache) > 64:
        _cache.clear()
    _cache[key] = wav
    return wav
