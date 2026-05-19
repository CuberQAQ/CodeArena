# Professional Test Engineer - Agent Memory

## Project: Code Arena

### Architecture
- Docker-based fullstack app: React (Vite) frontend + FastAPI backend + PostgreSQL
- Docker Compose split: docker-compose.yml (production) + docker-compose.dev.yml (development overlay)
- Nginx serves frontend static files and proxies /api/ to backend

### Key File Locations
- `/home/cuberqaq/projects/code-arena/docker-compose.yml` - production compose
- `/home/cuberqaq/projects/code-arena/docker-compose.dev.yml` - dev overlay
- `/home/cuberqaq/projects/code-arena/Dockerfile.frontend` - multi-stage (node build + nginx serve)
- `/home/cuberqaq/projects/code-arena/Dockerfile.backend` - python:3.12-slim + uvicorn
- `/home/cuberqaq/projects/code-arena/nginx.conf` - SPA routing + API proxy
- `/home/cuberqaq/projects/code-arena/.env.example` - environment template

### Known Issues (Task 1.2)
- [docker-compose.dev.yml frontend port/healthcheck conflict](defects.md) - HIGH severity, dev mode frontend healthcheck fails

### Testing Patterns
- Docker available on this machine (v29.1.3), can use `docker compose config` for YAML validation
- Use `cp .env.example .env` before compose validation since docker-compose.yml references .env via env_file
- Project has no `docker/` subdirectory; Docker files live in project root
