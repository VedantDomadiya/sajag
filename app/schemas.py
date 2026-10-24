"""Request and response models for the HTTP API. Every field is bounded, because every field is attacker-controlled."""

from typing import Literal

from pydantic import BaseModel, Field

from . import config

Lang = Literal["gu", "hi", "en"]
Level = Literal["SAFE", "CAUTION", "SCAM"]
Source = Literal["gemini", "rules"]

# 16 kHz mono 16-bit WAV is 32 KB/s; this cap also bounds webm/ogg uploads.
MAX_AUDIO_BYTES = config.MAX_CHUNK_SECONDS * 32_000 + 4_096
ALLOWED_MIME = frozenset(
    {"audio/wav", "audio/x-wav", "audio/wave", "audio/webm", "audio/ogg", "audio/mpeg", "audio/mp4"}
)


class CallState(BaseModel):
    """What the browser remembers about the call so far. Untrusted: flags are filtered, lengths are capped."""

    transcript: str = Field("", max_length=20_000)
    flags: list[str] = Field(default_factory=list, max_length=50)
    model_risk: int = Field(0, ge=0, le=100)


class ChunkRequest(BaseModel):
    audio_b64: str = Field(..., max_length=MAX_AUDIO_BYTES * 4 // 3 + 8)
    mime: str = "audio/wav"
    lang: Lang = "gu"
    t_start: float = Field(0, ge=0, le=36_000)
    t_end: float = Field(5, ge=0, le=36_000)
    state: CallState = Field(default_factory=CallState)


class SpeakRequest(BaseModel):
    """Sajag only speaks hand-written text: the fixed headline plus the curated explanation for one red-flag code.
    Model output is never spoken, so a caller can't get Sajag to read out a number or a link."""

    lang: Lang = "gu"
    flag: str | None = Field(None, max_length=32)


class FlagHit(BaseModel):
    code: str
    evidence: str
    source: Source


class AnalyzeResponse(BaseModel):
    transcript: str
    english: str
    flags: list[FlagHit]
    all_flags: list[str]
    scam_type: str
    latency_ms: int
    risk: int
    model_risk: int
    rule_risk: int
    combo: bool
    level: Level
