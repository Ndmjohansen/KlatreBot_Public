# Repository Guidelines

## Project Structure & Module Organization

KlatreBot V2 is a Poetry-managed Python 3.11 Discord bot. Runtime code lives in `klatrebot_v2/`, with the entry point at `klatrebot_v2/__main__.py`. Discord-facing features are split into `klatrebot_v2/cogs/`; database access is under `klatrebot_v2/db/`; OpenAI and prompt handling are under `klatrebot_v2/llm/`. Tests live in `tests/unit/` and `tests/integration/`. Deployment assets are `install.sh`, `klatrebot.service`, and `.github/workflows/`. `klatrebot_v1/` is archived reference code, not the deployed app.

## Build, Test, and Development Commands

- `poetry install --sync`: install dependencies exactly from `poetry.lock`.
- `poetry run python3 -m klatrebot_v2`: run the bot locally using `.env`.
- `poetry run pytest -v`: run the default test suite.
- `poetry run pytest tests/unit/test_chat.py::test_name -v`: run one focused test.
- `poetry run pytest -m integration`: run opt-in boot smoke tests that require real Discord credentials.
- `poetry check`: validate Poetry project metadata after dependency edits.

## Coding Style & Naming Conventions

Use idiomatic Python with 4-space indentation, type hints where they improve clarity, and small async functions for Discord and database flows. Keep module names lowercase with underscores, test files named `test_*.py`, and cog names aligned to their feature domain. User-facing bot strings are Danish; preserve Danish wording when editing existing behavior. Add database tables in `klatrebot_v2/db/migrations.py` with `CREATE TABLE IF NOT EXISTS`.

## Testing Guidelines

Unit tests should be fast and isolated in `tests/unit/`. Integration tests belong in `tests/integration/` and must be marked with `@pytest.mark.integration`. Prefer testing cogs, database helpers, rate limits, and time-window logic without network calls. Run `poetry run pytest -v` before opening a PR; run integration tests only when validating boot or environment-sensitive behavior.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commit-style subjects such as `feat(install): ...`, `chore(backup): ...`, and `refactor: ...`. Keep subjects imperative and scoped when useful. PRs should describe behavior changes, mention deployment or config impact, link relevant issues, and include test results. Include screenshots or Discord transcript snippets only when command output or user-facing messages change.

## Security & Configuration Tips

Never commit `.env`, database files, tokens, or real Discord/OpenAI keys. Local secrets come from `.env`; production uses `/etc/klatrebot/klatrebot.env`. When changing dependencies, update and commit `poetry.lock`. Pushes to `main` deploy to the Raspberry Pi, so treat `main` as production.
