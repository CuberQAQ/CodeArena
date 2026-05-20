---
name: quit-path-pattern
description: Quit/abandon paths across game modes often skip M-Elo and other cross-cutting updates
metadata:
  type: feedback
---

When a new cross-cutting feature (M-Elo, time_factor, achievement events, etc.) is added to the "happy path" submit_result/settle methods, the quit_challenge paths are frequently overlooked.

**Why:** Quit paths are separate code blocks that handle tiered penalties differently (0 submissions, 1-2 submissions, 3+ submissions). When submissions >= 3, they apply the full failure formula (S=0) to Global Elo but often forget to apply the same cross-cutting feature to M-Elo or other per-tag resources.

**How to apply:** For every feature that applies to "failure" outcomes, check BOTH the normal submit path AND the quit/abandon path in ALL modes (PvE, PvP, Contest). In this codebase, the affected methods are:
- `pve_challenge_service.py` -> `quit_challenge()`
- `challenge_service.py` -> `quit_challenge()`
- `contest_service.py` -> `end_contest()` and `_auto_end_expired()`
