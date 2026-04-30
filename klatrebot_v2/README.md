# KlatreBot V2

Lean Phase 1 rewrite. Spec: [`../docs/superpowers/specs/2026-04-30-klatrebot-v2-design.md`](../docs/superpowers/specs/2026-04-30-klatrebot-v2-design.md)

## Run

```
cd klatrebot_v2
cp .env.example .env  # fill in keys
poetry install
poetry run python3 -m klatrebot_v2
```

## Test

```
poetry run pytest                # unit tests
poetry run pytest -m integration # smoke boot (requires real DISCORD_KEY)
```
