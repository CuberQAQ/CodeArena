---
name: task17-pve-testing-patterns
description: Testing patterns and observations from Task 17.1 PvE challenge backend testing
metadata:
  type: reference
---

# Task 17.1 PvE Challenge Backend Testing Notes

## Key File Locations
- `/home/cuberqaq/projects/code-arena/backend/app/services/pve_challenge_service.py` - PvE service (558 lines)
- `/home/cuberqaq/projects/code-arena/backend/app/api/v1/pve_challenge.py` - 5 API endpoints
- `/home/cuberqaq/projects/code-arena/backend/app/models/pve_challenge_session.py` - ORM model
- `/home/cuberqaq/projects/code-arena/backend/app/schemas/pve_challenge.py` - Pydantic schemas
- `/home/cuberqaq/projects/code-arena/backend/migrations/versions/c3d4e5f6g7h8_add_pve_challenge_sessions_table.py` - Migration
- `/home/cuberqaq/projects/code-arena/backend/tests/test_pve_challenge.py` - 40 tests

## Test Architecture
- Uses SQLite in-memory with lightweight `_Test*` model classes
- Patches production model references in `pve_svc_module` (e.g., `PvEChallengeSession`, `User`, `PPRecord`)
- Mocks external dependencies: `EloService`, `PPService`, `ConfigService`, `economy_svc.award_tokens`
- pytest-asyncio AUTO mode with async fixtures

## Observations Found
1. quit_challenge returns raw dict instead of Pydantic model (PvEQuitResponse defined but unused)
2. solved=True + attempts=0 logically contradictory but not validated by schema
3. quit 3+ submission test assertion coupled to mock K-factor value

## Selection Range Constants
- `_SELECTION_RANGES` in service: `[(-100, 200), (-200, 300), (-300, 400)]`
- Verified matches requirements FR-2.1 exactly

## Cross-Layer Consistency
- Model columns == Migration columns (exact match)
- Model has 2 extra columns beyond task spec: `problem_tags` (JSON), `s_value` (Float) - both reasonable
