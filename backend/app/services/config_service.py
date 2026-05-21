"""Configuration management service.

Provides a database-backed key/value store for system-wide configuration
with an in-memory cache (TTL 60 s).  Every read falls back to the defaults
defined in ``app.core.default_config`` when no database row exists.

Key format
----------
Keys use dot-separated paths to address nested values, e.g.
``"elo.k_factor"`` resolves to ``DEFAULT_CONFIG["elo"]["k_factor"]``.
Top-level section keys like ``"elo"`` return the whole sub-dict.
"""

import time
import uuid
from contextlib import suppress
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.default_config import DEFAULT_CONFIG, VALIDATION_RULES
from app.models.system_config import SystemConfig

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_CACHE_TTL: float = 60.0  # seconds

_cache: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str) -> tuple[bool, Any]:
    """Return ``(hit, value)`` from the in-memory cache."""
    entry = _cache.get(key)
    if entry is None:
        return False, None
    ts, value = entry
    if time.monotonic() - ts > _CACHE_TTL:
        del _cache[key]
        return False, None
    return True, value


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)


def _cache_invalidate(key: str | None = None) -> None:
    """Remove a single key or flush the entire cache."""
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)


def _invalidate_key_and_parents(key: str) -> None:
    """Invalidate *key* and all parent section keys in the cache.

    For example, ``"economy.difficulty_tiers.gray.ac_reward"`` also
    invalidates ``"economy"``, ``"economy.difficulty_tiers"``, and
    ``"economy.difficulty_tiers.gray"``.
    """
    _cache_invalidate(key)
    parts = key.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        _cache_invalidate(parent)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_by_path(data: dict, path: str) -> Any:
    """Walk *data* along *path* (``"a.b.c"``) and return the leaf value.

    Raises ``KeyError`` if the path cannot be fully resolved.
    """
    parts = path.split(".")
    node: Any = data
    for part in parts:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise KeyError(path)
    return node


def _set_by_path(data: dict, path: str, value: Any) -> None:
    """Set a nested value in *data* identified by *path*.

    Raises ``KeyError`` if intermediate segments do not exist.
    """
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise KeyError(path)
    if not isinstance(node, dict) or parts[-1] not in node:
        raise KeyError(path)
    node[parts[-1]] = value


def _flatten(data: dict, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict into ``{"a.b.c": value}`` pairs."""
    out: dict[str, Any] = {}
    for k, v in data.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, full))
        else:
            out[full] = v
    return out


def _validate_config_value(key: str, value: Any) -> None:
    """Validate *value* against ``VALIDATION_RULES``.

    Raises ``ValueError`` when validation fails.
    """
    rule = VALIDATION_RULES.get(key)
    if rule is None:
        # No specific rule -- allow any JSON-compatible value
        return

    expected_type = rule["type"]
    if not isinstance(value, expected_type):
        # Allow int where float is expected
        if expected_type is float and isinstance(value, int):
            pass  # acceptable
        else:
            type_name = getattr(expected_type, "__name__", str(expected_type))
            raise ValueError(f"Config key '{key}': expected type {type_name}, got {type(value).__name__}")

    if "min" in rule and isinstance(value, int | float) and value < rule["min"]:
        raise ValueError(f"Config key '{key}': value {value} is below minimum {rule['min']}")
    if "max" in rule and isinstance(value, int | float) and value > rule["max"]:
        raise ValueError(f"Config key '{key}': value {value} is above maximum {rule['max']}")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ConfigService:
    """Database-backed configuration with in-memory TTL cache."""

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    @staticmethod
    async def get_config(db: AsyncSession, key: str) -> Any:
        """Return the configuration value for *key*.

        Resolution order:
        1. In-memory cache
        2. Database row (exact match + child-key overlay)
        3. DEFAULT_CONFIG fallback
        """
        # 1. Cache
        hit, cached = _cache_get(key)
        if hit:
            return deepcopy(cached)

        # 2. Database – exact match
        stmt = select(SystemConfig).where(SystemConfig.config_key == key)
        result = await db.execute(stmt)
        row: SystemConfig | None = result.scalar_one_or_none()

        if row is not None and row.config_value is not None:
            value = row.config_value
            _cache_set(key, value)
            return deepcopy(value)

        # 3. Fallback to defaults
        try:
            value = _resolve_by_path(DEFAULT_CONFIG, key)
        except KeyError:
            raise KeyError(f"Unknown config key: '{key}'") from None

        # If the value is a dict (section key), overlay any child-key overrides
        if isinstance(value, dict):
            prefix = key + "."
            stmt_children = select(SystemConfig).where(SystemConfig.config_key.startswith(prefix))
            result_children = await db.execute(stmt_children)
            child_rows = result_children.scalars().all()
            if child_rows:
                merged = deepcopy(value)
                for child in child_rows:
                    if child.config_value is not None:
                        child_suffix = child.config_key[len(prefix) :]
                        with suppress(KeyError):
                            _set_by_path(merged, child_suffix, child.config_value)
                _cache_set(key, merged)
                return deepcopy(merged)

        _cache_set(key, value)
        return deepcopy(value)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    @staticmethod
    async def set_config(
        db: AsyncSession,
        key: str,
        value: Any,
        admin_id: uuid.UUID,
    ) -> None:
        """Set (upsert) a configuration value.

        Validates the value against ``VALIDATION_RULES`` before persisting.
        """
        # Verify the key exists in defaults
        try:
            _resolve_by_path(DEFAULT_CONFIG, key)
        except KeyError:
            raise KeyError(f"Unknown config key: '{key}'") from None

        _validate_config_value(key, value)

        stmt = select(SystemConfig).where(SystemConfig.config_key == key)
        result = await db.execute(stmt)
        row: SystemConfig | None = result.scalar_one_or_none()

        if row is not None:
            row.config_value = value
            row.updated_by = admin_id
        else:
            row = SystemConfig(
                config_key=key,
                config_value=value,
                updated_by=admin_id,
            )
            db.add(row)

        await db.flush()
        _invalidate_key_and_parents(key)

    # ------------------------------------------------------------------
    # Bulk read
    # ------------------------------------------------------------------

    @staticmethod
    async def get_all_config(db: AsyncSession) -> dict:
        """Return a deep-merged dict of defaults overlaid with DB overrides."""
        merged = deepcopy(DEFAULT_CONFIG)

        stmt = select(SystemConfig)
        result = await db.execute(stmt)
        rows = result.scalars().all()

        for row in rows:
            if row.config_value is not None:
                with suppress(KeyError):
                    _set_by_path(merged, row.config_key, row.config_value)

        return merged

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    @staticmethod
    async def reset_config(
        db: AsyncSession,
        key: str,
        admin_id: uuid.UUID,
    ) -> Any:
        """Reset a config key to its DEFAULT_CONFIG value.

        Deletes the database row so that future reads fall back to the
        default.  Returns the default value.
        """
        try:
            default_value = _resolve_by_path(DEFAULT_CONFIG, key)
        except KeyError:
            raise KeyError(f"Unknown config key: '{key}'") from None

        stmt = select(SystemConfig).where(SystemConfig.config_key == key)
        result = await db.execute(stmt)
        row: SystemConfig | None = result.scalar_one_or_none()

        if row is not None:
            await db.delete(row)
            await db.flush()

        _invalidate_key_and_parents(key)
        return default_value

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    @staticmethod
    async def initialize_defaults(db: AsyncSession) -> None:
        """Populate the database with all default config rows.

        Only inserts rows that do not already exist, so this is safe to call
        on every application startup.
        """
        flat = _flatten(DEFAULT_CONFIG)

        # Batch-load existing keys to avoid N+1 queries
        existing_keys: set[str] = set()
        if flat:
            stmt = select(SystemConfig.config_key).where(SystemConfig.config_key.in_(flat.keys()))
            result = await db.execute(stmt)
            existing_keys = {row[0] for row in result.all()}

        for key, value in flat.items():
            if key not in existing_keys:
                row = SystemConfig(
                    config_key=key,
                    config_value=value,
                )
                db.add(row)

        await db.flush()
        _cache_invalidate()
