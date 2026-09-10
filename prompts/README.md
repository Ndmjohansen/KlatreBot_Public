# Runtime prompts

All model-facing prose lives here as UTF-8 Markdown. Python owns schemas,
validation, deadlines, data serialization and tool execution. Prompt text owns
task instructions, tone, field descriptions and model-facing error guidance.

- `soul.md`: shared personality and response principles.
- `routing.md`, `general.md`: intent routing and general answers.
- `source_evidence.md`, `assessment.md`, `draft.md`, `verification.md`: historical
  stages, composed with `evidence_rules.md`.
- `chat_input.md`, `summary.md`, `memory_cli.md`: request templates.
- `compiler_segment.md`, `compiler_daily.md`, `compiler_rollup.md`: background compilation.
- `memory_fields.md`, `tool_feedback.md`: named `## section` descriptions and guidance.

Templates use Python `string.Template`: `${name}` inserts a supplied value once;
use `$$` for a literal dollar sign in template text. Runtime data is never expanded
as another template. Section identifiers are lowercase letters, underscores and
dots. Missing files, missing sections and empty prompts fail loudly.

Paths resolve from the project, not the working directory. Prompts are cached for
the process lifetime; restart the bot and relevant workers after edits. `SOUL_PATH`
still permits a custom personality file; its default is `./prompts/soul.md`.

Keep rules domain-independent and tied to an actual task or schema contract.
Remove redundant wording rather than appending exceptions for individual failures.
Put counterexamples and regressions in tests and evaluation fixtures, not prompts.
Review advice, historical, mixed and ambiguous cases when changing routing.
Evaluation fingerprints include these files so prose-only changes are traceable.
