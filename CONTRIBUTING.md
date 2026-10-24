# Contributing

Thanks for helping protect people from scam calls.

## Setup

```bash
uv sync                 # Python 3.11–3.13
cp .env.example .env    # add GEMINI_API_KEY to run the app or the evaluation
make run                # http://localhost:8000
```

## Before you open a pull request

```bash
make test               # ruff lint + format check, pytest with coverage (≥ 90%), node:test for web/audio.js
```

CI runs the same checks plus a Docker build and smoke test.

## Common changes

- **New red flag:** add the code, weight, labels, explanation (en/hi/gu) and keyword rules in `app/redflags.py`, add it
  to the prompt in `app/analyzer.py`, then add a test in `tests/test_redflags.py`. The first test checks every flag
  has all three languages.
- **New sample call:** add a JSON script to `samples/scripts/` (see existing ones), run `make samples`, and check the
  rules test expectations. Keep names, numbers and organisations fictional.
- **New language:** add strings to `web/i18n.js`, `LABELS`/`EXPLAIN`/`HEADLINES` in `app/redflags.py`, and the
  language pattern in `app/main.py`.

## Style

Ruff enforces formatting and lint (line length 120). Keep advice text in `redflags.py` short, true and written for an
elderly reader. Never let model output be spoken or shown as advice.
