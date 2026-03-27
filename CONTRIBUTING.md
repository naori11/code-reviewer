# Contributing

## Local setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .
pip install pytest ruff mypy pre-commit
```

## Run checks locally

```bash
pytest tests -q
ruff check .
ruff format --check .
mypy src reviewer.py tests
```

## Pre-commit workflow

Install hooks once:

```bash
pre-commit install
```

Run hooks on all files:

```bash
pre-commit run --all-files
```

## Pull request expectations

- Keep changes scoped to the issue/plan.
- Ensure lint, type checks, and tests pass locally before opening a PR.
- For webhook-related changes, include tests for signature handling and end-to-end flow where relevant.
