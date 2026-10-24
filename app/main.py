"""Sajag web server: serves the UI and the chunk-analysis API.

The server is stateless. The browser keeps the call state (transcript so far, flags seen, last model score) and sends it
with every chunk, so this runs happily on Cloud Run with any number of instances.
"""

import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import logging
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analyzer, config, risk, speech
from . import redflags as rf

app = FastAPI(title="Sajag", version="1.0.0", docs_url="/api/docs", redoc_url=None)
log = logging.getLogger("sajag")

ALLOWED_MIME = {"audio/wav", "audio/x-wav", "audio/wave", "audio/webm", "audio/ogg", "audio/mpeg", "audio/mp4"}
# 16 kHz mono 16-bit WAV is 32 KB/s; this cap also bounds webm/ogg uploads.
MAX_AUDIO_BYTES = config.MAX_CHUNK_SECONDS * 32_000 + 4_096


class CallState(BaseModel):
    transcript: str = Field("", max_length=20_000)
    flags: list[str] = Field(default_factory=list, max_length=50)
    model_risk: int = Field(0, ge=0, le=100)


class ChunkRequest(BaseModel):
    audio_b64: str = Field(..., max_length=MAX_AUDIO_BYTES * 4 // 3 + 8)
    mime: str = "audio/wav"
    lang: str = Field("gu", pattern="^(gu|hi|en)$")
    t_start: float = Field(0, ge=0, le=36_000)
    t_end: float = Field(5, ge=0, le=36_000)
    state: CallState = Field(default_factory=CallState)


class SpeakRequest(BaseModel):
    """The server only ever speaks text it wrote itself: a fixed headline, plus either a warning it returned from
    /api/analyze (proved by `token`) or the hand-written explanation for one red flag."""

    lang: str = Field("gu", pattern="^(gu|hi|en)$")
    warning: str = Field("", max_length=600)
    token: str = Field("", max_length=128)
    flag: str | None = Field(None, max_length=32)


# Signed tokens for warnings. The signing key is derived from the API key, so every instance agrees without extra config.
_SIGNING_KEY = hashlib.sha256(b"sajag-speak-v1|" + config.GEMINI_API_KEY.encode()).digest()


def sign_warning(lang: str, text: str) -> str:
    return hmac.new(_SIGNING_KEY, f"{lang}|{text}".encode(), hashlib.sha256).hexdigest()


# Per-client rate limits, so the public endpoints can't be used as a free proxy to a paid key. In-memory, per instance:
# good enough to stop casual abuse; put Cloud Armor or API Gateway in front for anything bigger.
RATE_LIMITS = {"analyze": (40, 60), "speak": (6, 60)}  # (requests, per seconds)
MAX_TRACKED = 10_000
_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def client_key(request: Request) -> str:
    """Who to rate-limit. Behind a proxy, take the IP the *trusted* proxy appended to X-Forwarded-For, counting from the
    right (entries further left are client-supplied and spoofable). IPv6 clients are grouped by /64."""
    ip = request.client.host if request.client else "unknown"
    n = config.CLIENT_IP_FROM_RIGHT
    if n > 0:
        parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(parts) >= n:
            ip = parts[-n]
    try:
        addr = ipaddress.ip_address(ip)
        if addr.version == 6:
            return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    except ValueError:
        pass
    return ip


def _prune(now: float) -> None:
    """Drop only expired entries; never reset live counters."""
    for key in list(_hits):
        q = _hits[key]
        window = RATE_LIMITS[key[0]][1]
        while q and now - q[0] > window:
            q.popleft()
        if not q:
            del _hits[key]


def rate_limit(request: Request, bucket: str) -> None:
    limit, window = RATE_LIMITS[bucket]
    now = time.monotonic()
    key = (bucket, client_key(request))
    if key not in _hits and len(_hits) >= MAX_TRACKED:
        _prune(now)
        if len(_hits) >= MAX_TRACKED:  # still full of live clients: refuse newcomers rather than forget existing ones
            raise HTTPException(429, "Too many requests, slow down")
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many requests, slow down")
    q.append(now)


@app.get("/api/health")
def health():
    return {"ok": True, "model": config.MODEL, "tts_model": config.TTS_MODEL, "gemini_configured": bool(config.GEMINI_API_KEY)}


@app.get("/api/meta")
def meta():
    """Labels, explanations and headlines in all three languages, so the UI has one source of truth."""
    return {"labels": rf.LABELS, "explain": rf.EXPLAIN, "headlines": rf.HEADLINES, "thresholds": {"scam": risk.SCAM_AT, "caution": risk.CAUTION_AT}}


@app.get("/api/samples")
def samples():
    out = []
    for meta_file in sorted((config.SAMPLES_DIR / "scripts").glob("*.json")):
        info = json.loads(meta_file.read_text(encoding="utf-8"))
        wav = config.SAMPLES_DIR / f"{meta_file.stem}.wav"
        if wav.is_file():
            out.append({
                "id": meta_file.stem,
                "title": info["title"],
                "language": info["language"],
                "expected": info["expected"],
                "caller_id": info.get("caller_id", "Unknown number"),
                "url": f"/samples/{wav.name}",
            })
    return out


@app.post("/api/analyze")
async def analyze(req: ChunkRequest, request: Request):
    rate_limit(request, "analyze")
    if req.mime not in ALLOWED_MIME:
        raise HTTPException(415, "Unsupported audio type")
    try:
        audio = base64.b64decode(req.audio_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "audio_b64 is not valid base64")
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio chunk is empty or too long")
    if not config.GEMINI_API_KEY:
        raise HTTPException(503, "Gemini is not configured on the server (GEMINI_API_KEY missing)")

    try:
        verdict = await analyzer.analyze_chunk(
            audio, req.mime, req.lang, req.state.transcript, req.state.flags, req.t_start, req.t_end
        )
    except Exception:
        log.exception("Gemini analysis failed")
        raise HTTPException(502, "Analysis temporarily unavailable")

    # Second opinion: deterministic keyword rules over what Gemini heard (original script + English gloss).
    model_codes = {f["code"] for f in verdict["flags"]}
    rule_hits = [h for h in rf.match_rules(verdict["transcript"], verdict["english"]) if h["code"] not in model_codes]
    new_flags = [{**f, "source": "gemini"} for f in verdict["flags"]] + [{**h, "source": "rules"} for h in rule_hits]

    all_codes = set(req.state.flags) | {f["code"] for f in new_flags}
    fused = risk.fuse(verdict["scam_probability"], req.state.model_risk, all_codes)

    return {
        "transcript": verdict["transcript"],
        "english": verdict["english"],
        "flags": new_flags,
        "all_flags": sorted(all_codes),
        "scam_type": verdict["scam_type"],
        "warning": verdict["warning"],
        "warning_token": sign_warning(req.lang, verdict["warning"]) if verdict["warning"] else "",
        "reasoning": verdict["reasoning"],
        "latency_ms": verdict["latency_ms"],
        **fused,
    }


@app.post("/api/speak")
async def speak(req: SpeakRequest, request: Request):
    rate_limit(request, "speak")
    if not config.GEMINI_API_KEY:
        raise HTTPException(503, "Gemini is not configured")
    parts = [rf.HEADLINES["SCAM"][req.lang]]
    if req.warning and hmac.compare_digest(req.token, sign_warning(req.lang, req.warning)):
        parts.append(req.warning)
    elif req.flag in rf.EXPLAIN:
        parts.append(rf.EXPLAIN[req.flag][req.lang])
    elif req.warning or req.token:
        raise HTTPException(403, "Warning text was not issued by this server")
    try:
        wav = await speech.speak(" ".join(parts), req.lang)
    except Exception:
        log.exception("Gemini TTS failed")
        raise HTTPException(502, "Speech temporarily unavailable")
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
    return resp


app.mount("/samples", StaticFiles(directory=config.SAMPLES_DIR), name="samples")
app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(config.WEB_DIR / "index.html")
