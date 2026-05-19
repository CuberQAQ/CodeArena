---
name: testing-patterns
description: Testing patterns for async SQLite tests in Code Arena backend
metadata:
  type: reference
---

# Async SQLite Testing Pattern

## Problem
Production models use PostgreSQL-specific types (JSONB, UUID with `server_default=func.uuid_generate_v4()`) that SQLite cannot render. Running `Base.metadata.create_all` in tests fails.

## Solution
1. Create lightweight test model classes on a **separate** `DeclarativeBase`
2. Use `Uuid` type with `default=uuid.uuid4` instead of `server_default=func.uuid_generate_v4()`
3. Patch service methods that create/query real ORM model instances with test-model versions
4. Use `sqlite+aiosqlite:///:memory:` as the test database

## Pattern
```python
class _TestBase(DeclarativeBase):
    pass

class _TestUser(_TestBase):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # ... minimal columns needed for test

class _TestEloHistory(_TestBase):
    __tablename__ = "elo_history"
    # ... columns matching real model but without PG-specific types

@pytest.fixture
async def db(async_engine):
    session_factory = async_sessionmaker(async_engine, ...)

    async def _test_record_elo_history(db_session, user_id, ...):
        record = _TestEloHistory(...)
        db_session.add(record)
        await db_session.flush()
        return record

    async with session_factory() as session:
        with patch.object(EloService, "record_elo_history", _test_record_elo_history):
            yield session
```

## Key points
- Enable `PRAGMA foreign_keys=ON` for SQLite via `event.listens_for`
- Patch all service methods that reference real ORM models
- Use `aiosqlite` package for async SQLite support
