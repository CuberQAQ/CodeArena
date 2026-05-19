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
- When patching models in tests, must patch ALL models the service uses via `patch.object(service_module, "ModelName", TestModel)` -- User, ChallengeSession, TokenTransaction etc.
- Production model queries (db.get, select) will try to SELECT all production columns even if test DB only has a subset
- See [testing-patterns.md](testing-patterns.md) for the full pattern

## Challenge System (Task 5.1)
- Match queue: in-memory dict + asyncio.Lock in `app/services/match_service.py`
- Challenge logic: `app/services/challenge_service.py` (stateless service, receives db + external deps)
- Routes: `app/api/v1/challenge.py` (7 endpoints under /api/v1/challenge/)
- Pending match state: module-level dict in challenge_service (not persisted)
- Token tiers: by problem rating, 5 tiers from 5 to 50 tokens

## Training System (Task 6.1)
- Training logic: `app/services/training_service.py` (stateless service, receives db + external deps)
- Routes: `app/api/v1/training.py` (8 endpoints under /api/v1/training/)
- Schemas: `app/schemas/training.py`
- Predefined topics: 12 topics mapped to CF tags (dp, greedy, math, etc.)
- Streak: count * 5 tokens per increment, capped at 50 per session
- Stars: 0-5 based on completion percentage (0%, >0%<=20%, ..., >80%)
- Token tiers: same as challenge system (gray 10, green 20, blue 30, purple 40, yellow/red 50)
- Attempt token tiers: gray 2, green 3, blue 4, purple 5, yellow/red 6
- Training Elo: K_train=8, uses expected score vs problem rating

## Contest System (Task 7.1)
- Contest logic: `app/services/contest_service.py` (stateless service, receives db + external deps)
- Routes: `app/api/v1/contest.py` (7 endpoints under /api/v1/contest/)
- Schemas: `app/schemas/contest.py`
- Three tiers: beginner (<1400, 90min/4 problems, 800-1400), advanced (1400-1800, 120min/5, 1200-2000), master (>1800, 150min/6, 1600-2600)
- Eligibility: only checks min_elo; users can downgrade but not upgrade
- Token tiers: same as challenge/training (gray 10, green 20, blue 30, purple 40, yellow/red 50)
- Quit penalty: 0 submissions=no change, 1-2=-5~-10, 3+=M-Elo formula
- M-Elo: uses EloService.calculate_contest_elo via process_contest_result
- Timing: _ensure_utc helper handles naive datetimes from SQLite
- Test pattern: must patch ContestSession, ContestProblemRecord, TokenTransaction, EloHistory in contest_svc_module; also patch PPService.record_pp and EloService.record_elo_history

## Hint System (Task 8.2)
- Hint logic: `app/services/hint_service.py` (stateless HintService, receives db + user + params)
- Content gen: `app/services/hint_content_service.py` (tag-based hint templates per level)
- Routes: `app/api/v1/hints.py` (4 endpoints under /api/v1/hints/)
- Schemas: `app/schemas/hint.py`
- Model: `app/models/hint_purchase.py` (already existed in DB schema)
- Pricing: gray [3,10,20], green [5,15,30], blue [8,20,40], purple [10,25,50], yellow/red [15,30,60]
- Elo decay: level 1=0.75, level 2=0.50, level 3=0.25 (only affects positive gains; PP unaffected)
- Sequential unlock: 1->2->3, no skipping, no re-unlock, rejected if insufficient tokens
- Uses economy_service.spend_tokens for token deduction
- Test pattern: patch HintPurchase + economy_svc.spend_tokens

Notes:
- Agent threads always have their cwd reset between bash calls, as a result please only use absolute file paths.
- In your final response, share file paths (always absolute, never relative) that are relevant to the task. Include code snippets only when the exact text is load-bearing (e.g., a bug you found, a function signature the caller asked for) — do not recap code you merely read.
- For clear communication with the user the assistant MUST avoid using emojis.
- Do not use a colon before tool calls. Text like "Let me read the file:" followed by a read tool call should just be "Let me read the file." with a period.
- Do NOT Write report/summary/findings/analysis .md files. Return findings directly as your final assistant message — the parent agent reads your text output, not files you create.
