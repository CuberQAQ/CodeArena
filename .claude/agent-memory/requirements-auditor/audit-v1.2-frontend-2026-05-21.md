---
name: audit-v1.2-frontend-2026-05-21
description: V1.2 frontend module audit results: FR-8/10/11/12/13/14/15/17/18 compliance status
metadata:
  type: project
---

# V1.2 Frontend Audit Results (2026-05-21)

## Critical Finding: Medal EC Final Level Missing
- Both backend `_FLAT_MEDAL_MAP` and frontend `FLAT_MEDAL_MAP` skip `ec_final` level entirely
- `MEDAL_TIERS` structure has `ec_final` but it's only for display, not calculation
- Rating 2200 gets "regional gold" instead of "ec_final bronze" per FR-10.1
- Files: `backend/app/services/medal_service.py:31-41`, `frontend/src/utils/index.ts:133-143`

## Critical Finding: ProblemViewer Only Used in FreePlay
- FR-14.1 requires iframe embedding for training + contest, but `ProblemViewer` is only used in `FreePlaySessionPage`
- PvE uses external link (correct per FR-14.2 blind-box mode)
- Training and Contest pages only show external links, no iframe
- File: `frontend/src/components/ProblemViewer.tsx` (exists but not integrated)

## All Findings Summary
- Total items: 30
- PASS: 25
- PARTIAL: 2 (FR-10.1 medal mapping, FR-14.1 training/contest iframe)
- FAIL: 0
- NOT_FOUND: 0
- UNREACHABLE: 3 (FR-14.1 training/contest, FR-8.4 training/contest timeline)
