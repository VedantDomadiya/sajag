"""Sajag web server: the UI and the chunk-analysis API.

The server is stateless. The browser keeps the call state (transcript so far, flags seen, last model score) and sends it
with every chunk, so this scales to zero and runs on any number of instances.

Module map: schemas.py (request/response models) · pipeline.py (rules + fusion) · analyzer.py (Gemini audio) ·
speech.py (Gemini TTS) · ratelimit.py (abuse and cost limits) · web.py (headers, CSP, compression, caching).
"""

import base64
import binascii
import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import analyzer, config, pipeline, risk, speech, web
from . import redflags as rf
from .ratelimit import Policy, RateLimited, RateLimiter, client_key
from .schemas import ALLOWED_MIME, MAX_AUDIO_BYTES, AnalyzeResponse, ChunkRequest, SpeakRequest

log = logging.getLogger("sajag")

app = FastAPI(
    title="Sajag",
    version="1.1.0",
    description="Real-time scam-call guardian: listens in 5-second chunks and warns in Gujarati, Hindi or English.",
    docs_url="/api/docs",
    redoc_url=None,
)
app.add_middleware(web.SelectiveGZip)

# A live call needs 12 analyses a minute (one per 5-second chunk).
POLICIES = {
    "analyze": Policy(per_client=40, window_s=60, fair_share=15, soft_global=600, hard_global=1200),
    "speak": Policy(per_client=6, window_s=60, fair_share=2, soft_global=60, hard_global=120),
}
limiter = RateLimiter(POLICIES)


def rate_limit(request: Request, bucket: str) -> None:
    client = client_key(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for", ""),
        config.CLIENT_IP_FROM_RIGHT,
    )
    try:
        limiter.check(bucket, client)
    except RateLimited:
        raise HTTPException(429, "Too many requests, slow down") from None


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "model": config.MODEL,
        "tts_model": config.TTS_MODEL,
        "gemini_configured": bool(config.GEMINI_API_KEY),
    }


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    """Labels, explanations and headlines in all three languages, so the UI has one source of truth."""
    return {
        "labels": rf.LABELS,
        "explain": rf.EXPLAIN,
        "headlines": rf.HEADLINES,
        "scam_types": rf.SCAM_TYPES,
        "thresholds": {"scam": risk.SCAM_AT, "caution": risk.CAUTION_AT},
    }


@app.get("/api/samples")
def samples() -> list[dict[str, str]]:
    out = []
    for meta_file in sorted((config.SAMPLES_DIR / "scripts").glob("*.json")):
        wav = config.SAMPLES_DIR / f"{meta_file.stem}.wav"
        if not wav.is_file():
            continue
        info = json.loads(meta_file.read_text(encoding="utf-8"))
        out.append(
            {
                "id": meta_file.stem,
                "title": info["title"],
                "language": info["language"],
                "expected": info["expected"],
                "caller_id": info.get("caller_id", "Unknown number"),
                "url": f"/samples/{wav.name}",
            }
        )
    return out


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(req: ChunkRequest, request: Request) -> dict[str, Any]:
    rate_limit(request, "analyze")
    if req.mime not in ALLOWED_MIME:
        raise HTTPException(415, "Unsupported audio type")
    try:
        audio = base64.b64decode(req.audio_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "audio_b64 is not valid base64") from None
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio chunk is empty or too long")
    if not config.GEMINI_API_KEY:
        raise HTTPException(503, "Gemini is not configured on the server (GEMINI_API_KEY missing)")

    prev_flags = sorted({f for f in req.state.flags if f in rf.CODES})  # client state is untrusted
    try:
        verdict = await analyzer.analyze_chunk(
            audio, req.mime, req.lang, req.state.transcript, prev_flags, req.t_start, req.t_end
        )
    except Exception:
        log.exception("Gemini analysis failed")
        raise HTTPException(502, "Analysis temporarily unavailable") from None

    assessment = pipeline.assess(verdict, prev_flags, req.state.model_risk)
    return {
        "transcript": verdict["transcript"],
        "english": verdict["english"],
        "scam_type": verdict["scam_type"],
        "latency_ms": verdict["latency_ms"],
        **assessment,
    }


@app.post("/api/speak")
async def speak(req: SpeakRequest, request: Request) -> Response:
    rate_limit(request, "speak")
    if not config.GEMINI_API_KEY:
        raise HTTPException(503, "Gemini is not configured")
    parts = [rf.HEADLINES["SCAM"][req.lang]]
    if req.flag is not None:
        if req.flag not in rf.EXPLAIN:
            raise HTTPException(422, "Unknown red-flag code")
        parts.append(rf.EXPLAIN[req.flag][req.lang])
    try:
        wav = await speech.speak(" ".join(parts), req.lang)
    except Exception:
        log.exception("Gemini TTS failed")
        raise HTTPException(502, "Speech temporarily unavailable") from None
    return Response(wav, media_type="audio/wav")


@app.middleware("http")
async def headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    resp = await call_next(request)
    path = request.url.path
    for name, value in web.security_headers_for(path).items():
        resp.headers.setdefault(name, value)
    cache = web.cache_control_for(path)
    if cache:
        resp.headers.setdefault("Cache-Control", cache)
    return resp


app.mount("/samples", StaticFiles(directory=config.SAMPLES_DIR), name="samples")
app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(config.WEB_DIR / "index.html")
