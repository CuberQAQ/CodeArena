# Feature Engineer Memory

## Project: Code Arena
- **Stack**: FastAPI + SQLAlchemy 2.0 + Alembic (async with asyncpg) / React frontend
- **Backend dir**: `backend/`
- **DB**: PostgreSQL with async (asyncpg), config at `backend/app/core/config.py`
- **Linting**: ruff, configured in `backend/pyproject.toml` (line-length=120, target py311)
- **Testing**: pytest with pytest-asyncio (asyncio_mode=auto)

## Key Files
- [project-structure.md](project-structure.md) - Directory layout and key file locations
- [conventions.md](conventions.md) - Coding conventions and patterns
- [testing-patterns.md](testing-patterns.md) - Testing patterns for async SQLite

## Testing Gotchas
- PostgreSQL-specific types (JSONB, UUID with server_default=func.uuid_generate_v4) don't work with SQLite
- For async DB tests: create lightweight test model classes on a separate DeclarativeBase, patch service methods that use real ORM models
- See [testing-patterns.md](testing-patterns.md) for the full pattern

Notes:
- Agent threads always have their cwd reset between bash calls, as a result please only use absolute file paths.
- In your final response, share file paths (always absolute, never relative) that are relevant to the task. Include code snippets only when the exact text is load-bearing (e.g., a bug you found, a function signature the caller asked for) — do not recap code you merely read.
- For clear communication with the user the assistant MUST avoid using emojis.
- Do not use a colon before tool calls. Text like "Let me read the file:" followed by a read tool call should just be "Let me read the file." with a period.
- Do NOT Write report/summary/findings/analysis .md files. Return findings directly as your final assistant message — the parent agent reads your text output, not files you create.
