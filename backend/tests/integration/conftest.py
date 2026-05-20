"""Shared fixtures for end-to-end integration tests.

Provides:
- Real PostgreSQL via testcontainers (session-scoped container + migrations)
- Async engine and session with TRUNCATE-based cleanup between tests
- Patched service modules for Redis, config, Elo, MElo, ContestSimulation
- Helper factories for common entities (users, topics, etc.)
- CF API mock helper
"""

import uuid
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.models.topic_category import TopicCategory
from app.models.user import User
from app.services.config_service import ConfigService
from app.services.elo_service import EloService

# ---------------------------------------------------------------------------
# Skip entire module if Docker / testcontainers is not available
# ---------------------------------------------------------------------------
pytest.importorskip("testcontainers")

# ---------------------------------------------------------------------------
# Module references for service patching
# ---------------------------------------------------------------------------
from app.services import challenge_service as _chal_mod
from app.services import contest_simulation_service as _sim_mod
from app.services import match_service as _match_mod
from app.services import melo_service as _melo_mod

# ---------------------------------------------------------------------------
# Session-scoped fixtures: PostgreSQL container, URL, migrations
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_container():
    """Start a PostgreSQL 16-alpine container for the test session."""
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("postgres:16-alpine")
    container.start()
    yield container
    container.stop()


@pytest.fixture(scope="session")
def postgres_url(postgres_container):
    """Build an asyncpg-compatible connection URL from the container."""
    # PostgresContainer gives us a URL like one of:
    #   postgresql://test:test@localhost:54321/test           (older versions)
    #   postgresql+psycopg2://test:test@localhost:54321/test  (newer versions)
    # We need asyncpg: postgresql+asyncpg://...
    raw = postgres_container.get_connection_url()
    # Strip any existing driver, then add asyncpg
    if "+asyncpg://" in raw:
        return raw
    scheme_end = raw.index("://")
    return "postgresql+asyncpg://" + raw[scheme_end + 3:]


@pytest.fixture(scope="session")
def _run_migrations(postgres_url):
    """Run Alembic migrations against the test PostgreSQL container.

    The migration env.py uses async_engine_from_config which requires an async
    driver, so we keep the +asyncpg URL as-is.

    Two issues must be handled:
    1. env.py overrides sqlalchemy.url with settings.DATABASE_URL, so we must
       patch settings to use the testcontainer URL.
    2. The testcontainer PG does not support SSL, but asyncpg 0.31 defaults
       ssl='prefer' for TCP connections.  We patch asyncpg.connect to inject
       ssl=None so the migration engine can connect.
    """
    import asyncpg as _asyncpg
    from unittest.mock import patch as _patch

    _orig_connect = _asyncpg.connect

    async def _patched_connect(*args, **kwargs):
        kwargs.setdefault("ssl", None)
        return await _orig_connect(*args, **kwargs)

    # Patch settings.DATABASE_URL so env.py's config.set_main_option uses the
    # testcontainer URL instead of the production default.
    from app.core import config as _config_mod

    with (
        _patch.object(_config_mod.settings, "DATABASE_URL", postgres_url),
        _patch.object(_asyncpg, "connect", _patched_connect),
    ):
        from alembic import command
        from alembic.config import Config as AlembicConfig

        alembic_cfg = AlembicConfig()
        alembic_cfg.set_main_option("script_location", "migrations")
        alembic_cfg.set_main_option("sqlalchemy.url", postgres_url)
        command.upgrade(alembic_cfg, "head")


# ---------------------------------------------------------------------------
# Test-scoped fixtures: engine and session
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine(postgres_url, _run_migrations):
    """Create an async engine connected to the real PostgreSQL test container."""
    engine = create_async_engine(
        postgres_url,
        echo=False,
        pool_size=5,
        max_overflow=0,
        connect_args={"ssl": None},  # testcontainers PG does not support SSL
    )
    yield engine
    await engine.dispose()


# Table names in dependency order for TRUNCATE CASCADE.
# Leaf tables (those referencing others via FK) come first so that CASCADE
# can propagate cleanly; root tables (users, topic_categories) come last.
_TRUNCATE_TABLES = [
    "submission_tracking",
    "hint_purchases",
    "token_transactions",
    "training_problem_records",
    "training_sessions",
    "contest_problem_records",
    "contest_sessions",
    "contest_bots",
    "challenge_sessions",
    "pve_challenge_sessions",
    "pp_records",
    "elo_history",
    "user_tag_elo",
    "system_config",
    "users",
    "topic_categories",
]


async def _mock_get_config(db, key):
    """Return default config section for integration tests."""
    from app.core.default_config import DEFAULT_CONFIG

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


@pytest_asyncio.fixture
async def db_session(db_engine, fake_redis):
    """Provide an async database session with service patches applied.

    After the test completes, all tables are TRUNCATEd to leave a clean
    database for the next test.  Only lightweight service patches are applied
    (Redis, config, Elo submission count, MElo, ContestSimulation) -- no
    model patches are needed because we use the real PostgreSQL schema.
    """
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    patches_list = [
        # Redis patches: point match_service and challenge_service at fakeredis
        patch.object(_match_mod, "get_redis", return_value=fake_redis),
        patch.object(_chal_mod, "get_redis", return_value=fake_redis),
        # ConfigService: return DEFAULT_CONFIG without hitting DB
        patch.object(ConfigService, "get_config", _mock_get_config),
        # EloService: skip submission-count query
        patch.object(EloService, "get_submission_count", _mock_get_submission_count),
        # ContestSimulationService: avoid bot-generation logic
        patch.object(_sim_mod.ContestSimulationService, "generate_bots", AsyncMock(return_value=[])),
        patch.object(_sim_mod.ContestSimulationService, "stop_simulation", AsyncMock(return_value=False)),
        patch.object(
            _sim_mod.ContestSimulationService,
            "calculate_performance_rating",
            AsyncMock(return_value=1200),
        ),
        patch.object(_sim_mod.ContestSimulationService, "build_leaderboard", AsyncMock(return_value=None)),
        # MEloService: avoid querying user_tag_elo table
        patch.object(_melo_mod.MEloService, "is_shield_active", AsyncMock(return_value=False)),
        patch.object(_melo_mod.MEloService, "deactivate_shield", AsyncMock(return_value=None)),
        patch.object(
            _melo_mod.MEloService,
            "get_or_create_melo",
            AsyncMock(return_value=type("FakeMelo", (), {"elo": 1200, "first_ac_at": None})()),
        ),
        patch.object(_melo_mod.MEloService, "update_melo", AsyncMock(return_value=None)),
        patch.object(_melo_mod.MEloService, "get_all_melos", AsyncMock(return_value=[])),
    ]

    for p in patches_list:
        p.start()

    async with session_factory() as session:
        yield session
        await session.rollback()

    # Cleanup: TRUNCATE all tables for a clean slate
    async with db_engine.begin() as conn:
        for table in _TRUNCATE_TABLES:
            await conn.execute(text(f'TRUNCATE TABLE "{table}" CASCADE'))

    for p in patches_list:
        p.stop()


# ---------------------------------------------------------------------------
# Other fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fake_redis():
    """Provide a shared fakeredis instance for integration tests."""
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield redis
    await redis.aclose()


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
) -> User:
    """Create a test user directly in the database."""
    user = User(
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
) -> TopicCategory:
    """Create a test topic directly in the database."""
    topic = TopicCategory(
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
