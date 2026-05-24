# Professional Test Engineer - Agent Memory

## Project: Code Arena

### Architecture
- Docker-based fullstack app: React (Vite) frontend + FastAPI backend + PostgreSQL
- Docker Compose split: docker-compose.yml (production) + docker-compose.dev.yml (development overlay)
- Backend ORM: SQLAlchemy 2.0 async with Alembic migrations

### Key File Locations
- `/home/cuberqaq/projects/code-arena/requirements.md` - master requirements document
- `/home/cuberqaq/projects/code-arena/task.md` - project task list
- Backend services: `backend/app/services/` (challenge, pve_challenge, training, contest, etc.)
- Frontend pages: `frontend/src/pages/`

### Testing Patterns
- Docker available, `docker compose config` for YAML validation
- Use `cp .env.example .env` before compose validation
- Test files use SQLite-compatible _Test models, patch production model references
- Integration test models in conftest.py must sync with production models - common false-failure source
- pytest-asyncio AUTO mode; fixtures yield async sessions with context-managed patches
- Frontend: `npm run build` = `tsc -b && vite build`; `npx tsc --noEmit` for TS check
- Frontend tsconfig.app.json includes `src` so ALL .tsx files (including tests) are type-checked by `tsc -b`
- Frontend test mocks: Element.closest() returns Element not HTMLElement; must cast for @testing-library `within()`
- Frontend test mocks: unused params in mock components must use underscore prefix to avoid TS6133

### Test Environment
- Running pytest from project root fails due to .env CORS_ORIGINS format (pydantic-settings expects JSON array)
- Workaround: `cd backend && CORS_ORIGINS='["http://localhost","http://localhost:80"]' python -m pytest tests/`

### Test Infrastructure (Updated 2026-05-24)
- Backend unit suite: ~1100 tests, 80% coverage threshold (`cd backend && pytest --tb=short -q`)
- Frontend vitest: ~1026 tests in 72 files, coverage thresholds: lines 90%, functions 87%, branches 82%, statements 88%
- Frontend e2e (Playwright chromium): 69 tests, many currently failing due to UI/code drift — needs baseline fix
- Frontend integration (Playwright integration): 6 spec files, requires Docker Compose running
- Pre-commit hooks: ruff lint+format, eslint, tsc --noEmit, detect-secrets

### Cross-cutting Observations
- contest_service.py does NOT call AchievementService.check_overkill (pre-existing gap)
- Frontend ChallengeDetail type missing opponent_elo_change field (pre-existing, no UI impact)
