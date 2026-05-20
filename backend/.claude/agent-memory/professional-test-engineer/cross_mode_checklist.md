---
name: cross-mode-checklist
description: Checklist for verifying cross-mode feature consistency (PvE, PvP, Contest, Training)
metadata:
  type: feedback
---

When testing a cross-cutting feature, verify it in ALL four game modes. The settlement entry points are:

| Mode | Service | Settlement Method | Notes |
|------|---------|-------------------|-------|
| PvE | `pve_challenge_service.py` | `submit_result()` | Also check `quit_challenge()` |
| PvP | `challenge_service.py` | `_settle_challenge()` | Also check `quit_challenge()` |
| Contest | `contest_service.py` | `submit_problem()` | Also check `end_contest()`, `_auto_end_expired()`, `_settle_with_pr()` |
| Training | `training_service.py` | `_calculate_training_elo()` | Has its own coefficient logic (x0.5/x2.0) |

Key cross-cutting features to verify per mode: M-Elo update, time_factor, hint_attenuation, achievement events, token rewards, shield check, PP recording.

**Why:** This project has 4 game modes and features like FR-9 (M-Elo), FR-16 (time factor), FR-5.3 (hint attenuation) must work consistently across all of them. The codebase has a pattern where features are implemented in one mode's submit path but missed in other modes or in quit paths.

**How to apply:** For each test task, create a matrix: Feature x Mode x Path (submit/quit). Mark each cell. Any empty cell is a potential gap.
