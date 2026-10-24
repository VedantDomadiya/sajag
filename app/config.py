"""Runtime configuration, read from the environment (and a local .env file in development)."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so local dev needs no extra dependency. Real env vars always win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("SAJAG_MODEL", "gemini-3.8-flash")
TTS_MODEL = os.environ.get("SAJAG_TTS_MODEL", "gemini-2.5-flash-preview-tts")
TTS_VOICE = os.environ.get("SAJAG_TTS_VOICE", "Sulafat")

# Rate limiting behind a proxy: which X-Forwarded-For entry, counted from the right, is the real client IP.
# 0 = use the socket peer (local dev). Cloud Run appends the client IP as the right-most entry, so use 1 there;
# with an external HTTPS load balancer in front of Cloud Run it is the second from the right, so use 2.
CLIENT_IP_FROM_RIGHT = int(os.environ.get("SAJAG_CLIENT_IP_FROM_RIGHT", "0"))

# Each audio chunk is ~5 s; we never send more than this many seconds in one request.
MAX_CHUNK_SECONDS = 15
# How much of the running transcript we send back to the model as context.
CONTEXT_CHARS = 2500

SAMPLES_DIR = ROOT / "samples"
WEB_DIR = ROOT / "web"
