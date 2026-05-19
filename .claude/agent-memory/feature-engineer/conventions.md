---
name: conventions
description: Coding conventions and patterns discovered in the Code Arena project
metadata:
  type: reference
---

# Coding Conventions

## Python Style
- **Target**: Python 3.11+, line-length 120
- **Linter**: ruff with rules E, F, I, N, UP, B, A, SIM
- **Type hints**: Full typing with `Mapped[...]` from SQLAlchemy 2.0 style
- **Nullable**: Use `type | None` syntax (Python 3.11+ union)

## SQLAlchemy Patterns
- **Declarative**: `DeclarativeBase` subclass in `base.py`
- **Mapped columns**: Always use `Mapped[type]` + `mapped_column(...)`
- **UUID PKs**: Via `UUIDPrimaryKeyMixin` with `server_default=func.uuid_generate_v4()`
- **Timestamps**: `server_default=func.now()`, `onupdate=func.now()` for updated_at
- **Server defaults**: Use `server_default=sa.text('...')` for string/bool/int defaults
- **Relationships**: Use `relationship()` with `back_populates` and `cascade="all, delete-orphan"`
- **Foreign keys**: Use `UUID(as_uuid=True)` type, explicit `ondelete` in ForeignKey

## Model Organization
- One model per file under `app/models/`
- All models re-exported from `app/models/__init__.py`
- Base mixins in `app/models/base.py`

## Alembic
- Async mode configured in `migrations/env.py`
- Uses `async_engine_from_config` + `pool.NullPool`
- URL overridden from `settings.DATABASE_URL` at runtime
- All model imports are explicit in env.py for autogenerate detection
