"""Tests for the configuration management service.

Uses in-memory SQLite with lightweight test models to avoid PostgreSQL
dependencies.  The real ``SystemConfig`` model uses JSONB / UUID types
that SQLite cannot render, so we create compatible test equivalents and
patch the module-level import in config_service.
"""

import time
import uuid

import pytest
from sqlalchemy import DateTime, String, Text, event
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.core.default_config import DEFAULT_CONFIG, VALIDATION_RULES
from app.services import config_service as _cs_module
from app.services.config_service import (
    ConfigService,
    _cache_invalidate,
    _cache_set,
    _flatten,
    _resolve_by_path,
    _set_by_path,
    _validate_config_value,
)

# ---------------------------------------------------------------------------
# Lightweight SQLite-compatible test model
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _TestSystemConfig(_TestBase):
    __tablename__ = "system_config"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    config_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    config_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)

    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db(async_engine):
    """Provide an async session with the SystemConfig model patched to use SQLite.

    We replace the module-level ``SystemConfig`` reference in config_service
    with our SQLite-compatible _TestSystemConfig for the duration of the test.
    """
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    original_model = _cs_module.SystemConfig
    _cs_module.SystemConfig = _TestSystemConfig

    try:
        async with session_factory() as session:
            yield session
    finally:
        _cs_module.SystemConfig = original_model


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure cache is clean before and after every test."""
    _cache_invalidate()
    yield
    _cache_invalidate()


# ---------------------------------------------------------------------------
# 1. Path resolution helpers
# ---------------------------------------------------------------------------


class TestResolveByPath:
    def test_top_level_key(self):
        assert _resolve_by_path(DEFAULT_CONFIG, "elo") == DEFAULT_CONFIG["elo"]

    def test_nested_key(self):
        assert _resolve_by_path(DEFAULT_CONFIG, "elo.k_factor") == 32

    def test_deeply_nested(self):
        assert _resolve_by_path(DEFAULT_CONFIG, "economy.difficulty_tiers.gray.ac_reward") == 10

    def test_list_value(self):
        assert _resolve_by_path(DEFAULT_CONFIG, "elo.hint_decay") == [0.75, 0.50, 0.25]

    def test_unknown_key_raises(self):
        with pytest.raises(KeyError):
            _resolve_by_path(DEFAULT_CONFIG, "nonexistent")

    def test_partial_path_raises(self):
        with pytest.raises(KeyError):
            _resolve_by_path(DEFAULT_CONFIG, "elo.k_factor.extra")


class TestSetByPath:
    def test_set_nested_value(self):
        data = {"a": {"b": {"c": 1}}}
        _set_by_path(data, "a.b.c", 42)
        assert data["a"]["b"]["c"] == 42

    def test_set_missing_intermediate_raises(self):
        data = {"a": {}}
        with pytest.raises(KeyError):
            _set_by_path(data, "a.x.y", 1)

    def test_set_missing_leaf_raises(self):
        data = {"a": {"b": 1}}
        with pytest.raises(KeyError):
            _set_by_path(data, "a.c", 2)


class TestFlatten:
    def test_flat_dict(self):
        assert _flatten({"x": 1, "y": 2}) == {"x": 1, "y": 2}

    def test_nested_dict(self):
        result = _flatten({"a": {"b": 1, "c": {"d": 2}}})
        assert result == {"a.b": 1, "a.c.d": 2}

    def test_preserves_list(self):
        result = _flatten({"a": {"b": [1, 2, 3]}})
        assert result == {"a.b": [1, 2, 3]}

    def test_empty_dict(self):
        assert _flatten({}) == {}


# ---------------------------------------------------------------------------
# 2. Validation
# ---------------------------------------------------------------------------


class TestValidateConfigValue:
    def test_valid_int_in_range(self):
        _validate_config_value("elo.k_factor", 40)  # should not raise

    def test_valid_float_in_range(self):
        _validate_config_value("elo.k_factor", 40.0)  # should not raise

    def test_int_accepted_for_float_field(self):
        """int is acceptable where float is expected."""
        _validate_config_value("pp.decay_factor", 1)

    def test_wrong_type_raises(self):
        with pytest.raises(ValueError, match="expected type"):
            _validate_config_value("elo.k_factor", "not_a_number")

    def test_below_min_raises(self):
        with pytest.raises(ValueError, match="below minimum"):
            _validate_config_value("elo.k_factor", 0)

    def test_above_max_raises(self):
        with pytest.raises(ValueError, match="above maximum"):
            _validate_config_value("elo.k_factor", 101)

    def test_boundary_min_ok(self):
        _validate_config_value("elo.k_factor", 1)

    def test_boundary_max_ok(self):
        _validate_config_value("elo.k_factor", 100)

    def test_no_rule_allows_any(self):
        """Keys not in VALIDATION_RULES should pass without error."""
        _validate_config_value("some.unknown.key", {"anything": True})

    def test_string_type_rejected_for_numeric(self):
        with pytest.raises(ValueError, match="expected type"):
            _validate_config_value("elo.initial_elo", "1200")

    def test_negative_rejected(self):
        with pytest.raises(ValueError, match="below minimum"):
            _validate_config_value("pp.max_problems", -1)


# ---------------------------------------------------------------------------
# 3. Cache behaviour
# ---------------------------------------------------------------------------


class TestCache:
    def test_cache_set_and_get(self):
        from app.services.config_service import _cache_get

        _cache_set("test_key", 42)
        hit, value = _cache_get("test_key")
        assert hit is True
        assert value == 42

    def test_cache_miss(self):
        from app.services.config_service import _cache_get

        hit, value = _cache_get("nonexistent")
        assert hit is False
        assert value is None

    def test_cache_invalidate_key(self):
        from app.services.config_service import _cache_get

        _cache_set("a", 1)
        _cache_set("b", 2)
        _cache_invalidate("a")
        assert _cache_get("a") == (False, None)
        assert _cache_get("b") == (True, 2)

    def test_cache_invalidate_all(self):
        from app.services.config_service import _cache_get

        _cache_set("a", 1)
        _cache_set("b", 2)
        _cache_invalidate()
        assert _cache_get("a") == (False, None)
        assert _cache_get("b") == (False, None)

    def test_cache_ttl_expiry(self):
        """Manually expire a cache entry by backdating its timestamp."""
        from app.services import config_service as cs

        cs._cache["ttl_test"] = (time.monotonic() - cs._CACHE_TTL - 1, "stale")

        hit, value = cs._cache_get("ttl_test")
        assert hit is False
        assert value is None


# ---------------------------------------------------------------------------
# 4. ConfigService - get_config
# ---------------------------------------------------------------------------


class TestGetConfig:
    async def test_get_default_value(self, db: AsyncSession):
        """When no DB row exists, should return the DEFAULT_CONFIG value."""
        value = await ConfigService.get_config(db, "elo.k_factor")
        assert value == 32

    async def test_get_nested_section(self, db: AsyncSession):
        """Top-level section key returns the whole sub-dict."""
        value = await ConfigService.get_config(db, "elo")
        assert isinstance(value, dict)
        assert value["k_factor"] == 32
        assert value["initial_elo"] == 1200

    async def test_get_deeply_nested(self, db: AsyncSession):
        value = await ConfigService.get_config(db, "economy.difficulty_tiers.blue.ac_reward")
        assert value == 30

    async def test_get_list_value(self, db: AsyncSession):
        value = await ConfigService.get_config(db, "elo.hint_decay")
        assert value == [0.75, 0.50, 0.25]

    async def test_get_unknown_key_raises(self, db: AsyncSession):
        with pytest.raises(KeyError, match="Unknown config key"):
            await ConfigService.get_config(db, "nonexistent.key")

    async def test_get_returns_copy(self, db: AsyncSession):
        """Successive calls should return independent copies."""
        v1 = await ConfigService.get_config(db, "elo")
        v2 = await ConfigService.get_config(db, "elo")
        v1["k_factor"] = 999
        assert v2["k_factor"] == 32


# ---------------------------------------------------------------------------
# 5. ConfigService - set_config
# ---------------------------------------------------------------------------


class TestSetConfig:
    async def test_set_new_value(self, db: AsyncSession):
        admin_id = uuid.uuid4()
        await ConfigService.set_config(db, "elo.k_factor", 64, admin_id)

        value = await ConfigService.get_config(db, "elo.k_factor")
        assert value == 64

    async def test_set_updates_existing(self, db: AsyncSession):
        admin_id = uuid.uuid4()
        await ConfigService.set_config(db, "elo.k_factor", 48, admin_id)
        await ConfigService.set_config(db, "elo.k_factor", 64, admin_id)

        value = await ConfigService.get_config(db, "elo.k_factor")
        assert value == 64

    async def test_set_unknown_key_raises(self, db: AsyncSession):
        admin_id = uuid.uuid4()
        with pytest.raises(KeyError, match="Unknown config key"):
            await ConfigService.set_config(db, "nonexistent.key", 1, admin_id)

    async def test_set_invalid_value_raises(self, db: AsyncSession):
        admin_id = uuid.uuid4()
        with pytest.raises(ValueError, match="expected type"):
            await ConfigService.set_config(db, "elo.k_factor", "bad", admin_id)

    async def test_set_out_of_range_raises(self, db: AsyncSession):
        admin_id = uuid.uuid4()
        with pytest.raises(ValueError, match="above maximum"):
            await ConfigService.set_config(db, "elo.k_factor", 200, admin_id)

    async def test_set_invalidates_cache(self, db: AsyncSession):
        """After set_config, a subsequent get_config must reflect the new value."""
        admin_id = uuid.uuid4()
        # Prime the cache with the default
        await ConfigService.get_config(db, "elo.k_factor")
        # Override via set
        await ConfigService.set_config(db, "elo.k_factor", 50, admin_id)
        value = await ConfigService.get_config(db, "elo.k_factor")
        assert value == 50

    async def test_set_float_for_int_field(self, db: AsyncSession):
        """int fields should also accept float (e.g. 32.0 for k_factor)."""
        admin_id = uuid.uuid4()
        await ConfigService.set_config(db, "elo.k_factor", 48.0, admin_id)
        value = await ConfigService.get_config(db, "elo.k_factor")
        assert value == 48.0


# ---------------------------------------------------------------------------
# 6. ConfigService - get_all_config
# ---------------------------------------------------------------------------


class TestGetAllConfig:
    async def test_returns_full_defaults(self, db: AsyncSession):
        result = await ConfigService.get_all_config(db)
        assert "elo" in result
        assert "pp" in result
        assert "challenge" in result
        assert "economy" in result
        assert "contest" in result
        assert "cf_api" in result

    async def test_overrides_applied(self, db: AsyncSession):
        admin_id = uuid.uuid4()
        await ConfigService.set_config(db, "elo.k_factor", 64, admin_id)

        result = await ConfigService.get_all_config(db)
        assert result["elo"]["k_factor"] == 64

    async def test_no_mutation_of_defaults(self, db: AsyncSession):
        """get_all_config must not mutate DEFAULT_CONFIG."""
        await ConfigService.get_all_config(db)
        assert DEFAULT_CONFIG["elo"]["k_factor"] == 32


# ---------------------------------------------------------------------------
# 7. ConfigService - reset_config
# ---------------------------------------------------------------------------


class TestResetConfig:
    async def test_reset_returns_default(self, db: AsyncSession):
        admin_id = uuid.uuid4()
        await ConfigService.set_config(db, "elo.k_factor", 64, admin_id)

        default_val = await ConfigService.reset_config(db, "elo.k_factor", admin_id)
        assert default_val == 32

    async def test_reset_clears_override(self, db: AsyncSession):
        admin_id = uuid.uuid4()
        await ConfigService.set_config(db, "elo.k_factor", 64, admin_id)
        await ConfigService.reset_config(db, "elo.k_factor", admin_id)

        value = await ConfigService.get_config(db, "elo.k_factor")
        assert value == 32

    async def test_reset_unknown_key_raises(self, db: AsyncSession):
        admin_id = uuid.uuid4()
        with pytest.raises(KeyError, match="Unknown config key"):
            await ConfigService.reset_config(db, "nonexistent", admin_id)

    async def test_reset_idempotent(self, db: AsyncSession):
        """Resetting a key that has no override should still succeed."""
        admin_id = uuid.uuid4()
        default_val = await ConfigService.reset_config(db, "elo.k_factor", admin_id)
        assert default_val == 32


# ---------------------------------------------------------------------------
# 8. ConfigService - initialize_defaults
# ---------------------------------------------------------------------------


class TestInitializeDefaults:
    async def test_populates_all_keys(self, db: AsyncSession):
        await ConfigService.initialize_defaults(db)

        from sqlalchemy import select

        flat = _flatten(DEFAULT_CONFIG)
        stmt = select(_TestSystemConfig)
        result = await db.execute(stmt)
        rows = {r.config_key: r.config_value for r in result.scalars().all()}

        for key in flat:
            assert key in rows, f"Missing key in DB: {key}"

    async def test_idempotent(self, db: AsyncSession):
        """Calling initialize_defaults twice should not duplicate rows."""
        await ConfigService.initialize_defaults(db)
        await ConfigService.initialize_defaults(db)

        from sqlalchemy import func, select

        stmt = select(func.count()).select_from(_TestSystemConfig)
        result = await db.execute(stmt)
        count = result.scalar()
        flat = _flatten(DEFAULT_CONFIG)
        assert count == len(flat)

    async def test_does_not_overwrite_existing(self, db: AsyncSession):
        """Existing overrides should be preserved."""
        admin_id = uuid.uuid4()
        await ConfigService.initialize_defaults(db)
        await ConfigService.set_config(db, "elo.k_factor", 99, admin_id)

        await ConfigService.initialize_defaults(db)
        value = await ConfigService.get_config(db, "elo.k_factor")
        assert value == 99


# ---------------------------------------------------------------------------
# 9. End-to-end scenarios
# ---------------------------------------------------------------------------


class TestEndToEnd:
    async def test_set_get_reset_cycle(self, db: AsyncSession):
        admin_id = uuid.uuid4()

        # Default
        assert await ConfigService.get_config(db, "elo.initial_elo") == 1200

        # Override
        await ConfigService.set_config(db, "elo.initial_elo", 1500, admin_id)
        assert await ConfigService.get_config(db, "elo.initial_elo") == 1500

        # Reset
        await ConfigService.reset_config(db, "elo.initial_elo", admin_id)
        assert await ConfigService.get_config(db, "elo.initial_elo") == 1200

    async def test_multiple_overrides(self, db: AsyncSession):
        admin_id = uuid.uuid4()
        await ConfigService.set_config(db, "elo.k_factor", 48, admin_id)
        await ConfigService.set_config(db, "pp.decay_factor", 0.9, admin_id)

        all_config = await ConfigService.get_all_config(db)
        assert all_config["elo"]["k_factor"] == 48
        assert all_config["pp"]["decay_factor"] == 0.9
        # Non-overridden values should remain default
        assert all_config["pp"]["max_problems"] == 100

    async def test_nested_section_get(self, db: AsyncSession):
        """Getting a section key returns the full sub-tree with overrides."""
        admin_id = uuid.uuid4()
        await ConfigService.set_config(db, "elo.k_factor", 64, admin_id)

        elo_section = await ConfigService.get_config(db, "elo")
        assert elo_section["k_factor"] == 64
        assert elo_section["initial_elo"] == 1200
        assert elo_section["divisor"] == 400

    async def test_cache_hit_on_second_read(self, db: AsyncSession):
        """Second read should hit cache without another DB query."""
        # First read populates cache
        value1 = await ConfigService.get_config(db, "elo.k_factor")
        assert value1 == 32

        # Manually verify it is cached
        from app.services.config_service import _cache_get

        hit, cached = _cache_get("elo.k_factor")
        assert hit is True
        assert cached == 32

    async def test_economy_nested_dict(self, db: AsyncSession):
        """Economy config has deeply nested structures."""
        value = await ConfigService.get_config(db, "economy.difficulty_tiers.purple")
        assert value == {"min": 1700, "max": 1999, "ac_reward": 40, "attempt_reward": 5}

    async def test_contest_tiers(self, db: AsyncSession):
        value = await ConfigService.get_config(db, "contest.tiers.beginner")
        assert value == {
            "max_elo": 1400,
            "duration_minutes": 90,
            "problems": 4,
            "rating_range": [800, 1400],
        }

    async def test_cf_api_config(self, db: AsyncSession):
        value = await ConfigService.get_config(db, "cf_api")
        assert value["base_url"] == "https://codeforces.com/api"
        assert value["request_interval_seconds"] == 2

    async def test_full_config_all_sections_present(self, db: AsyncSession):
        """get_all_config returns all 7 top-level sections."""
        result = await ConfigService.get_all_config(db)
        expected_sections = {"elo", "pp", "challenge", "economy", "contest", "cf_api", "melo"}
        assert set(result.keys()) == expected_sections


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    async def test_get_config_after_set_same_as_default(self, db: AsyncSession):
        """Setting a value equal to the default should still persist."""
        admin_id = uuid.uuid4()
        await ConfigService.set_config(db, "elo.k_factor", 32, admin_id)
        value = await ConfigService.get_config(db, "elo.k_factor")
        assert value == 32

    async def test_validate_list_value_no_rule(self):
        """List values without explicit rules should pass validation."""
        _validate_config_value("elo.hint_decay", [0.5, 0.3, 0.1])

    def test_default_config_completeness(self):
        """Ensure all top-level sections exist in DEFAULT_CONFIG."""
        for section in ["elo", "pp", "challenge", "economy", "contest", "cf_api"]:
            assert section in DEFAULT_CONFIG, f"Missing section: {section}"

    def test_validation_rules_reference_valid_keys(self):
        """Every key in VALIDATION_RULES should resolve in DEFAULT_CONFIG."""
        for key in VALIDATION_RULES:
            _resolve_by_path(DEFAULT_CONFIG, key)  # should not raise

    async def test_reset_then_set(self, db: AsyncSession):
        """Reset then set should work correctly."""
        admin_id = uuid.uuid4()
        await ConfigService.set_config(db, "elo.k_factor", 64, admin_id)
        await ConfigService.reset_config(db, "elo.k_factor", admin_id)
        assert await ConfigService.get_config(db, "elo.k_factor") == 32

        await ConfigService.set_config(db, "elo.k_factor", 48, admin_id)
        assert await ConfigService.get_config(db, "elo.k_factor") == 48
