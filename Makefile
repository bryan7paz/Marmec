.PHONY: install test lint run docker clean help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies + Playwright
	pip install -r requirements.txt
	playwright install chromium
	@if not exist config\secrets.env copy config\secrets.env.example config\secrets.env

test:  ## Run all tests
	python -m pytest tests/ -v --tb=short

test-cov:  ## Run tests with coverage
	python -m pytest tests/ -v --tb=short --cov=. --cov-report=term-missing

lint:  ## Lint with ruff
	ruff check . --select E,F,W --ignore E501
	ruff format --check .

format:  ## Auto-format code
	ruff format .

run:  ## Start dashboard (port 8000)
	python -m uvicorn api.main:app --port 8000 --reload

crawl:  ## Analyze a URL (URL=<url> [FROM=AAAA-MM-DD TO=AAAA-MM-DD])
	python run_pipeline.py $(URL) $(FROM) $(TO)

process:  ## Process queue only
	python process_queue.py

docker-up:  ## Start with Docker
	docker compose up -d

docker-down:  ## Stop Docker
	docker compose down

docker-logs:  ## View Docker logs
	docker compose logs -f

clean:  ## Clean generated files
	if exist .pytest_cache rmdir /s /q .pytest_cache
	if exist __pycache__ rmdir /s /q __pycache__
	if exist htmlcov rmdir /s /q htmlcov
	if exist data rmdir /s /q data
	del /q *.pyc 2>nul
