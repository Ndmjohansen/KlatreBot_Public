"""Load versioned Markdown prompts independently of the working directory."""
from functools import lru_cache
import hashlib
from pathlib import Path
import re
from string import Template

from klatrebot_v2.settings import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = PROJECT_ROOT / "prompts"
REQUIRED_PROMPTS = (
    "soul", "routing", "evidence_rules", "source_evidence", "assessment", "draft",
    "verification", "general", "chat_input", "summary", "memory_cli",
    "compiler_segment", "compiler_rollup", "compiler_daily", "memory_fields", "tool_feedback",
)


@lru_cache(maxsize=None)
def load_prompt(name: str, section: str | None = None) -> str:
    if not re.fullmatch(r"[a-z_]+", name):
        raise ValueError(f"Invalid prompt name: {name}")
    path = PROMPTS_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8").strip()
    if section is not None:
        parts = re.split(r"^## ([a-z_.]+)\s*$", text, flags=re.MULTILINE)
        names = parts[1::2]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate prompt section: {path}")
        sections = dict(zip(names, parts[2::2]))
        if section not in sections:
            raise ValueError(f"Missing prompt section {section}: {path}")
        text = sections[section].strip()
    if not text:
        raise ValueError(f"Empty prompt: {path} ({section})")
    return text


def render_prompt(name: str, **values) -> str:
    return Template(load_prompt(name)).substitute(values)


def compose_prompts(*names: str) -> str:
    return "\n\n".join(load_prompt(name) for name in names)


def prompt_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in sorted(PROMPTS_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def validate_prompts() -> None:
    for name in REQUIRED_PROMPTS:
        if not Template(load_prompt(name)).is_valid():
            raise ValueError(f"Invalid prompt template: {PROMPTS_DIR / (name + '.md')}")
    load_soul()


@lru_cache(maxsize=1)
def load_soul() -> str:
    path = Path(get_settings().soul_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Empty personality prompt: {path}")
    return text
