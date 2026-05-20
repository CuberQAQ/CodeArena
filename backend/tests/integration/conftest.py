"""Shared fixtures for end-to-end integration tests.

Provides:
- In-memory SQLite async database with SQLite-compatible test models
- Patched service modules that use the test models
- Helper factories for common entities (users, topics, etc.)
- CF API mock helper
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, TypeDecorator, event
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.security import create_access_token, hash_password
from app.services.config_service import ConfigService
from app.services.elo_service import EloService

# ---------------------------------------------------------------------------
# Custom UUID type for SQLite compatibility
# ---------------------------------------------------------------------------


class SQLiteUUID(TypeDecorator):
    """A UUID type that stores values as plain strings in SQLite.

    Handles both uuid.UUID objects and string representations transparently,
    avoiding the PostgreSQL-specific UUID type handler that breaks with SQLite.
    """
    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return str(value)
        return value


# ---------------------------------------------------------------------------
# SQLite-compatible test models
# ---------------------------------------------------------------------------


class TestBase(DeclarativeBase):
    pass


class _TestUser(TestBase):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(SQLiteUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    cf_handle: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    cf_handle_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_tokens_earned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_tokens_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class _TestEloHistory(TestBase):
    __tablename__ = "elo_history"

    id: Mapped[str] = mapped_column(SQLiteUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(SQLiteUUID, nullable=False)
    elo_before: Mapped[int] = mapped_column(Integer, nullable=False)
    elo_after: Mapped[int] = mapped_column(Integer, nullable=False)
    elo_change: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(SQLiteUUID, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestPPRecord(TestBase):
    __tablename__ = "pp_records"

    id: Mapped[str] = mapped_column(SQLiteUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(SQLiteUUID, nullable=False)
    cf_problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    base_pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hints_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wa_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_spent_minutes: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    performance_factor: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    final_pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    overkill_multiplier: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)


class _TestChallengeSession(TestBase):
    __tablename__ = "challenge_sessions"

    id: Mapped[str] = mapped_column(SQLiteUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    challenger_id: Mapped[str] = mapped_column(SQLiteUUID, nullable=False)
    opponent_id: Mapped[str] = mapped_column(SQLiteUUID, nullable=False)
    problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    challenger_submissions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opponent_submissions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    challenger_solved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opponent_solved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    challenger_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    opponent_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    elo_change: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hints_used_challenger: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hints_used_opponent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestTopicCategory(TestBase):
    __tablename__ = "topic_categories"

    id: Mapped[str] = mapped_column(SQLiteUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cf_tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class _TestTrainingSession(TestBase):
    __tablename__ = "training_sessions"

    id: Mapped[str] = mapped_column(SQLiteUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(SQLiteUUID, nullable=False)
    topic_id: Mapped[str] = mapped_column(SQLiteUUID, nullable=False)
    problems_solved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_problems: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    streak_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestTrainingProblemRecord(TestBase):
    __tablename__ = "training_problem_records"

    id: Mapped[str] = mapped_column(SQLiteUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(SQLiteUUID, nullable=False)
    user_id: Mapped[str] = mapped_column(SQLiteUUID, nullable=False)
    topic_id: Mapped[str] = mapped_column(SQLiteUUID, nullable=False)
    problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    solved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_spent: Mapped[float | None] = mapped_column(Float, nullable=True)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestContestSession(TestBase):
    __tablename__ = "contest_sessions"

    id: Mapped[str] = mapped_column(SQLiteUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(SQLiteUUID, nullable=False)
    contest_tier: Mapped[str] = mapped_column(String(20), nullable=False)
    problems: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_problems: Mapped[int] = mapped_column(Integer, nullable=False)
    problems_solved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    submissions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    elo_change: Mapped[int | None] = mapped_column(Integer, nullable=True)


class _TestContestProblemRecord(TestBase):
    __tablename__ = "contest_problem_records"

    id: Mapped[str] = mapped_column(SQLiteUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    contest_id: Mapped[str] = mapped_column(SQLiteUUID, nullable=False)
    problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    solved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_spent: Mapped[float | None] = mapped_column(Float, nullable=True)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestTokenTransaction(TestBase):
    __tablename__ = "token_transactions"

    id: Mapped[str] = mapped_column(SQLiteUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(SQLiteUUID, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(SQLiteUUID, nullable=True)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=True)


class _TestHintPurchase(TestBase):
    __tablename__ = "hint_purchases"

    id: Mapped[str] = mapped_column(SQLiteUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(SQLiteUUID, nullable=False)
    problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hint_level: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestSystemConfig(TestBase):
    __tablename__ = "system_config"

    id: Mapped[str] = mapped_column(SQLiteUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(SQLiteUUID, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Module references for patching
# ---------------------------------------------------------------------------

# All services that import models
from app.core import security as _security_mod
from app.services import admin_service as _admin_mod
from app.services import auth_service as _auth_mod
from app.services import challenge_service as _chal_mod
from app.services import config_service as _config_mod
from app.services import contest_service as _contest_mod
from app.services import contest_simulation_service as _sim_mod
from app.services import economy_service as _eco_mod
from app.services import elo_service as _elo_mod
from app.services import hint_service as _hint_mod
from app.services import melo_service as _melo_mod
from app.services import pp_service as _pp_mod
from app.services import pve_challenge_service as _pve_mod
from app.services import training_service as _train_mod

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine():
    """Create an in-memory SQLite async engine with all tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(TestBase.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(TestBase.metadata.drop_all)

    await engine.dispose()


async def _mock_get_config(db, key):
    """Return default config section for integration tests."""
    from app.core.default_config import DEFAULT_CONFIG

    # Return the requested section from DEFAULT_CONFIG
    parts = key.split(".")
    node = DEFAULT_CONFIG
    for part in parts:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise KeyError(f"Unknown config key: '{key}'")
    return node


async def _mock_get_submission_count(db, user_id):
    """Return 0 submissions for integration tests (avoids querying pp_records)."""
    return 0


def _apply_model_patches():
    """Apply all model patches and return a list of patch objects.

    Uses start/stop pattern instead of context managers to avoid
    Python's static nesting depth limit.
    """
    patches_list = [
        # Security module uses User for get_current_user
        patch.object(_security_mod, "User", _TestUser),
        patch.object(_eco_mod, "User", _TestUser),
        patch.object(_eco_mod, "TokenTransaction", _TestTokenTransaction),
        patch.object(_auth_mod, "User", _TestUser),
        patch.object(_chal_mod, "User", _TestUser),
        patch.object(_chal_mod, "ChallengeSession", _TestChallengeSession),
        patch.object(_train_mod, "User", _TestUser),
        patch.object(_train_mod, "TopicCategory", _TestTopicCategory),
        patch.object(_train_mod, "TrainingSession", _TestTrainingSession),
        patch.object(_train_mod, "TrainingProblemRecord", _TestTrainingProblemRecord),
        patch.object(_train_mod, "EloHistory", _TestEloHistory),
        patch.object(_train_mod, "TokenTransaction", _TestTokenTransaction),
        patch.object(_contest_mod, "User", _TestUser),
        patch.object(_contest_mod, "ContestSession", _TestContestSession),
        patch.object(_contest_mod, "ContestProblemRecord", _TestContestProblemRecord),
        patch.object(_contest_mod, "EloHistory", _TestEloHistory),
        patch.object(_hint_mod, "User", _TestUser),
        patch.object(_hint_mod, "HintPurchase", _TestHintPurchase),
        patch.object(_hint_mod.HintService, "get_max_hint_level", AsyncMock(return_value=0)),
        patch.object(_elo_mod, "EloHistory", _TestEloHistory),
        patch.object(_pp_mod, "User", _TestUser),
        patch.object(_pp_mod, "PPRecord", _TestPPRecord),
        patch.object(_admin_mod, "User", _TestUser),
        patch.object(_admin_mod, "ChallengeSession", _TestChallengeSession),
        patch.object(_admin_mod, "ContestSession", _TestContestSession),
        patch.object(_admin_mod, "TrainingSession", _TestTrainingSession),
        patch.object(_config_mod, "SystemConfig", _TestSystemConfig),
        # Patch ConfigService and EloService for K-factor segmentation
        patch.object(ConfigService, "get_config", _mock_get_config),
        patch.object(EloService, "get_submission_count", _mock_get_submission_count),
        # Patch ContestSimulationService to avoid DB operations on contest_bots table
        patch.object(_sim_mod.ContestSimulationService, "generate_bots", AsyncMock(return_value=[])),
        patch.object(_sim_mod.ContestSimulationService, "stop_simulation", AsyncMock(return_value=False)),
        patch.object(_sim_mod.ContestSimulationService, "calculate_performance_rating", AsyncMock(return_value=1200)),
        patch.object(_sim_mod.ContestSimulationService, "build_leaderboard", AsyncMock(return_value=None)),
        # Patch MEloService to avoid querying user_tag_elo table (UUID type incompatible with SQLite)
        patch.object(_melo_mod.MEloService, "is_shield_active", AsyncMock(return_value=False)),
        patch.object(_melo_mod.MEloService, "deactivate_shield", AsyncMock(return_value=None)),
        patch.object(_melo_mod.MEloService, "get_or_create_melo", AsyncMock(
            return_value=type("FakeMelo", (), {"elo": 1200, "first_ac_at": None})()
        )),
        patch.object(_melo_mod.MEloService, "update_melo", AsyncMock(return_value=None)),
        patch.object(_melo_mod.MEloService, "get_all_melos", AsyncMock(return_value=[])),
    ]
    for p in patches_list:
        p.start()
    return patches_list


def _stop_model_patches(patches_list):
    """Stop all model patches."""
    for p in patches_list:
        p.stop()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Provide an async database session with all model patches applied.

    Patches all service modules to use SQLite-compatible test models instead
    of the PostgreSQL-specific production models.
    """
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    active_patches = _apply_model_patches()

    async with session_factory() as session:
        yield session
        await session.rollback()

    _stop_model_patches(active_patches)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


async def create_test_user(
    db: AsyncSession,
    username: str = "testuser",
    email: str = "test@example.com",
    password: str = "TestPass123",
    elo: int = 1200,
    tokens: int = 0,
    is_admin: bool = False,
    is_active: bool = True,
) -> _TestUser:
    """Create a test user directly in the database."""
    user = _TestUser(
        username=username,
        email=email,
        password_hash=hash_password(password),
        elo=elo,
        pp=0.0,
        tokens=tokens,
        daily_tokens_earned=0,
        is_active=is_active,
        is_admin=is_admin,
    )
    db.add(user)
    await db.flush()
    return user


async def create_test_topic(
    db: AsyncSession,
    name: str = "Dynamic Programming",
    slug: str = "dp",
    cf_tags: list[str] | None = None,
    description: str = "DP problems",
    display_order: int = 0,
) -> _TestTopicCategory:
    """Create a test topic directly in the database."""
    topic = _TestTopicCategory(
        name=name,
        slug=slug,
        description=description,
        cf_tags=cf_tags or ["dp"],
        display_order=display_order,
    )
    db.add(topic)
    await db.flush()
    return topic


def get_auth_headers(user_id: str | uuid.UUID) -> dict[str, str]:
    """Return authorization headers with a valid access token for the user."""
    token = create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


def make_cf_problems_response(
    count: int = 10,
    base_rating: int = 1000,
    tags: list[str] | None = None,
) -> dict:
    """Create a mock CF API problemset.problems response."""
    problems = []
    for i in range(count):
        contest_id = 1000 + i
        index = chr(ord("A") + (i % 6))
        rating = base_rating + (i * 100)
        problems.append({
            "contestId": contest_id,
            "index": index,
            "name": f"Test Problem {i}",
            "rating": rating,
            "tags": tags or ["dp", "math"],
        })
    return {"status": "OK", "result": {"problems": problems}}


def mock_cf_service(
    problems_data: dict | None = None,
):
    """Return a mock CFApiService that returns predefined problem data."""
    if problems_data is None:
        problems_data = make_cf_problems_response()

    mock = AsyncMock()
    mock.get_problemset_problems = AsyncMock(return_value=problems_data["result"])
    mock.get_user_info = AsyncMock(return_value=[{
        "handle": "testcf",
        "rating": 1500,
    }])
    mock.get_user_status = AsyncMock(return_value=[])
    mock.close = AsyncMock()
    return mock
