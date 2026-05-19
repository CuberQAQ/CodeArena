# Professional Test Engineer - Agent Memory

## Project: Code Arena

### Architecture
- Docker-based fullstack app: React (Vite) frontend + FastAPI backend + PostgreSQL
- Docker Compose split: docker-compose.yml (production) + docker-compose.dev.yml (development overlay)
- Nginx serves frontend static files and proxies /api/ to backend
- Backend ORM: SQLAlchemy 2.0 async with Alembic migrations

### Key File Locations
- `/home/cuberqaq/projects/code-arena/task.md` - master requirements document
- `/home/cuberqaq/projects/code-arena/docker-compose.yml` - production compose
- `/home/cuberqaq/projects/code-arena/docker-compose.dev.yml` - dev overlay
- `/home/cuberqaq/projects/code-arena/backend/app/models/` - 12 ORM models + base.py + __init__.py
- `/home/cuberqaq/projects/code-arena/backend/app/core/database.py` - async engine/session/get_db
- `/home/cuberqaq/projects/code-arena/backend/alembic.ini` - Alembic config
- `/home/cuberqaq/projects/code-arena/backend/migrations/env.py` - async migration runner
- `/home/cuberqaq/projects/code-arena/backend/migrations/versions/` - migration scripts

### Known Issues
- Task 1.2: [docker-compose.dev.yml frontend port/healthcheck conflict](defects.md) - HIGH severity
- Task 1.3: user.py missing elo/pp Index in __table_args__ - MEDIUM severity, model layer inconsistent with migration layer
- Task 4.1: rate_limiter.py token math bug - tokens can go negative after sleep+refill+decrement sequence in concurrent use. Over-limits (pessimistic) rather than under-limits in sequential use. MEDIUM severity.
- Task 4.1: Timeout not retried - requirements say "retry on timeout" but code raises CFNetworkError immediately. Only 429 responses are retried. HIGH severity.

### Testing Patterns
- Docker available on this machine (v29.1.3), can use `docker compose config` for YAML validation
- Use `cp .env.example .env` before compose validation since docker-compose.yml references .env via env_file
- Project has no `docker/` subdirectory; Docker files live in project root
- For schema verification: cross-reference task.md table definitions against both model files AND migration files; always check consistency between the two layers
- Test files use lightweight SQLite-compatible models (prefixed with `_Test`) and patch production model references in the service module to redirect queries to SQLite tables
- Tests patch `pp_svc_module.PPService.record_pp` and `elo_svc_module.EloService.record_elo_history` to avoid cross-model dependencies
- pytest-asyncio with AUTO mode; fixtures yield async sessions with context-managed patches

### Service Test Coverage (verified)
- Task 7.1 (contest_service): 57 tests, all passing. Covers tier eligibility, start/submit/end lifecycle, timing/auto-expiry, token rewards (15 parametrized cases), M-Elo settlement, quit penalties, concurrent contest guard, access control, problem selection, and history.
