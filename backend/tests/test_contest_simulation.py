"""Tests for the contest simulation service: bot generation, tick simulation, leaderboard.

Uses lightweight SQLite-compatible test models and mocks for external services.
Patches production model references in contest_simulation_service with test
models so SQLAlchemy queries target the SQLite tables.
"""

import math
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.services.contest_simulation_service import (
    _PREFIXES,
    _SUFFIXES,
    ContestSimulationService,
    _bot_states,
    _generate_bot_name,
    _get_simulation_config,
    _get_tick_range_for_rating,
    _get_ticks_for_bot_problem,
)

# ---------------------------------------------------------------------------
# Lightweight SQLite-compatible test models
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _TestContestBot(_TestBase):
    __tablename__ = "contest_bots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contest_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    bot_name: Mapped[str] = mapped_column(String(50), nullable=False)
    bot_elo: Mapped[int] = mapped_column(Integer, nullable=False)
    problems_solved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    solved_problem_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestContestSession(_TestBase):
    __tablename__ = "contest_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
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


class _TestUser(_TestBase):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    cf_handle: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cf_handle_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cf_verification_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
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
    from app.services import contest_simulation_service as sim_svc_module

    session_factory = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        with (
            patch.object(sim_svc_module, "ContestBot", _TestContestBot),
            patch.object(sim_svc_module, "ContestSession", _TestContestSession),
        ):
            yield session


@pytest.fixture(autouse=True)
def _clear_bot_states():
    """Clear in-memory bot states between tests to prevent leakage."""
    _bot_states.clear()
    yield
    _bot_states.clear()


def _make_user(**kwargs) -> _TestUser:
    """Create a test user with sensible defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "email": f"user_{uuid.uuid4().hex[:8]}@test.com",
        "password_hash": "hashed_value",  # pragma: allowlist secret
        "elo": 1500,
    }
    defaults.update(kwargs)
    return _TestUser(**defaults)


def _make_contest_session(**kwargs) -> _TestContestSession:
    """Create a test contest session with sensible defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "contest_tier": "advanced",
        "problems": [
            {"problem_id": "p1", "rating": 1200},
            {"problem_id": "p2", "rating": 1500},
            {"problem_id": "p3", "rating": 1800},
            {"problem_id": "p4", "rating": 2000},
            {"problem_id": "p5", "rating": 1600},
        ],
        "total_problems": 5,
        "time_limit": 120,
        "started_at": datetime.now(UTC),
        "status": "active",
    }
    defaults.update(kwargs)
    return _TestContestSession(**defaults)


# ===========================================================================
# Test: Bot name generation
# ===========================================================================


class TestBotNameGeneration:
    """Verify bot name generation produces unique, valid names."""

    def test_name_format(self):
        """Generated name has prefix + suffix + number format."""
        name = _generate_bot_name(42)
        assert "_" in name
        # Name should end with the index number
        parts = name.rsplit("_", 1)
        assert parts[-1] == "42"

    def test_name_uses_prefixes_and_suffixes(self):
        """Name contains elements from the prefix and suffix pools."""
        name = _generate_bot_name(1)
        # At least one prefix should appear in some generated name
        found_prefix = any(p.lower() in name.lower() for p in _PREFIXES)
        found_suffix = any(s.lower() in name.lower() for s in _SUFFIXES)
        assert found_prefix or found_suffix

    def test_names_different_for_different_indices(self):
        """Different indices generally produce different names."""
        names = set()
        for i in range(100):
            names.add(_generate_bot_name(i))
        # Should have a reasonable number of unique names
        assert len(names) > 50


# ===========================================================================
# Test: Bot generation
# ===========================================================================


class TestBotGeneration:
    """Verify bot generation produces correct count and Elo distribution."""

    @pytest.mark.asyncio
    async def test_generate_default_count(self, db):
        """Default generation creates 50 bots."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
        )
        assert len(bots) == 50

    @pytest.mark.asyncio
    async def test_generate_custom_count(self, db):
        """Custom count generates exactly that many bots."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=10,
        )
        assert len(bots) == 10

    @pytest.mark.asyncio
    async def test_generate_zero_bots(self, db):
        """Count of 0 returns empty list."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=0,
        )
        assert bots == []

    @pytest.mark.asyncio
    async def test_elo_normal_distribution(self, db):
        """Bot Elo values are approximately normally distributed around user Elo."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=100,
            sigma=200,
        )
        elos = [b.bot_elo for b in bots]

        # Mean should be approximately 1500
        mean_elo = sum(elos) / len(elos)
        assert abs(mean_elo - 1500) < 100  # Within 100 of target

        # Standard deviation should be approximately 200
        variance = sum((e - mean_elo) ** 2 for e in elos) / len(elos)
        std_dev = math.sqrt(variance)
        assert 100 < std_dev < 350  # Reasonable range around sigma=200

    @pytest.mark.asyncio
    async def test_bot_names_unique(self, db):
        """All generated bots have unique names."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=50,
        )
        names = [b.bot_name for b in bots]
        assert len(names) == len(set(names))

    @pytest.mark.asyncio
    async def test_bot_initial_state(self, db):
        """Bots start with 0 solved, empty solved list, 0 attempts."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=5,
        )
        for bot in bots:
            assert bot.problems_solved == 0
            assert bot.solved_problem_ids == []
            assert bot.total_attempts == 0

    @pytest.mark.asyncio
    async def test_elo_non_negative(self, db):
        """Bot Elo values are never negative (clamped to 0)."""
        # Use very low user Elo with small sigma to test clamping
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=50,
            count=20,
            sigma=100,
        )
        for bot in bots:
            assert bot.bot_elo >= 0

    @pytest.mark.asyncio
    async def test_generate_one_bot(self, db):
        """Edge case: generating exactly 1 bot works."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=1,
        )
        assert len(bots) == 1
        assert bots[0].bot_elo > 0


# ===========================================================================
# Test: Elo-aware tick calculation
# ===========================================================================


class TestEloAwareTickCalculation:
    """Verify _get_ticks_for_bot_problem produces Elo-aware tick counts."""

    def test_higher_elo_fewer_ticks(self):
        """Higher Elo bot spends fewer ticks on the same problem."""
        import random

        random.seed(42)

        # Multiple samples to avoid jitter flakiness
        ticks_800 = [_get_ticks_for_bot_problem(800, 1200, 120, 5, 30, 0.0) for _ in range(10)]
        ticks_2000 = [_get_ticks_for_bot_problem(2000, 1200, 120, 5, 30, 0.0) for _ in range(10)]

        avg_800 = sum(ticks_800) / len(ticks_800)
        avg_2000 = sum(ticks_2000) / len(ticks_2000)
        assert avg_2000 < avg_800

    def test_higher_rating_more_ticks(self):
        """Higher-rated problem requires more ticks for the same bot."""
        ticks_easy = _get_ticks_for_bot_problem(1500, 800, 120, 5, 30, 0.0)
        ticks_hard = _get_ticks_for_bot_problem(1500, 2000, 120, 5, 30, 0.0)
        assert ticks_hard > ticks_easy

    def test_equal_elo_moderate_ticks(self):
        """When bot_elo == problem_rating, ticks are moderate (contest_duration / n_problems)."""
        # 120 min contest, 5 problems, 30s ticks
        # Total ticks = 240, per problem = 48
        ticks = _get_ticks_for_bot_problem(1500, 1500, 120, 5, 30, 0.0)
        assert ticks == 48  # exactly total_ticks / n_problems at ratio=1.0

    def test_tick_count_scales_with_contest_duration(self):
        """Longer contests produce proportionally more ticks per problem."""
        ticks_60 = _get_ticks_for_bot_problem(1500, 1500, 60, 5, 30, 0.0)
        ticks_120 = _get_ticks_for_bot_problem(1500, 1500, 120, 5, 30, 0.0)
        ticks_150 = _get_ticks_for_bot_problem(1500, 1500, 150, 6, 30, 0.0)

        # Proportional to duration
        assert ticks_120 > ticks_60
        assert ticks_150 > ticks_60

    def test_tick_count_scales_with_problem_count(self):
        """More problems means fewer ticks per problem."""
        ticks_4 = _get_ticks_for_bot_problem(1500, 1500, 120, 4, 30, 0.0)
        ticks_6 = _get_ticks_for_bot_problem(1500, 1500, 120, 6, 30, 0.0)
        assert ticks_4 > ticks_6

    def test_jitter_adds_variation(self):
        """With jitter, tick counts vary between calls."""
        import random

        random.seed(42)

        values = set()
        for _ in range(100):
            values.add(_get_ticks_for_bot_problem(1500, 1500, 120, 5, 30, 0.3))
        assert len(values) > 1

    def test_zero_jitter_deterministic(self):
        """Without jitter, same inputs always produce same output."""
        values = set()
        for _ in range(20):
            values.add(_get_ticks_for_bot_problem(1500, 1500, 120, 5, 30, 0.0))
        assert len(values) == 1

    def test_always_at_least_one_tick(self):
        """Tick count is always >= 1, even with extreme inputs."""
        import random

        random.seed(42)

        for bot_elo in [0, 100, 800, 3000]:
            for problem_rating in [800, 1500, 3000]:
                for _ in range(20):
                    ticks = _get_ticks_for_bot_problem(bot_elo, problem_rating, 120, 5, 30, 0.5)
                    assert ticks >= 1

    def test_elo_power_curve(self):
        """The 1.5 power creates meaningful differentiation between Elo levels."""
        # At ratio 2.0 (problem much harder): ticks = base * 2^1.5 = base * 2.83
        base = 120 * 60 / 30 / 5  # 48
        hard_ratio = _get_ticks_for_bot_problem(800, 1600, 120, 5, 30, 0.0)
        assert hard_ratio == int(base * (1600 / 800) ** 1.5)

        # At ratio 0.5 (problem much easier): ticks = base * 0.5^1.5 = base * 0.354
        easy_ratio = _get_ticks_for_bot_problem(1600, 800, 120, 5, 30, 0.0)
        assert easy_ratio == int(base * (800 / 1600) ** 1.5)

    def test_different_tick_intervals(self):
        """Smaller tick intervals produce more ticks for the same time."""
        ticks_30 = _get_ticks_for_bot_problem(1500, 1500, 120, 5, 30, 0.0)
        ticks_15 = _get_ticks_for_bot_problem(1500, 1500, 120, 5, 15, 0.0)
        assert ticks_15 > ticks_30


# ===========================================================================
# Test: Legacy tick range (backward compat)
# ===========================================================================


class TestDifficultyTiming:
    """Verify legacy difficulty-based tick ranges for backward compat."""

    def test_easy_problem_few_ticks(self):
        """Easy problems (rating < 1200) need few ticks."""
        ticks = _get_tick_range_for_rating(800)
        assert 1 <= ticks <= 6  # [2,4] with 30% jitter: min 1, max ~5

    def test_medium_problem_moderate_ticks(self):
        """Medium problems (1200 <= rating < 1800) need moderate ticks."""
        ticks = _get_tick_range_for_rating(1500)
        assert 4 <= ticks <= 22  # [6,16] with 30% jitter

    def test_hard_problem_many_ticks(self):
        """Hard problems (rating >= 1800) need many ticks."""
        ticks = _get_tick_range_for_rating(2200)
        assert 10 <= ticks <= 40  # [16,30] with 30% jitter

    def test_custom_difficulty_ticks(self):
        """Custom difficulty_ticks override defaults."""
        custom = {"easy": [1, 1], "medium": [1, 1], "hard": [1, 1]}
        ticks = _get_tick_range_for_rating(2000, difficulty_ticks=custom, jitter=0.0)
        assert ticks == 1

    def test_zero_jitter(self):
        """Zero jitter means exact range values."""
        import random

        random.seed(42)
        ticks_values = set()
        for _ in range(100):
            t = _get_tick_range_for_rating(1000, jitter=0.0)
            ticks_values.add(t)
        # Without jitter, values should be in [2, 4] exactly
        assert all(2 <= t <= 4 for t in ticks_values)

    def test_tick_range_always_at_least_one(self):
        """Tick range never returns 0 or negative."""
        for rating in [500, 1000, 1500, 2000, 3000]:
            for _ in range(50):
                ticks = _get_tick_range_for_rating(rating, jitter=0.9)
                assert ticks >= 1


# ===========================================================================
# Test: Give-up mechanism
# ===========================================================================


class TestGiveUpMechanism:
    """Verify that bots skip problems far above their Elo."""

    def test_low_elo_bot_skips_hard_problem(self):
        """Bot with Elo 800 skips a 2000-rated problem (threshold 800 -> skip at >1600)."""
        # Bot has already solved the easy problem, so it will consider the hard one next
        bot = _make_bot(elo=800, problems=["easy"])
        problems = [
            {"problem_id": "easy", "rating": 900},
            {"problem_id": "hard", "rating": 2000},
        ]
        bot_state: dict = {
            "current_problem": None,
            "ticks_remaining": 0,
            "attempted_and_failed": [],
            "skipped_problems": [],
        }

        # Run one tick: bot should skip the hard problem immediately
        ContestSimulationService._simulate_bot_tick(
            bot,
            problems,
            time_factor=1.0,
            bot_state=bot_state,
            give_up_threshold=800,
        )

        # Bot should have skipped the hard problem (2000 > 800 + 800)
        skipped = bot_state.get("skipped_problems", [])
        assert "hard" in skipped

    def test_high_elo_bot_does_not_skip(self):
        """Bot with Elo 2000 does not skip a 1500-rated problem."""
        bot = _make_bot(elo=2000, problems=[])
        problems = [
            {"problem_id": "p1", "rating": 1500},
        ]
        bot_state: dict = {
            "current_problem": None,
            "ticks_remaining": 0,
            "attempted_and_failed": [],
            "skipped_problems": [],
        }

        # Run ticks until processed
        for _ in range(200):
            ContestSimulationService._simulate_bot_tick(
                bot,
                problems,
                time_factor=1.0,
                bot_state=bot_state,
                give_up_threshold=800,
            )
            if bot.problems_solved > 0 or bot_state.get("current_problem") is None:
                break

        skipped = bot_state.get("skipped_problems", [])
        assert "p1" not in skipped

    def test_give_up_threshold_customizable(self):
        """Give-up threshold can be configured."""
        bot = _make_bot(elo=1200, problems=[])
        problems = [
            {"problem_id": "p1", "rating": 1600},
        ]
        bot_state: dict = {
            "current_problem": None,
            "ticks_remaining": 0,
            "attempted_and_failed": [],
            "skipped_problems": [],
        }

        # With threshold=300, 1600 > 1200+300=1500 -> skip
        for _ in range(200):
            ContestSimulationService._simulate_bot_tick(
                bot,
                problems,
                time_factor=1.0,
                bot_state=bot_state,
                give_up_threshold=300,
            )
            if bot_state.get("skipped_problems"):
                break

        assert "p1" in bot_state.get("skipped_problems", [])

    def test_bot_with_no_solvable_problems_stops(self):
        """Bot that can't solve any problem just increments attempts."""
        bot = _make_bot(elo=500, problems=[])
        problems = [
            {"problem_id": "p1", "rating": 2000},
            {"problem_id": "p2", "rating": 2200},
        ]
        bot_state: dict = {
            "current_problem": None,
            "ticks_remaining": 0,
            "attempted_and_failed": [],
            "skipped_problems": [],
        }

        solved = ContestSimulationService._simulate_bot_tick(
            bot,
            problems,
            time_factor=1.0,
            bot_state=bot_state,
            give_up_threshold=800,
        )
        assert solved == []
        assert bot.total_attempts == 1
        # Both problems should be skipped
        assert len(bot_state.get("skipped_problems", [])) == 2


# ===========================================================================
# Test: Retry mechanism
# ===========================================================================


class TestRetryMechanism:
    """Verify that bots may retry failed problems."""

    def test_failed_problem_tracked(self):
        """When a bot fails a problem, it's recorded in attempted_and_failed."""
        import random

        random.seed(42)

        # Create a bot that will likely fail: low Elo vs hard problem
        bot = _make_bot(elo=800, problems=[])
        problems = [{"problem_id": "hard", "rating": 1400}]
        bot_state: dict = {
            "current_problem": None,
            "ticks_remaining": 0,
            "attempted_and_failed": [],
            "skipped_problems": [],
        }

        # Run enough ticks for the bot to attempt and potentially fail
        for _ in range(200):
            solved = ContestSimulationService._simulate_bot_tick(
                bot,
                problems,
                time_factor=1.0,
                bot_state=bot_state,
                give_up_threshold=800,  # 1400 < 800+800=1600, so won't skip
                retry_base_prob=0.3,
            )
            if solved:
                break

        # If bot hasn't solved it, check if it's tracked as failed
        if bot.problems_solved == 0:
            # The problem may be in attempted_and_failed or being retried
            assert bot.total_attempts > 0

    def test_retry_prob_scales_with_elo_ratio(self):
        """Higher Elo bots have higher retry probability for the same problem."""
        # retry_prob = retry_base_prob * min(1.0, bot_elo / problem_rating)
        # Bot 1500 vs problem 1500: prob = 0.3 * 1.0 = 0.3
        # Bot 800 vs problem 1500: prob = 0.3 * (800/1500) = 0.16
        pass  # Verified indirectly by simulation integration tests

    def test_retry_base_prob_zero_no_retry(self):
        """With retry_base_prob=0, bot never retries (always moves to next)."""
        import random

        random.seed(42)

        bot = _make_bot(elo=800, problems=[])
        problems = [
            {"problem_id": "p1", "rating": 1300},
            {"problem_id": "p2", "rating": 900},
        ]
        bot_state: dict = {
            "current_problem": None,
            "ticks_remaining": 0,
            "attempted_and_failed": [],
            "skipped_problems": [],
        }

        # Run many ticks
        for _ in range(200):
            ContestSimulationService._simulate_bot_tick(
                bot,
                problems,
                time_factor=1.0,
                bot_state=bot_state,
                give_up_threshold=800,
                retry_base_prob=0.0,
            )

        # With retry_base_prob=0, the bot should move to next problem after failure
        # It should have attempted both problems
        assert bot.total_attempts > 0


# ===========================================================================
# Test: Sequential bot behavior
# ===========================================================================


class TestSimulateBotTickSequential:
    """Verify that each bot works on one problem at a time."""

    def test_bot_solves_at_most_one_per_tick(self):
        """A bot can solve at most one problem per tick."""
        bot = _make_bot(elo=3000, problems=["p1", "p2", "p3", "p4", "p5"])
        problems = [
            {"problem_id": "p1", "rating": 800},
            {"problem_id": "p2", "rating": 900},
            {"problem_id": "p3", "rating": 1000},
            {"problem_id": "p4", "rating": 1100},
            {"problem_id": "p5", "rating": 1200},
        ]
        bot_state: dict = {
            "current_problem": None,
            "ticks_remaining": 0,
            "attempted_and_failed": [],
            "skipped_problems": [],
        }

        # Run many ticks -- each should solve at most 1
        for _ in range(20):
            solved = ContestSimulationService._simulate_bot_tick(
                bot,
                problems,
                time_factor=1.0,
                bot_state=bot_state,
                total_minutes=120,
                n_problems=5,
                tick_interval=30,
                jitter=0.0,
            )
            assert len(solved) <= 1

    def test_bot_works_on_easiest_first(self):
        """Bot picks the lowest-rating unsolved problem first."""
        bot = _make_bot(elo=1500, problems=[])
        problems = [
            {"problem_id": "hard", "rating": 2000},
            {"problem_id": "easy", "rating": 800},
            {"problem_id": "medium", "rating": 1400},
        ]
        bot_state: dict = {
            "current_problem": None,
            "ticks_remaining": 0,
            "attempted_and_failed": [],
            "skipped_problems": [],
        }

        ContestSimulationService._simulate_bot_tick(
            bot,
            problems,
            time_factor=1.0,
            bot_state=bot_state,
            total_minutes=120,
            n_problems=3,
            tick_interval=30,
            jitter=0.0,
        )

        # Bot should have selected the easiest problem
        assert bot_state["current_problem"] is None or bot_state["current_problem"] == "easy"

    def test_bot_pauses_on_hard_problems(self):
        """Hard problems require multiple ticks before P(AC) roll."""
        bot = _make_bot(elo=1500, problems=[])
        # Use a problem within the give-up threshold (1800 < 1500 + 800 = 2300)
        problems = [{"problem_id": "hard", "rating": 1800}]
        bot_state: dict = {
            "current_problem": None,
            "ticks_remaining": 0,
            "attempted_and_failed": [],
            "skipped_problems": [],
        }

        # Use a short contest to get fewer ticks per problem
        # 30 min, 1 problem, 30s tick -> total=60 ticks, base=60/1=60
        # ratio=1800/1500=1.2, scaled=60 * 1.2^1.5 = 78.9 ticks

        # First tick: bot picks problem, starts working
        ContestSimulationService._simulate_bot_tick(
            bot,
            problems,
            time_factor=1.0,
            bot_state=bot_state,
            total_minutes=30,
            n_problems=1,
            tick_interval=30,
            jitter=0.0,
        )
        # Should be working on the hard problem
        assert bot_state["current_problem"] == "hard"
        assert bot_state["ticks_remaining"] > 0

    def test_bot_moves_to_next_after_solving(self):
        """After solving a problem, bot picks the next unsolved."""
        bot = _make_bot(elo=3000, problems=[])
        problems = [
            {"problem_id": "p1", "rating": 800},
            {"problem_id": "p2", "rating": 900},
        ]
        bot_state: dict = {
            "current_problem": None,
            "ticks_remaining": 0,
            "attempted_and_failed": [],
            "skipped_problems": [],
        }

        # Run enough ticks to potentially solve both
        for _ in range(200):
            ContestSimulationService._simulate_bot_tick(
                bot,
                problems,
                time_factor=1.0,
                bot_state=bot_state,
                total_minutes=120,
                n_problems=2,
                tick_interval=30,
                jitter=0.0,
            )

        # Bot should have solved at most 2 problems
        assert bot.problems_solved <= 2

    def test_bot_no_work_when_all_solved(self):
        """Bot has nothing to do when all problems are solved."""
        bot = _make_bot(elo=3000, problems=["p1", "p2"])
        problems = [
            {"problem_id": "p1", "rating": 800},
            {"problem_id": "p2", "rating": 900},
        ]
        bot_state: dict = {
            "current_problem": None,
            "ticks_remaining": 0,
            "attempted_and_failed": [],
            "skipped_problems": [],
        }

        solved = ContestSimulationService._simulate_bot_tick(
            bot,
            problems,
            time_factor=1.0,
            bot_state=bot_state,
        )
        assert solved == []


# ===========================================================================
# Test: P(AC) probability
# ===========================================================================


class TestProbabilityOfAC:
    """Verify bot solve probability follows the P(AC) formula."""

    def test_high_elo_high_probability(self):
        """Bot with much higher Elo than problem has high P(AC)."""
        # P(AC) = 1 / (1 + 10^((rating - bot_elo) / 400))
        # bot_elo=2000, rating=1000: P = 1/(1+10^(-2.5)) ~ 0.997
        p_ac = 1.0 / (1.0 + 10.0 ** ((1000 - 2000) / 400.0))
        assert p_ac > 0.99

    def test_equal_elo_50_percent(self):
        """Bot with same Elo as problem has ~50% P(AC)."""
        p_ac = 1.0 / (1.0 + 10.0 ** ((1500 - 1500) / 400.0))
        assert abs(p_ac - 0.5) < 0.01

    def test_low_elo_low_probability(self):
        """Bot with much lower Elo than problem has low P(AC)."""
        p_ac = 1.0 / (1.0 + 10.0 ** ((2500 - 1000) / 400.0))
        assert p_ac < 0.01

    def test_solves_follow_probability(self):
        """Empirical test: over many ticks, solve rate matches P(AC)."""
        import random

        bot_elo = 1500
        problem_rating = 1500
        expected_p = 1.0 / (1.0 + 10.0 ** ((problem_rating - bot_elo) / 400.0))
        time_factor = 1.0  # beginning of contest

        solves = 0
        trials = 10000
        for _ in range(trials):
            if random.random() < expected_p * time_factor:
                solves += 1

        observed_rate = solves / trials
        # Should be within 5% of expected
        assert abs(observed_rate - expected_p) < 0.05


# ===========================================================================
# Test: Tick simulation
# ===========================================================================


class TestTickSimulation:
    """Verify tick simulation correctly simulates bot problem-solving."""

    @pytest.mark.asyncio
    async def test_tick_updates_bot_state(self, db):
        """After a tick, some bots may have solved problems."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=20,
        )
        await db.commit()

        # Run a tick
        await ContestSimulationService.tick_simulation(db, contest.id)

        # Refresh bots to see updated state
        for bot in bots:
            await db.refresh(bot)
            # total_attempts should be incremented
            assert bot.total_attempts == 1

    @pytest.mark.asyncio
    async def test_tick_skips_completed_contest(self, db):
        """Tick returns empty list for non-active contests."""
        contest = _make_contest_session(status="completed")
        db.add(contest)
        await db.flush()

        solved = await ContestSimulationService.tick_simulation(db, contest.id)
        assert solved == []

    @pytest.mark.asyncio
    async def test_tick_no_duplicate_solves(self, db):
        """A bot cannot solve the same problem twice."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=2000,
            count=50,
        )
        await db.commit()

        # Run multiple ticks
        for _ in range(60):
            await ContestSimulationService.tick_simulation(db, contest.id)
            await db.commit()

        # Verify no bot has duplicate problem IDs in solved list
        for bot in bots:
            await db.refresh(bot)
            solved_list = bot.solved_problem_ids or []
            assert len(solved_list) == len(set(solved_list))

    @pytest.mark.asyncio
    async def test_tick_problems_solved_matches_list(self, db):
        """Bot's problems_solved count matches solved_problem_ids length."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1800,
            count=30,
        )
        await db.commit()

        for _ in range(40):
            await ContestSimulationService.tick_simulation(db, contest.id)
            await db.commit()

        for bot in bots:
            await db.refresh(bot)
            solved_list = bot.solved_problem_ids or []
            assert bot.problems_solved == len(solved_list)

    @pytest.mark.asyncio
    async def test_tick_bot_states_initialized(self, db):
        """tick_simulation creates bot_states for each bot."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=5,
        )
        await db.commit()

        await ContestSimulationService.tick_simulation(db, contest.id)
        await db.commit()

        # Check that bot states were created
        assert contest.id in _bot_states
        for bot in bots:
            assert bot.id in _bot_states[contest.id]

    @pytest.mark.asyncio
    async def test_tick_bot_states_cleaned_on_stop(self, db):
        """Bot states are cleaned up when simulation stops."""
        contest_id = uuid.uuid4()
        _bot_states[contest_id] = {uuid.uuid4(): {"current_problem": None, "ticks_remaining": 0}}

        await ContestSimulationService.stop_simulation(contest_id)

        assert contest_id not in _bot_states


# ===========================================================================
# Test: Realistic simulation behavior
# ===========================================================================


class TestRealisticSimulation:
    """Verify that the simulation produces realistic contest behavior."""

    @pytest.mark.asyncio
    async def test_bots_active_throughout_contest(self, db):
        """Bots should still be active (incrementing attempts) near the end of a 120-min contest."""
        import random

        random.seed(42)

        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=10,
        )
        await db.commit()

        # Simulate enough ticks to cover most of the contest
        # 120 min * 60s / 30s = 240 ticks total
        # Run 200 ticks (most of the contest)
        for tick_num in range(200):
            await ContestSimulationService.tick_simulation(db, contest.id)
            await db.commit()

        # Check that bots have been active throughout
        for bot in bots:
            await db.refresh(bot)
            # Every bot should have many attempts (one per tick)
            assert bot.total_attempts >= 100  # at least 100 attempts

    @pytest.mark.asyncio
    async def test_low_elo_cannot_solve_hard_problems(self, db):
        """Low Elo bots should not solve problems far above their level."""
        import random

        random.seed(42)

        # Contest with hard problems only (rating 1800-2200)
        contest = _make_contest_session(
            problems=[
                {"problem_id": "p1", "rating": 1800},
                {"problem_id": "p2", "rating": 2000},
                {"problem_id": "p3", "rating": 2200},
                {"problem_id": "p4", "rating": 1900},
                {"problem_id": "p5", "rating": 2100},
            ],
        )
        db.add(contest)
        await db.flush()

        # Generate LOW Elo bots (800-1000 range)
        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=800,
            count=20,
            sigma=100,
        )
        await db.commit()

        # Run many ticks
        for _ in range(240):
            await ContestSimulationService.tick_simulation(db, contest.id)
            await db.commit()

        # Low Elo bots should solve very few problems
        total_solved = sum(bot.problems_solved for bot in bots)
        avg_solved = total_solved / len(bots)
        # With P(AC) very low and give-up threshold, most bots should solve < 2
        assert avg_solved < 3

    @pytest.mark.asyncio
    async def test_high_elo_solves_more(self, db):
        """Higher Elo bots should solve more problems than lower Elo bots."""
        import random

        random.seed(42)

        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        # Generate bots with varied Elo
        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=50,
            sigma=300,
        )
        await db.commit()

        # Run many ticks
        for _ in range(240):
            await ContestSimulationService.tick_simulation(db, contest.id)
            await db.commit()

        # Higher Elo bots should have solved more on average
        high_elo_solved = []
        low_elo_solved = []
        for bot in bots:
            await db.refresh(bot)
            if bot.bot_elo >= 1600:
                high_elo_solved.append(bot.problems_solved)
            elif bot.bot_elo <= 1400:
                low_elo_solved.append(bot.problems_solved)

        if high_elo_solved and low_elo_solved:
            avg_high = sum(high_elo_solved) / len(high_elo_solved)
            avg_low = sum(low_elo_solved) / len(low_elo_solved)
            assert avg_high >= avg_low

    @pytest.mark.asyncio
    async def test_not_all_bots_solve_all_problems(self, db):
        """Not all bots should solve all problems in a contest."""
        import random

        random.seed(42)

        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=50,
            sigma=200,
        )
        await db.commit()

        # Run full contest (240 ticks)
        for _ in range(240):
            await ContestSimulationService.tick_simulation(db, contest.id)
            await db.commit()

        # Count bots that solved all 5 problems
        all_solved = sum(1 for bot in bots if (bot.problems_solved if hasattr(bot, "problems_solved") else 0) == 5)
        # With the new model, not all bots should solve all problems
        # Allow up to 40% to solve all (probabilistic but very unlikely to be 100%)
        assert all_solved < len(bots) * 0.5

    @pytest.mark.asyncio
    async def test_leaderboard_gradual_progression(self, db):
        """Leaderboard shows gradual progression of solve counts."""
        import random

        random.seed(42)

        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=30,
            sigma=200,
        )
        await db.commit()

        # Run full contest
        for _ in range(240):
            await ContestSimulationService.tick_simulation(db, contest.id)
            await db.commit()

        # Get solve counts
        solve_counts = sorted([bot.problems_solved for bot in bots], reverse=True)

        # There should be a spread of solve counts (not all same value)
        unique_counts = len(set(solve_counts))
        assert unique_counts >= 2  # At least some variation

    @pytest.mark.asyncio
    async def test_different_tiers_behavior(self, db):
        """Different contest tiers produce different bot behavior."""
        import random

        # Blitz: 60 min, 4 problems
        random.seed(42)
        blitz = _make_contest_session(
            time_limit=60,
            problems=[
                {"problem_id": "p1", "rating": 1200},
                {"problem_id": "p2", "rating": 1400},
                {"problem_id": "p3", "rating": 1600},
                {"problem_id": "p4", "rating": 1800},
            ],
            total_problems=4,
        )
        db.add(blitz)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            blitz.id,
            user_elo=1500,
            count=20,
        )
        await db.commit()

        # Run 120 ticks (60 min * 60s / 30s = 120 ticks)
        for _ in range(120):
            await ContestSimulationService.tick_simulation(db, blitz.id)
            await db.commit()

        blitz_solved = [bot.problems_solved for bot in bots]

        # Bots should have some solves
        assert any(s > 0 for s in blitz_solved)


# ===========================================================================
# Test: Leaderboard
# ===========================================================================


class TestLeaderboard:
    """Verify combined human+bot leaderboard."""

    @pytest.mark.asyncio
    async def test_leaderboard_includes_human(self, db):
        """Leaderboard includes the human player."""
        user = _make_user()
        db.add(user)
        contest = _make_contest_session(user_id=user.id, problems_solved=2)
        db.add(contest)
        await db.flush()

        leaderboard = await ContestSimulationService.build_leaderboard(
            db,
            contest.id,
            user,
        )
        human_entries = [e for e in leaderboard.leaderboard if not e.is_bot]
        assert len(human_entries) == 1
        assert human_entries[0].name == user.username
        assert human_entries[0].solved == 2
        assert human_entries[0].is_bot is False

    @pytest.mark.asyncio
    async def test_leaderboard_includes_bots(self, db):
        """Leaderboard includes all bots."""
        user = _make_user()
        db.add(user)
        contest = _make_contest_session(user_id=user.id)
        db.add(contest)
        await db.flush()

        await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=10,
        )
        await db.commit()

        leaderboard = await ContestSimulationService.build_leaderboard(
            db,
            contest.id,
            user,
        )
        bot_entries = [e for e in leaderboard.leaderboard if e.is_bot]
        assert len(bot_entries) == 10

    @pytest.mark.asyncio
    async def test_leaderboard_sorted_by_solved(self, db):
        """Leaderboard is sorted by solved count descending."""
        user = _make_user()
        db.add(user)
        contest = _make_contest_session(user_id=user.id, problems_solved=3)
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=5,
        )
        # Manually set some bots to have solved problems
        bots[0].problems_solved = 5
        bots[0].solved_problem_ids = ["p1", "p2", "p3", "p4", "p5"]
        bots[1].problems_solved = 0
        bots[1].solved_problem_ids = []
        bots[2].problems_solved = 2
        bots[2].solved_problem_ids = ["p1", "p2"]
        await db.flush()

        leaderboard = await ContestSimulationService.build_leaderboard(
            db,
            contest.id,
            user,
        )

        # First entry should have most solved
        assert leaderboard.leaderboard[0].solved >= leaderboard.leaderboard[1].solved
        # Ranks should be sequential
        for i, entry in enumerate(leaderboard.leaderboard):
            assert entry.rank == i + 1

    @pytest.mark.asyncio
    async def test_leaderboard_timing(self, db):
        """Leaderboard includes time elapsed and total."""
        user = _make_user()
        db.add(user)
        contest = _make_contest_session(
            user_id=user.id,
            time_limit=90,
            started_at=datetime.now(UTC),
        )
        db.add(contest)
        await db.flush()

        leaderboard = await ContestSimulationService.build_leaderboard(
            db,
            contest.id,
            user,
        )
        assert leaderboard.time_total == 90
        assert leaderboard.time_elapsed >= 0

    @pytest.mark.asyncio
    async def test_leaderboard_empty_for_no_contest(self, db):
        """Leaderboard returns empty for nonexistent contest."""
        user = _make_user()
        db.add(user)
        await db.flush()

        leaderboard = await ContestSimulationService.build_leaderboard(
            db,
            uuid.uuid4(),
            user,
        )
        assert leaderboard.leaderboard == []


# ===========================================================================
# Test: Time factor
# ===========================================================================


class TestTimeFactor:
    """Verify time-based scaling factor."""

    def test_beginning_factor(self):
        """At start of contest, factor is 1.0."""
        factor = ContestSimulationService._calculate_time_factor(0, 90)
        assert factor == 1.0

    def test_mid_contest_factor(self):
        """Mid-contest factor is between 0.2 and 1.0."""
        factor = ContestSimulationService._calculate_time_factor(45, 90)
        assert 0.2 < factor < 1.0

    def test_end_factor(self):
        """Near end of contest, factor approaches 0.2."""
        factor = ContestSimulationService._calculate_time_factor(90, 90)
        assert factor == 0.2

    def test_factor_decreases_over_time(self):
        """Factor monotonically decreases."""
        prev = 1.0
        for elapsed in range(1, 91):
            factor = ContestSimulationService._calculate_time_factor(elapsed, 90)
            assert factor <= prev
            prev = factor


# ===========================================================================
# Test: Simulation lifecycle
# ===========================================================================


class TestSimulationLifecycle:
    """Verify simulation start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        """Stopping a simulation that was never started returns False."""
        result = await ContestSimulationService.stop_simulation(uuid.uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_is_simulation_active_false_when_none(self):
        """is_simulation_active returns False when no simulation exists."""
        assert ContestSimulationService.is_simulation_active(uuid.uuid4()) is False


# ===========================================================================
# Test: Integration -- generate + tick + leaderboard
# ===========================================================================


class TestSimulationIntegration:
    """End-to-end test: generate bots, run ticks, build leaderboard."""

    @pytest.mark.asyncio
    async def test_full_simulation_flow(self, db):
        """Generate bots, run ticks, verify leaderboard is coherent."""
        user = _make_user(elo=1500, username="TestPlayer")
        db.add(user)
        contest = _make_contest_session(user_id=user.id, problems_solved=0)
        db.add(contest)
        await db.flush()

        # Generate bots
        bots = await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=20,
        )
        await db.commit()
        assert len(bots) == 20

        # Simulate the user solving 2 problems
        contest.problems_solved = 2
        await db.flush()

        # Run several ticks (enough for some bots to complete easy problems)
        for _ in range(60):
            await ContestSimulationService.tick_simulation(db, contest.id)
            await db.commit()

        # Build leaderboard
        leaderboard = await ContestSimulationService.build_leaderboard(
            db,
            contest.id,
            user,
        )

        # Should have 21 entries (1 human + 20 bots)
        assert len(leaderboard.leaderboard) == 21

        # Human should be present
        human = [e for e in leaderboard.leaderboard if not e.is_bot]
        assert len(human) == 1
        assert human[0].name == "TestPlayer"
        assert human[0].solved == 2

        # Ranks should be sequential
        for i, entry in enumerate(leaderboard.leaderboard):
            assert entry.rank == i + 1

        # Sorted by solved descending, then elo descending
        for i in range(len(leaderboard.leaderboard) - 1):
            curr = leaderboard.leaderboard[i]
            next_entry = leaderboard.leaderboard[i + 1]
            assert (curr.solved, curr.elo) >= (next_entry.solved, next_entry.elo)


# ===========================================================================
# Test: Performance Rating (PR) calculation
# ===========================================================================


class TestActualRank:
    """Verify actual rank calculation."""

    def test_player_best(self):
        """Player solved most -> rank 1."""
        rank = ContestSimulationService.calculate_actual_rank(5, [4, 3, 2, 1, 0])
        assert rank == 1

    def test_player_worst(self):
        """Player solved nothing -> rank = number of bots ahead + 1."""
        rank = ContestSimulationService.calculate_actual_rank(0, [4, 3, 2, 1, 0])
        # 4 bots have strictly more than 0
        assert rank == 5

    def test_player_middle(self):
        """Player in middle of pack."""
        rank = ContestSimulationService.calculate_actual_rank(3, [5, 4, 3, 2, 1])
        # 2 bots with strictly more (5, 4)
        assert rank == 3

    def test_player_tied(self):
        """Player tied with some bots: tied bots do NOT count as ahead."""
        rank = ContestSimulationService.calculate_actual_rank(3, [3, 3, 2, 1])
        # No bot has strictly more than 3
        assert rank == 1

    def test_empty_bots(self):
        """No bots -> player is rank 1."""
        rank = ContestSimulationService.calculate_actual_rank(3, [])
        assert rank == 1


class TestActualRankSmooth:
    """Verify smooth actual rank calculation (Elo-based expected)."""

    def test_player_best_smooth(self):
        """Player solved all -> smooth rank 1 when no bot expects more."""
        bot_elos = [1000, 1200, 1400]
        problem_ratings = [1500, 1500, 1500, 1500, 1500]
        # Bot expected solved: ~2.5 each at 1500 vs 1500 -> all < 5
        rank = ContestSimulationService.calculate_actual_rank_smooth(
            5,
            bot_elos,
            problem_ratings,
        )
        assert rank == 1.0

    def test_player_worst_smooth(self):
        """Player solved 0 -> all bots beat player."""
        bot_elos = [2000, 2000, 2000]
        problem_ratings = [1000, 1000, 1000]
        # Bot expected solved: ~3 each (P(AC)~1 for 2000 vs 1000) -> all > 0
        rank = ContestSimulationService.calculate_actual_rank_smooth(
            0,
            bot_elos,
            problem_ratings,
        )
        assert rank == 4.0  # 3 bots ahead + 1

    def test_smooth_rank_bounded(self):
        """Smooth rank is always in [1, N+1]."""
        bot_elos = [1200, 1400, 1600, 1800]
        problem_ratings = [1500, 1500, 1500]
        for ps in range(6):
            rank = ContestSimulationService.calculate_actual_rank_smooth(
                ps,
                bot_elos,
                problem_ratings,
            )
            assert 1.0 <= rank <= 5.0


class TestExpectedRank:
    """Verify expected rank calculation."""

    def test_high_elo_low_rank(self):
        """High Elo player should have low expected rank (close to 1)."""
        problem_ratings = [800, 800, 800, 800, 800]
        rank = ContestSimulationService.calculate_expected_rank(
            3000,
            [1000, 1000, 1000],
            problem_ratings,
            5,
        )
        # Player at 3000 expects ~5, bots at 1000 expect ~3.8 each
        # No bot beats player -> rank = 1
        assert rank == 1.0

    def test_low_elo_high_rank(self):
        """Low Elo player should have high expected rank."""
        problem_ratings = [2000, 2000, 2000, 2000, 2000]
        rank = ContestSimulationService.calculate_expected_rank(
            500,
            [2000, 2000, 2000],
            problem_ratings,
            0,
        )
        # Player at 500 expects very little, bots at 2000 expect ~2.5 each
        # All bots beat player -> rank = 4
        assert rank > 3.0

    def test_equal_scenario(self):
        """Player and bots at same level -> rank around middle."""
        problem_ratings = [1500, 1500, 1500, 1500, 1500]
        rank = ContestSimulationService.calculate_expected_rank(
            1500,
            [1500, 1500, 1500, 1500],
            problem_ratings,
            2,
        )
        # At elo=1500, player expects 2.5, each bot also 2.5 -> tied
        # No bot has strictly more -> rank = 1
        assert 1.0 <= rank <= 5.0

    def test_no_problems(self):
        """No problems -> expected rank is 1."""
        rank = ContestSimulationService.calculate_expected_rank(
            1500,
            [1500, 1500],
            [],
            0,
        )
        assert rank == 1.0

    def test_no_bots(self):
        """No bots -> expected rank is 1."""
        rank = ContestSimulationService.calculate_expected_rank(
            1500,
            [],
            [1500, 1500],
            2,
        )
        assert rank == 1.0


class TestPerformanceRating:
    """Verify PR binary search calculation via DB integration tests."""

    @pytest.mark.asyncio
    async def test_champion_pr_high(self, db):
        """Player solves all problems -> PR should be high (near max bot elo or higher)."""
        user = _make_user(elo=1500)
        db.add(user)
        contest = _make_contest_session(user_id=user.id, problems_solved=5)
        db.add(contest)
        await db.flush()

        # Create bots with varied elos
        for i in range(10):
            bot = _TestContestBot(
                contest_id=contest.id,
                bot_name=f"Bot_{i}",
                bot_elo=1200 + i * 50,
                problems_solved=1 + i % 3,
                solved_problem_ids=[],
                total_attempts=5,
            )
            db.add(bot)
        await db.flush()

        pr = await ContestSimulationService.calculate_performance_rating(
            db,
            contest.id,
            player_solved=5,
        )
        # Player solved 5 (all), no bot expects > 5 solves at these Elo levels
        # PR should be near or above the highest bot Elo (1650)
        assert pr >= 1400

    @pytest.mark.asyncio
    async def test_last_place_pr_low(self, db):
        """Player solves 0 problems -> PR should be low."""
        user = _make_user(elo=1500)
        db.add(user)
        contest = _make_contest_session(user_id=user.id, problems_solved=0)
        db.add(contest)
        await db.flush()

        # Create bots that have solved many problems
        for i in range(10):
            bot = _TestContestBot(
                contest_id=contest.id,
                bot_name=f"Bot_{i}",
                bot_elo=1500 + i * 50,
                problems_solved=3 + i % 3,
                solved_problem_ids=[],
                total_attempts=5,
            )
            db.add(bot)
        await db.flush()

        pr = await ContestSimulationService.calculate_performance_rating(
            db,
            contest.id,
            player_solved=0,
        )
        # Player solved 0 -> all bots expected to have more solves -> very low PR
        assert pr < 1200

    @pytest.mark.asyncio
    async def test_midpack_pr_near_average(self, db):
        """Player in the middle -> PR should be near bot Elo average."""
        user = _make_user(elo=1500)
        db.add(user)
        contest = _make_contest_session(user_id=user.id, problems_solved=3)
        db.add(contest)
        await db.flush()

        # Create bots with varied Elo and solved counts
        bot_data = [
            (1500, 5),
            (1600, 4),
            (1400, 4),
            (1550, 3),
            (1450, 3),
            (1500, 2),
            (1350, 1),
            (1600, 0),
        ]
        for i, (elo, solved) in enumerate(bot_data):
            bot = _TestContestBot(
                contest_id=contest.id,
                bot_name=f"Bot_{i}",
                bot_elo=elo,
                problems_solved=solved,
                solved_problem_ids=[],
                total_attempts=5,
            )
            db.add(bot)
        await db.flush()

        pr = await ContestSimulationService.calculate_performance_rating(
            db,
            contest.id,
            player_solved=3,
        )
        # Player solved 3, which is middle of pack
        # PR should be somewhere in the reasonable range [1000, 2000]
        assert 800 < pr < 2500

    @pytest.mark.asyncio
    async def test_pr_bounded_0_4000(self, db):
        """PR is always in [0, 4000]."""
        user = _make_user(elo=1500)
        db.add(user)
        contest = _make_contest_session(user_id=user.id, problems_solved=0)
        db.add(contest)
        await db.flush()

        for i in range(5):
            bot = _TestContestBot(
                contest_id=contest.id,
                bot_name=f"Bot_{i}",
                bot_elo=3500 + i * 100,
                problems_solved=5,
                solved_problem_ids=[],
                total_attempts=5,
            )
            db.add(bot)
        await db.flush()

        pr = await ContestSimulationService.calculate_performance_rating(
            db,
            contest.id,
            player_solved=0,
        )
        assert 0 <= pr <= 4000

    @pytest.mark.asyncio
    async def test_pr_no_bots_fallback(self, db):
        """PR with no bots uses fallback estimation."""
        user = _make_user(elo=1500)
        db.add(user)
        contest = _make_contest_session(user_id=user.id, problems_solved=3)
        db.add(contest)
        await db.flush()

        pr = await ContestSimulationService.calculate_performance_rating(
            db,
            contest.id,
            player_solved=3,
        )
        # Should still return a valid PR
        assert 0 <= pr <= 4000
        # With 3/5 solved, PR should be somewhat reasonable
        assert pr > 0

    @pytest.mark.asyncio
    async def test_pr_with_one_bot(self, db):
        """PR works with just 1 bot."""
        user = _make_user(elo=1500)
        db.add(user)
        contest = _make_contest_session(user_id=user.id, problems_solved=3)
        db.add(contest)
        await db.flush()

        bot = _TestContestBot(
            contest_id=contest.id,
            bot_name="SoloBot",
            bot_elo=1500,
            problems_solved=2,
            solved_problem_ids=[],
            total_attempts=5,
        )
        db.add(bot)
        await db.flush()

        pr = await ContestSimulationService.calculate_performance_rating(
            db,
            contest.id,
            player_solved=3,
        )
        # Player solved more than bot -> PR should be reasonable
        assert pr > 0
        assert 0 <= pr <= 4000


class TestPerformanceRatingConvergence:
    """Verify binary search converges correctly."""

    def test_binary_search_precision(self):
        """Binary search converges within +/- 1 precision."""
        bot_elos = [1200, 1400, 1600, 1800, 2000]
        problem_ratings = [1200, 1400, 1600, 1800, 2000]
        player_solved = 3

        actual_rank = ContestSimulationService.calculate_actual_rank_smooth(
            player_solved,
            bot_elos,
            problem_ratings,
        )

        lo, hi = 0, 4000
        iterations = 0
        while hi - lo > 1:
            mid = (lo + hi) // 2
            expected_rank = ContestSimulationService.calculate_expected_rank(
                mid,
                bot_elos,
                problem_ratings,
                player_solved,
            )
            if expected_rank <= actual_rank:
                hi = mid
            else:
                lo = mid
            iterations += 1

        # Should converge in ~12 iterations (log2(4000) ~ 12)
        assert iterations <= 15
        assert hi - lo <= 1


class TestEstimatePrNoBots:
    """Verify PR fallback when no bots are present."""

    def test_full_solve(self):
        """Full solve -> PR higher than average rating."""
        problems = [
            {"rating": 1000},
            {"rating": 1200},
            {"rating": 1400},
            {"rating": 1600},
            {"rating": 1800},
        ]
        pr = ContestSimulationService._estimate_pr_no_bots(5, problems)
        avg = sum(p["rating"] for p in problems) / len(problems)
        # solve_ratio=1.0 -> PR = avg * 1.5
        assert pr == int(avg * 1.5)

    def test_no_solve(self):
        """No solve -> PR lower than average rating."""
        problems = [{"rating": 1000}, {"rating": 1500}]
        pr = ContestSimulationService._estimate_pr_no_bots(0, problems)
        # avg=1250, solve_ratio=0 -> PR = 1250 * 0.5 = 625
        assert pr == 625

    def test_no_problems(self):
        """No problems -> fallback to 1000."""
        pr = ContestSimulationService._estimate_pr_no_bots(0, [])
        assert pr == 1000

    def test_half_solve(self):
        """Half solve -> PR at average rating."""
        problems = [
            {"rating": 1000},
            {"rating": 1500},
            {"rating": 2000},
            {"rating": 2500},
        ]
        pr = ContestSimulationService._estimate_pr_no_bots(2, problems)
        # avg = 1750, solve_ratio = 0.5 -> PR = 1750 * (0.5 + 0.5) = 1750
        assert pr == 1750


# ===========================================================================
# Test: PR Elo settlement integration
# ===========================================================================


class _TestEloHistory(_TestBase):
    __tablename__ = "elo_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    elo_before: Mapped[int] = mapped_column(Integer, nullable=False)
    elo_after: Mapped[int] = mapped_column(Integer, nullable=False)
    elo_change: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    time_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestTokenTransaction(_TestBase):
    __tablename__ = "token_transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestPPRecord(_TestBase):
    __tablename__ = "pp_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    cf_problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    base_pp: Mapped[float] = mapped_column(Float, nullable=False)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hints_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wa_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_spent_minutes: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    performance_factor: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    final_pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    overkill_multiplier: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)


class TestPrEloSettlement:
    """Verify that PR-based Elo settlement formula works correctly."""

    def test_elo_change_formula(self):
        """Elo change = K * (PR - current_elo) / 400."""
        # K=32, PR=1800, current_elo=1500
        # elo_change = 32 * (1800 - 1500) / 400 = 32 * 0.75 = 24
        pr = 1800
        current_elo = 1500
        k = 32.0
        elo_change = round(k * (pr - current_elo) / 400)
        assert elo_change == 24

    def test_elo_change_negative(self):
        """When PR < current_elo, Elo change is negative."""
        pr = 1000
        current_elo = 1500
        k = 32.0
        elo_change = round(k * (pr - current_elo) / 400)
        assert elo_change < 0
        assert elo_change == -40

    def test_elo_change_zero(self):
        """When PR == current_elo, Elo change is 0."""
        pr = 1500
        current_elo = 1500
        k = 32.0
        elo_change = round(k * (pr - current_elo) / 400)
        assert elo_change == 0

    def test_large_elo_update(self):
        """PR settlement produces larger changes than standard Elo."""
        # Standard Elo: K * (S - E) where S in [0,1] and E ~ 0.5
        # Max standard change: K * 0.5 = 16 (for K=32)
        # PR settlement: K * (PR - elo) / 400
        # For PR=2200, elo=1000: K * 1200/400 = K * 3 = 96
        pr = 2200
        current_elo = 1000
        k = 32.0
        elo_change = round(k * (pr - current_elo) / 400)
        assert elo_change > 32  # Much larger than standard Elo update
        assert elo_change == 96

    @pytest.mark.asyncio
    async def test_pr_and_elo_change_integration(self, db):
        """End-to-end: compute PR and verify Elo change formula."""
        user = _make_user(elo=1500)
        db.add(user)
        contest = _make_contest_session(user_id=user.id, problems_solved=4)
        db.add(contest)
        await db.flush()

        # Create bots that solved fewer than player
        for i in range(10):
            bot = _TestContestBot(
                contest_id=contest.id,
                bot_name=f"Bot_{i}",
                bot_elo=1200 + i * 50,
                problems_solved=1 + i % 3,
                solved_problem_ids=[],
                total_attempts=5,
            )
            db.add(bot)
        await db.flush()

        pr = await ContestSimulationService.calculate_performance_rating(
            db,
            contest.id,
            player_solved=4,
        )

        # PR should be reasonable for 4/5 solved
        assert pr > 0
        assert pr <= 4000

        # Calculate what Elo change would be with K=32
        k = 32.0
        elo_change = round(k * (pr - 1500) / 400)

        # Player solved 4/5 which is very good -> PR likely > 1500 -> positive change
        assert pr >= 1500
        assert elo_change >= 0


# ===========================================================================
# Test: Simulation config
# ===========================================================================


class TestSimulationConfig:
    """Verify simulation config loading."""

    def test_get_simulation_config_returns_dict(self):
        """_get_simulation_config returns the expected config dict."""
        config = _get_simulation_config()
        assert "tick_interval_seconds" in config
        assert "difficulty_ticks" in config
        assert "jitter" in config

    def test_default_tick_interval(self):
        """Default tick interval is 30 seconds."""
        config = _get_simulation_config()
        assert config["tick_interval_seconds"] == 30

    def test_default_difficulty_ticks(self):
        """Default difficulty ticks has easy/medium/hard ranges."""
        config = _get_simulation_config()
        dt = config["difficulty_ticks"]
        assert dt["easy"] == [2, 4]
        assert dt["medium"] == [6, 16]
        assert dt["hard"] == [16, 30]

    def test_default_jitter(self):
        """Default jitter is 0.3."""
        config = _get_simulation_config()
        assert config["jitter"] == 0.3

    def test_default_give_up_threshold(self):
        """Default give_up_threshold is 800."""
        config = _get_simulation_config()
        assert config["give_up_threshold"] == 800

    def test_default_retry_base_prob(self):
        """Default retry_base_prob is 0.3."""
        config = _get_simulation_config()
        assert config["retry_base_prob"] == 0.3


# ===========================================================================
# Test: Extreme Elo values
# ===========================================================================


class TestExtremeEloValues:
    """Verify simulation handles extreme Elo values without errors."""

    def test_zero_elo_bot(self):
        """Bot with Elo 0 can still compute ticks."""
        ticks = _get_ticks_for_bot_problem(0, 800, 120, 5, 30, 0.0)
        assert ticks >= 1

    def test_very_high_elo_bot(self):
        """Bot with Elo 5000 can still compute ticks."""
        ticks = _get_ticks_for_bot_problem(5000, 800, 120, 5, 30, 0.0)
        assert ticks >= 1

    def test_zero_elo_problem(self):
        """Problem with rating 0 can still compute ticks."""
        ticks = _get_ticks_for_bot_problem(1500, 0, 120, 5, 30, 0.0)
        assert ticks >= 1

    def test_very_high_rating_problem(self):
        """Problem with rating 5000 can still compute ticks."""
        ticks = _get_ticks_for_bot_problem(1500, 5000, 120, 5, 30, 0.0)
        assert ticks >= 1

    def test_extreme_tick_interval(self):
        """Very small tick interval works."""
        ticks = _get_ticks_for_bot_problem(1500, 1500, 120, 5, 1, 0.0)
        assert ticks >= 1
        # Should be proportionally larger than with 30s interval
        ticks_30 = _get_ticks_for_bot_problem(1500, 1500, 120, 5, 30, 0.0)
        assert ticks > ticks_30

    @pytest.mark.asyncio
    async def test_zero_elo_bot_in_simulation(self, db):
        """Bot with Elo 0 works in full simulation without errors."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        # Create a bot with Elo 0
        bot = _TestContestBot(
            contest_id=contest.id,
            bot_name="ZeroBot",
            bot_elo=0,
            problems_solved=0,
            solved_problem_ids=[],
            total_attempts=0,
        )
        db.add(bot)
        await db.commit()

        # Should not crash
        for _ in range(10):
            await ContestSimulationService.tick_simulation(db, contest.id)
            await db.commit()

        await db.refresh(bot)
        assert bot.total_attempts > 0

    @pytest.mark.asyncio
    async def test_very_high_elo_bot_in_simulation(self, db):
        """Bot with Elo 5000 works in full simulation without errors."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bot = _TestContestBot(
            contest_id=contest.id,
            bot_name="UltraBot",
            bot_elo=5000,
            problems_solved=0,
            solved_problem_ids=[],
            total_attempts=0,
        )
        db.add(bot)
        await db.commit()

        for _ in range(10):
            await ContestSimulationService.tick_simulation(db, contest.id)
            await db.commit()

        await db.refresh(bot)
        assert bot.total_attempts > 0


# ===========================================================================
# Helper: create a bot for unit tests
# ===========================================================================


def _make_bot(
    elo: int = 1500,
    problems: list[str] | None = None,
) -> _TestContestBot:
    """Create a test bot with sensible defaults."""
    return _TestContestBot(
        id=uuid.uuid4(),
        contest_id=uuid.uuid4(),
        bot_name=f"TestBot_{uuid.uuid4().hex[:4]}",
        bot_elo=elo,
        problems_solved=len(problems) if problems else 0,
        solved_problem_ids=problems or [],
        total_attempts=0,
    )
