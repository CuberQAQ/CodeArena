# Professional Test Engineer - Agent Memory

## Project: Code Arena

### Architecture
- Docker-based fullstack app: React (Vite) frontend + FastAPI backend + PostgreSQL
- Docker Compose split: docker-compose.yml (production) + docker-compose.dev.yml (development overlay)
- Nginx serves frontend static files and proxies /api/ to backend
- Backend ORM: SQLAlchemy 2.0 async with Alembic migrations

### Key File Locations
- `/home/cuberqaq/projects/code-arena/requirements.md` - master requirements document
- `/home/cuberqaq/projects/code-arena/task.md` - project task list (links to requirements.md)
- `/home/cuberqaq/projects/code-arena/backend/app/services/contest_service.py` - contest service with _auto_end_expired
- `/home/cuberqaq/projects/code-arena/backend/app/services/pp_service.py` - PP service with overkill multiplier
- `/home/cuberqaq/projects/code-arena/backend/app/services/achievement_service.py` - achievement event detection

### Known Issues
- Task 1.2: [docker-compose.dev.yml frontend port/healthcheck conflict](defects.md) - HIGH severity
- Task 1.3: user.py missing elo/pp Index in __table_attrs__ - MEDIUM severity
- Task 4.1: rate_limiter.py token math bug - MEDIUM severity
- Task 4.1: Timeout not retried - HIGH severity
- Task 9.1: api.ts 401 interceptor dead code - observation only
- Task 13.2: Dockerfile.backend exec-form CMD - HIGH severity
- Task 13.2: nginx.conf missing security headers - MEDIUM severity
- Pre-existing: integration test _TestPPRecord missing overkill_multiplier column (conftest.py not synced since Task 17.3)
- Task 22.3 obs: PvP PPService.record_pp uses post-settlement Elo for overkill, inconsistent with PvE
- OBS: contest_service.py missing AchievementService.check_overkill call (pre-existing)
- OBS: 2 pre-existing economy test failures (TestDailyReset, TestGetDailyStatus)

### Testing Patterns
- Docker available (v29.1.3), `docker compose config` for YAML validation
- Use `cp .env.example .env` before compose validation
- Test files use SQLite-compatible _Test models, patch production model references
- Integration test models in conftest.py must sync with production models - common false-failure source
- pytest-asyncio AUTO mode; fixtures yield async sessions with context-managed patches
- When testing Elo baseline: trace exact point where `user.elo` is mutated relative to overkill/achievement calls
- Frontend: `npm run build` = `tsc -b && vite build`; `npx tsc --noEmit` for TS check
- Frontend tsconfig.app.json includes `src` so ALL .tsx files (including tests) are type-checked by `tsc -b`
- Frontend test mocks: Element.closest() returns Element not HTMLElement; must cast for @testing-library `within()`
- Frontend test mocks: unused params in mock components must use underscore prefix to avoid TS6133

### Test Environment
- Running pytest from project root fails due to .env CORS_ORIGINS format (pydantic-settings expects JSON array)
- Workaround: `cd backend && CORS_ORIGINS='["http://localhost","http://localhost:80"]' python -m pytest tests/`
- Pre-existing economy test failures: test_economy.py TestDailyReset and TestGetDailyStatus (2 tests)

### Service Test Coverage
- challenge_service: 103 tests passing (includes TestOverkillAchievement: 4 tests)
- Full backend unit suite: 1098/1100 passing (2 pre-existing economy failures)
- Frontend test suite: 90 tests passing (28 page component tests + 62 other) as of Task 27.5

### Cross-cutting Observations
- contest_service.py does NOT call AchievementService.check_overkill (pre-existing gap)
- Frontend ChallengeDetail type missing opponent_elo_change field (pre-existing, no UI impact)
