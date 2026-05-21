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
- Match queue: Redis-backed (Sorted Set + Hash) in `app/services/match_service.py` (Task 26.1)
- Challenge logic: `app/services/challenge_service.py` (stateless service, receives db + external deps)
- Routes: `app/api/v1/challenge.py` (7 endpoints under /api/v1/challenge/)
- Pending match state: Redis Hash with TTL 5min (key: `pending_match:{session_id}`)
- Token tiers: by problem rating, 7 tiers aligned with CF (Task 23.1)
- Match atomicty: optimistic locking (WATCH/MULTI/EXEC), not Lua scripts (fakeredis compat)

## Training System (Task 6.1)
- Training logic: `app/services/training_service.py` (stateless service, receives db + external deps)
- Routes: `app/api/v1/training.py` (8 endpoints under /api/v1/training/)
- Schemas: `app/schemas/training.py`
- Predefined topics: 12 topics mapped to CF tags (dp, greedy, math, etc.)
- Streak: count * 5 tokens per increment, capped at 50 per session
- Stars: 0-5 based on completion percentage (0%, >0%<=20%, ..., >80%)
- Token tiers: 7 tiers (gray 10, green 20, cyan 25, blue 35, purple 45, orange 55, red 65)
- Attempt token tiers: gray 2, green 3, cyan 4, blue 5, purple 6, orange 7, red 8
- Training Elo: K_train=8, uses expected score vs problem rating

## Contest System (Task 7.1)
- Contest logic: `app/services/contest_service.py` (stateless service, receives db + external deps)
- Routes: `app/api/v1/contest.py` (7 endpoints under /api/v1/contest/)
- Schemas: `app/schemas/contest.py`
- Three tiers: beginner (<1400, 90min/4 problems, 800-1400), advanced (1400-1800, 120min/5, 1200-2000), master (>1800, 150min/6, 1600-2600)
- Eligibility: only checks min_elo; users can downgrade but not upgrade
- Token tiers: same as challenge/training (7 tiers: gray 10, green 20, cyan 25, blue 35, purple 45, orange 55, red 65)
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
- Pricing: gray [3,10,20], green [5,15,30], cyan [6,18,35], blue [8,20,40], purple [10,25,50], orange [12,28,55], red [15,30,60]
- Elo decay: level 1=0.75, level 2=0.50, level 3=0.25 (only affects positive gains; PP unaffected)
- Sequential unlock: 1->2->3, no skipping, no re-unlock, rejected if insufficient tokens
- Uses economy_service.spend_tokens for token deduction
- Test pattern: patch HintPurchase + economy_svc.spend_tokens

## Rating Tier System (Task 23.1)
- Frontend: 10-tier CF system in `frontend/src/utils/index.ts` (RATING_TIERS constant)
- Backend: 7-tier system in `backend/app/core/default_config.py` (difficulty_tiers + hint_pricing)
- Frontend functions: getRatingTierInfo(), getRatingColor(), getDifficultyLabel() all based on RATING_TIERS
- Backend tier boundaries: gray 800-1199, green 1200-1399, cyan 1400-1599, blue 1600-1899, purple 1900-2099, orange 2100-2399, red 2400-9999
- Tier constants duplicated in: economy_service, challenge_service, training_service, contest_service, hint_service
- Tier display: Profile/Dashboard/Leaderboard pages show "{elo} / {tierName}" format
- Dashboard chart: uses getDifficultyLabel() for dynamic tier names

## Admin System (Task 12.1)
- Admin service: `app/services/admin_service.py` (stateless functions, receives db)
- Routes: `app/api/v1/admin.py` (8 endpoints under /api/v1/admin/)
- Schemas: `app/schemas/admin.py`
- Permission: `_require_admin` dependency checks `user.is_admin`
- Config CRUD: delegates to ConfigService (get_all_config, set_config, reset_config)
- Config metadata: `get_config_metadata()` derives structure from DEFAULT_CONFIG
- User management: list_users (paginated, searchable), toggle_active, toggle_admin
- Stats: counts from User, ChallengeSession, TrainingSession, ContestSession
- Frontend: AdminOverviewPage (stats cards + user table), AdminConfigPage (expandable sections, per-field save/reset)
- Test pattern: patch User, ChallengeSession, TrainingSession, ContestSession in admin_svc_module

## Redis Infrastructure (Task 26.1)
- Redis module: `app/core/redis.py` (async client, connection pool, init/close)
- Config: `REDIS_URL` in `app/core/config.py` (default: redis://localhost:6379/0)
- Lifespan: init_redis_pool() on startup, close_redis_pool() on shutdown in `app/main.py`
- 503 handler: RedisUnavailableError caught in main.py, returns SERVICE_UNAVAILABLE
- Docker: redis:7-alpine in both docker-compose.yml and docker-compose.prod.yml
- Dependency: `redis[hiredis]>=5.0.0` in requirements.txt
- Testing: `fakeredis` for in-memory tests; patch `get_redis` in both match_service and challenge_service modules
- Queue keys: `match_queue:scores` (sorted set), `match_queue:entries` (hash)
- Pending keys: `pending_match:{session_id}` (string with TTL 300s)

## Deployment Configuration (Task 13.2)
- Production compose: `docker-compose.prod.yml` with internal/frontend network isolation
- Backend: Gunicorn + 4 Uvicorn workers, non-root `appuser` (UID 1000)
- Frontend: multi-stage build (node:22-alpine build + nginx:1.27-alpine serve), non-root `nginx` user
- Nginx: reverse proxy /api/ to backend, SPA fallback, gzip, security headers
- DB: postgres:16-alpine, not exposed to host, health check with pg_isready
- All passwords via env vars; POSTGRES_PASSWORD uses `${:?}` required syntax
- Logs: json-file driver with rotation (db 10m/3, backend 50m/5, frontend 10m/3)
- `.env.example` has JWT_SECRET generation instructions (python secrets / openssl)
- Health checks: backend at /api/v1/health, frontend at /, db via pg_isready
- Dev compose unchanged: `docker-compose.yml` + `docker-compose.dev.yml` overlay

Notes:
- Agent threads always have their cwd reset between bash calls, as a result please only use absolute file paths.
- In your final response, share file paths (always absolute, never relative) that are relevant to the task. Include code snippets only when the exact text is load-bearing (e.g., a bug you found, a function signature the caller asked for) — do not recap code you merely read.
- For clear communication with the user the assistant MUST avoid using emojis.
- Do not use a colon before tool calls. Text like "Let me read the file:" followed by a read tool call should just be "Let me read the file." with a period.
- Do NOT Write report/summary/findings/analysis .md files. Return findings directly as your final assistant message — the parent agent reads your text output, not files you create.
