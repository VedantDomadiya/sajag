# Sajag on Cloud Run: a small, non-root, stateless container.
FROM python:3.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 SAJAG_CLIENT_IP_FROM_RIGHT=1
WORKDIR /srv

COPY pyproject.toml ./
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" "google-genai>=1.20"

COPY app ./app
COPY web ./web
COPY samples ./samples

RUN useradd --create-home --uid 10001 sajag
USER sajag

EXPOSE 8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
