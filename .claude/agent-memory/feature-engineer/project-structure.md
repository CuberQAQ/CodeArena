---
name: project-structure
description: Code Arena project directory layout and key file locations
metadata:
  type: reference
---

# Project Structure

## Backend (`backend/`)
```
backend/
  alembic.ini          - Alembic config (script_location=migrations, async URL)
  requirements.txt     - Python dependencies
  pyproject.toml       - ruff + pytest config
  app/
    main.py            - FastAPI app entry point
    core/
      config.py        - Pydantic Settings (DATABASE_URL, JWT, CF API, etc.)
      database.py      - Async engine, sessionmaker, get_db dependency
    models/
      base.py          - Base, UUIDPrimaryKeyMixin, TimestampMixin
      user.py          - User model
      elo_history.py   - EloHistory model
      pp_record.py     - PPRecord model
      challenge_session.py  - ChallengeSession model
      topic_category.py     - TopicCategory model
      training_session.py   - TrainingSession model
      training_problem_record.py - TrainingProblemRecord model
      contest_session.py    - ContestSession model
      contest_problem_record.py - ContestProblemRecord model
      token_transaction.py  - TokenTransaction model
      hint_purchase.py      - HintPurchase model
      system_config.py      - SystemConfig model
      __init__.py           - Re-exports all models + Base
    api/v1/router.py   - API router (currently minimal)
    services/          - Business logic (empty)
    schemas/           - Pydantic schemas (empty)
    middleware/         - Middleware (empty)
    utils/              - Utilities (empty)
  migrations/
    env.py             - Alembic env with async support + model autodiscovery
    script.py.mako     - Migration template
    versions/          - Migration files
  tests/               - Test directory
```

## Frontend (`frontend/`)
- React + Vite + TypeScript project
