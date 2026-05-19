---
name: defects
description: Known defects discovered during testing
metadata:
  type: project
---

## BUG-001: docker-compose.dev.yml frontend port/healthcheck conflict

**Severity**: High
**Status**: Open
**Found**: Task 1.2 testing (2026-05-19)

**Problem**: When docker-compose.dev.yml is overlaid on docker-compose.yml:
1. Port conflict: FRONTEND_PORT=80 (from .env.example) creates two mappings on host port 80 (80:80 from base + 80:5173 from dev)
2. Healthcheck mismatch: base healthcheck checks port 80, but Vite dev server listens on 5173

**Fix**: Hardcode port to "5173:5173" in dev overlay and override healthcheck to check port 5173.
