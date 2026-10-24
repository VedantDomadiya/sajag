.PHONY: install run test test-py test-js lint format eval samples docker

install:      ## Install Python dependencies (uses uv)
	uv sync

run:          ## Start the app on http://localhost:8000
	uv run uvicorn app.main:app --reload

test: lint test-py test-js  ## Everything CI runs

test-py:      ## Python tests with coverage
	uv run pytest --cov --cov-report=term-missing

test-js:      ## Browser audio code tests (Node 20+)
	node --test tests/js/*.test.mjs

lint:         ## Ruff lint + format check
	uv run ruff check app scripts tests
	uv run ruff format --check app scripts tests

format:       ## Auto-format
	uv run ruff format app scripts tests
	uv run ruff check --fix app scripts tests

eval:         ## Replay the sample calls through Gemini (needs GEMINI_API_KEY)
	uv run python scripts/evaluate.py

samples:      ## Regenerate the sample .wav calls
	uv run python scripts/generate_calls.py

docker:       ## Build and run the container on :8080
	docker build -t sajag . && docker run --rm -p 8080:8080 --env-file .env sajag
