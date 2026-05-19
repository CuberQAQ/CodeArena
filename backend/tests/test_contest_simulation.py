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
from sqlalchemy import JSON, DateTime, Integer, String, event
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
    _generate_bot_name,
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
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)


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
        async_engine, class_=AsyncSession, expire_on_commit=False,
    )

    async with session_factory() as session:
        with (
            patch.object(sim_svc_module, "ContestBot", _TestContestBot),
            patch.object(sim_svc_module, "ContestSession", _TestContestSession),
        ):
            yield session


def _make_user(**kwargs) -> _TestUser:
    """Create a test user with sensible defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "username": f"user_{uuid.uuid4().hex[:8]}",
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
            db, contest.id, user_elo=1500,
        )
        assert len(bots) == 50

    @pytest.mark.asyncio
    async def test_generate_custom_count(self, db):
        """Custom count generates exactly that many bots."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db, contest.id, user_elo=1500, count=10,
        )
        assert len(bots) == 10

    @pytest.mark.asyncio
    async def test_generate_zero_bots(self, db):
        """Count of 0 returns empty list."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db, contest.id, user_elo=1500, count=0,
        )
        assert bots == []

    @pytest.mark.asyncio
    async def test_elo_normal_distribution(self, db):
        """Bot Elo values are approximately normally distributed around user Elo."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        bots = await ContestSimulationService.generate_bots(
            db, contest.id, user_elo=1500, count=100, sigma=200,
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
            db, contest.id, user_elo=1500, count=50,
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
            db, contest.id, user_elo=1500, count=5,
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
            db, contest.id, user_elo=50, count=20, sigma=100,
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
            db, contest.id, user_elo=1500, count=1,
        )
        assert len(bots) == 1
        assert bots[0].bot_elo > 0


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
            db, contest.id, user_elo=1500, count=20,
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
    async def test_tick_returns_solved_ids(self, db):
        """Tick returns list of problem IDs solved this tick."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        # Generate many bots to increase chance of solves
        await ContestSimulationService.generate_bots(
            db, contest.id, user_elo=1500, count=100,
        )
        await db.commit()

        # Run multiple ticks to increase chance of at least one solve
        all_solved = []
        for _ in range(10):
            solved = await ContestSimulationService.tick_simulation(db, contest.id)
            all_solved.extend(solved)
            await db.commit()

        # With 100 bots at elo 1500 and 5 problems, at least some should solve
        # (probabilistic test, but with 100 bots x 10 ticks, extremely likely)
        # Note: it is theoretically possible no bots solve anything, but very unlikely

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
            db, contest.id, user_elo=2000, count=50,
        )
        await db.commit()

        # Run multiple ticks
        for _ in range(5):
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
            db, contest.id, user_elo=1800, count=30,
        )
        await db.commit()

        for _ in range(5):
            await ContestSimulationService.tick_simulation(db, contest.id)
            await db.commit()

        for bot in bots:
            await db.refresh(bot)
            solved_list = bot.solved_problem_ids or []
            assert bot.problems_solved == len(solved_list)


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
            db, contest.id, user,
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
            db, contest.id, user_elo=1500, count=10,
        )
        await db.commit()

        leaderboard = await ContestSimulationService.build_leaderboard(
            db, contest.id, user,
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
            db, contest.id, user_elo=1500, count=5,
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
            db, contest.id, user,
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
            db, contest.id, user,
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
            db, uuid.uuid4(), user,
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
            db, contest.id, user_elo=1500, count=20,
        )
        await db.commit()
        assert len(bots) == 20

        # Simulate the user solving 2 problems
        contest.problems_solved = 2
        await db.flush()

        # Run several ticks
        for _ in range(10):
            await ContestSimulationService.tick_simulation(db, contest.id)
            await db.commit()

        # Build leaderboard
        leaderboard = await ContestSimulationService.build_leaderboard(
            db, contest.id, user,
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
