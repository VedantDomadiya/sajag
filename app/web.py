"""HTTP hardening and efficiency: security headers, a strict CSP, selective compression and cache policy."""

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

# Only our own scripts; Google Fonts for Gujarati/Devanagari glyphs; blob: for the spoken warning.
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com",
        "img-src 'self' data:",
        "media-src 'self' blob:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ]
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Cross-Origin-Opener-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}

# Swagger UI loads its own scripts from a CDN, so the interactive docs get the other headers but not the CSP.
_NO_CSP_PATHS = ("/api/docs", "/openapi.json")


def security_headers_for(path: str) -> dict[str, str]:
    headers = dict(SECURITY_HEADERS)
    if not path.startswith(_NO_CSP_PATHS):
        headers["Content-Security-Policy"] = CSP
    return headers


def cache_control_for(path: str) -> str | None:
    """Sample calls never change between deploys; UI assets revalidate cheaply via ETag; API answers aren't cached."""
    if path.startswith("/samples/"):
        return "public, max-age=86400"
    if path.startswith("/static/") or path == "/":
        return "no-cache"
    if path.startswith("/api/"):
        return "no-store"
    return None


class SelectiveGZip:
    """Gzip text (HTML, JS, CSS, JSON) but not audio, which doesn't compress and would only burn CPU."""

    SKIP = ("/samples/", "/api/speak")

    def __init__(self, app: ASGIApp, minimum_size: int = 1024) -> None:
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not scope["path"].startswith(self.SKIP):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)
