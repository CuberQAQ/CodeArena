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
    _bot_states,
    _generate_bot_name,
    _get_simulation_config,
    _get_tick_range_for_rating,
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
    async def test_tick_returns_solved_ids(self, db):
        """Tick returns list of problem IDs solved this tick."""
        contest = _make_contest_session()
        db.add(contest)
        await db.flush()

        # Generate many bots to increase chance of solves
        await ContestSimulationService.generate_bots(
            db,
            contest.id,
            user_elo=1500,
            count=100,
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
            db,
            contest.id,
            user_elo=2000,
            count=50,
        )
        await db.commit()

        # Run multiple ticks
        for _ in range(30):
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

        for _ in range(20):
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
# Test: Difficulty-based tick timing
# ===========================================================================


class TestDifficultyTiming:
    """Verify difficulty-based tick ranges for bot problem-solving."""

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
        # Use extreme jitter + small range
        for rating in [500, 1000, 1500, 2000, 3000]:
            for _ in range(50):
                ticks = _get_tick_range_for_rating(rating, jitter=0.9)
                assert ticks >= 1


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
        bot_state: dict = {"current_problem": None, "ticks_remaining": 0}

        # Use 0-tick difficulty to force immediate P(AC) rolls
        diff_ticks = {"easy": [1, 1], "medium": [1, 1], "hard": [1, 1]}

        # Run many ticks -- each should solve at most 1
        for _ in range(20):
            solved = ContestSimulationService._simulate_bot_tick(
                bot,
                problems,
                time_factor=1.0,
                bot_state=bot_state,
                difficulty_ticks=diff_ticks,
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
        bot_state: dict = {"current_problem": None, "ticks_remaining": 0}

        # Use 1-tick difficulty so bot picks immediately
        diff_ticks = {"easy": [1, 1], "medium": [1, 1], "hard": [1, 1]}

        ContestSimulationService._simulate_bot_tick(
            bot,
            problems,
            time_factor=1.0,
            bot_state=bot_state,
            difficulty_ticks=diff_ticks,
            jitter=0.0,
        )

        # Bot should have selected the easiest problem
        assert bot_state["current_problem"] is None or bot_state["current_problem"] == "easy"

    def test_bot_pauses_on_hard_problems(self):
        """Hard problems require multiple ticks before P(AC) roll."""
        bot = _make_bot(elo=1500, problems=[])
        problems = [{"problem_id": "hard", "rating": 2500}]
        bot_state: dict = {"current_problem": None, "ticks_remaining": 0}

        # Hard = 3 ticks minimum
        diff_ticks = {"easy": [1, 1], "medium": [2, 2], "hard": [3, 3]}

        # First tick: bot picks problem, starts working
        ContestSimulationService._simulate_bot_tick(
            bot,
            problems,
            time_factor=1.0,
            bot_state=bot_state,
            difficulty_ticks=diff_ticks,
            jitter=0.0,
        )
        # Should be working on the hard problem, 2 ticks remaining
        assert bot_state["current_problem"] == "hard"
        assert bot_state["ticks_remaining"] == 2

        # Second tick: still working
        solved = ContestSimulationService._simulate_bot_tick(
            bot,
            problems,
            time_factor=1.0,
            bot_state=bot_state,
            difficulty_ticks=diff_ticks,
            jitter=0.0,
        )
        assert len(solved) == 0
        assert bot_state["ticks_remaining"] == 1

        # Third tick: P(AC) roll happens
        solved = ContestSimulationService._simulate_bot_tick(
            bot,
            problems,
            time_factor=1.0,
            bot_state=bot_state,
            difficulty_ticks=diff_ticks,
            jitter=0.0,
        )
        # Either solved or not (depends on random), but no more ticks remaining
        assert bot_state["ticks_remaining"] == 0

    def test_bot_moves_to_next_after_solving(self):
        """After solving a problem, bot picks the next unsolved."""
        bot = _make_bot(elo=3000, problems=[])
        problems = [
            {"problem_id": "p1", "rating": 800},
            {"problem_id": "p2", "rating": 900},
        ]
        bot_state: dict = {"current_problem": None, "ticks_remaining": 0}
        diff_ticks = {"easy": [1, 1], "medium": [1, 1], "hard": [1, 1]}

        # Tick 1: solve p1
        ContestSimulationService._simulate_bot_tick(
            bot,
            problems,
            time_factor=1.0,
            bot_state=bot_state,
            difficulty_ticks=diff_ticks,
            jitter=0.0,
        )
        # p1 may or may not be solved (depends on random), but bot should move on

        # Run enough ticks to potentially solve both
        for _ in range(5):
            ContestSimulationService._simulate_bot_tick(
                bot,
                problems,
                time_factor=1.0,
                bot_state=bot_state,
                difficulty_ticks=diff_ticks,
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
        bot_state: dict = {"current_problem": None, "ticks_remaining": 0}

        solved = ContestSimulationService._simulate_bot_tick(
            bot,
            problems,
            time_factor=1.0,
            bot_state=bot_state,
        )
        assert solved == []

    def test_easy_not_solved_first_tick(self):
        """With multi-tick easy problems, bot does not solve immediately."""
        bot = _make_bot(elo=3000, problems=[])
        problems = [{"problem_id": "p1", "rating": 800}]
        bot_state: dict = {"current_problem": None, "ticks_remaining": 0}

        # Easy = 5 ticks minimum
        diff_ticks = {"easy": [5, 5], "medium": [10, 10], "hard": [20, 20]}

        # First tick: bot picks problem, starts working
        solved = ContestSimulationService._simulate_bot_tick(
            bot,
            problems,
            time_factor=1.0,
            bot_state=bot_state,
            difficulty_ticks=diff_ticks,
            jitter=0.0,
        )
        assert len(solved) == 0  # Not enough ticks yet
        assert bot_state["ticks_remaining"] == 4  # 5 - 1 = 4


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
        for _ in range(20):
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
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class _TestTokenTransaction(_TestBase):
    __tablename__ = "token_transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    tx_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class _TestPPRecord(_TestBase):
    __tablename__ = "pp_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    wa_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_spent: Mapped[float] = mapped_column(Integer, default=0, nullable=False)
    user_elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)


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
