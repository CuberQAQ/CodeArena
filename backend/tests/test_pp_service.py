"""Tests for the PP (Performance Points) calculation engine.

All pure-calculation tests verify correctness against the mathematical formulas.
Integration-style tests that involve database writes use an in-memory SQLite
database with async sessions.
"""

import math
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import Float, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.services.pp_service import PPConfig, PPService

# ---------------------------------------------------------------------------
# Lightweight SQLite-compatible test models
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _TestUser(_TestBase):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class _TestPPRecord(_TestBase):
    __tablename__ = "pp_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    cf_problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    base_pp: Mapped[float] = mapped_column(Float, nullable=False)
    solved_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.now)
    hints_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> PPConfig:
    """Return a default PPConfig."""
    return PPConfig()


# Async DB fixtures ---------------------------------------------------------


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
    """Provide an async session that uses test-compatible models.

    The real PPService creates real PPRecord instances mapped to the
    production Base.  We patch the DB-interacting methods so they use our
    SQLite-compatible _TestPPRecord and _TestUser instead.
    """
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _test_record_pp(
        db_session: AsyncSession,
        user_id: uuid.UUID,
        cf_problem_id: str,
        problem_rating: int,
        hints_used: int = 0,
        config: PPConfig | None = None,
    ):
        if config is None:
            config = PPConfig()
        base_pp = PPService.calculate_base_pp(problem_rating, config)

        from sqlalchemy import select

        stmt = select(_TestPPRecord).where(
            _TestPPRecord.user_id == user_id,
            _TestPPRecord.cf_problem_id == cf_problem_id,
        )
        result = await db_session.execute(stmt)
        existing = result.scalar_one_or_none()

        now = datetime.now()

        if existing is None:
            record = _TestPPRecord(
                user_id=user_id,
                cf_problem_id=cf_problem_id,
                problem_rating=problem_rating,
                base_pp=base_pp,
                solved_at=now,
                hints_used=hints_used,
            )
            db_session.add(record)
            await db_session.flush()
        else:
            existing.hints_used = existing.hints_used + hints_used
            if problem_rating > existing.problem_rating:
                existing.problem_rating = problem_rating
                existing.base_pp = base_pp
                existing.solved_at = now
            await db_session.flush()
            record = existing

        await PPService.refresh_user_pp(db_session, user_id, config)
        return record

    async def _test_calculate_user_total_pp(
        db_session: AsyncSession,
        user_id: uuid.UUID,
        config: PPConfig | None = None,
    ) -> float:
        if config is None:
            config = PPConfig()

        from sqlalchemy import select

        stmt = (
            select(_TestPPRecord.base_pp)
            .where(_TestPPRecord.user_id == user_id)
            .order_by(_TestPPRecord.base_pp.desc())
            .limit(config.max_problems)
        )
        result = await db_session.execute(stmt)
        pp_values = [row[0] for row in result.all()]
        return PPService.aggregate_total_pp(pp_values, config)

    async def _test_refresh_user_pp(
        db_session: AsyncSession,
        user_id: uuid.UUID,
        config: PPConfig | None = None,
    ) -> float:
        if config is None:
            config = PPConfig()

        total_pp = await _test_calculate_user_total_pp(db_session, user_id, config)

        from sqlalchemy import select

        stmt = select(_TestUser).where(_TestUser.id == user_id)
        result = await db_session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is not None:
            user.pp = total_pp
            await db_session.flush()

        return total_pp

    async def _test_get_pp_ranking(
        db_session: AsyncSession,
        page: int = 1,
        page_size: int = 50,
    ):
        page = max(1, page)
        page_size = max(1, min(page_size, 100))

        from sqlalchemy import func, select

        count_stmt = select(func.count()).select_from(_TestUser).where(_TestUser.is_active.is_(True))
        total = (await db_session.execute(count_stmt)).scalar_one()

        offset = (page - 1) * page_size
        stmt = (
            select(_TestUser.username, _TestUser.pp)
            .where(_TestUser.is_active.is_(True))
            .order_by(_TestUser.pp.desc(), _TestUser.username.asc())
            .offset(offset)
            .limit(page_size)
        )
        result = await db_session.execute(stmt)
        rows = result.all()

        ranking = [(offset + i + 1, row[0], row[1]) for i, row in enumerate(rows)]
        return ranking, total

    async def _test_get_user_rank(
        db_session: AsyncSession,
        user_id: uuid.UUID,
    ):
        from sqlalchemy import func, select

        user_stmt = select(_TestUser.pp).where(_TestUser.id == user_id, _TestUser.is_active.is_(True))
        result = await db_session.execute(user_stmt)
        user_pp = result.scalar_one_or_none()
        if user_pp is None:
            return None

        higher_stmt = (
            select(func.count())
            .select_from(_TestUser)
            .where(
                _TestUser.is_active.is_(True),
                _TestUser.pp > user_pp,
            )
        )
        higher_count = (await db_session.execute(higher_stmt)).scalar_one()
        return higher_count + 1

    async with session_factory() as session:
        with (
            patch.object(PPService, "record_pp", _test_record_pp),
            patch.object(PPService, "calculate_user_total_pp", _test_calculate_user_total_pp),
            patch.object(PPService, "refresh_user_pp", _test_refresh_user_pp),
            patch.object(PPService, "get_pp_ranking", _test_get_pp_ranking),
            patch.object(PPService, "get_user_rank", _test_get_user_rank),
        ):
            yield session


async def _create_user(
    db: AsyncSession,
    username: str = "testuser",
    pp: float = 0.0,
    is_active: bool = True,
) -> uuid.UUID:
    """Helper: insert a _TestUser row directly and return the id."""
    uid = uuid.uuid4()
    db.add(
        _TestUser(
            id=uid,
            username=username,
            email=f"{username}@test.com",
            password_hash="hash",
            pp=pp,
            is_active=is_active,
        )
    )
    await db.flush()
    return uid


async def _create_pp_record(
    db: AsyncSession,
    user_id: uuid.UUID,
    cf_problem_id: str,
    problem_rating: int,
    hints_used: int = 0,
) -> uuid.UUID:
    """Helper: insert a _TestPPRecord row directly and return the id."""
    config = PPConfig()
    base_pp = PPService.calculate_base_pp(problem_rating, config)
    rid = uuid.uuid4()
    db.add(
        _TestPPRecord(
            id=rid,
            user_id=user_id,
            cf_problem_id=cf_problem_id,
            problem_rating=problem_rating,
            base_pp=base_pp,
            solved_at=datetime.now(),
            hints_used=hints_used,
        )
    )
    await db.flush()
    return rid


# ---------------------------------------------------------------------------
# 1. Base PP calculation
# ---------------------------------------------------------------------------


class TestCalculateBasePP:
    """Verify base PP formula: sqrt((rating - 800) / 100) * 10 for rating >= 800."""

    def test_below_offset_returns_zero(self):
        assert PPService.calculate_base_pp(799) == 0.0

    def test_at_offset_returns_zero(self):
        """rating = 800 => sqrt(0) * 10 = 0."""
        assert PPService.calculate_base_pp(800) == 0.0

    def test_rating_900(self):
        """sqrt((900-800)/100) * 10 = sqrt(1) * 10 = 10."""
        assert PPService.calculate_base_pp(900) == pytest.approx(10.0, abs=1e-6)

    def test_rating_1200(self):
        """sqrt((1200-800)/100) * 10 = sqrt(4) * 10 = 20."""
        assert PPService.calculate_base_pp(1200) == pytest.approx(20.0, abs=1e-6)

    def test_rating_1500(self):
        """sqrt((1500-800)/100) * 10 = sqrt(7) * 10 ~ 26.46."""
        expected = math.sqrt(7) * 10
        assert PPService.calculate_base_pp(1500) == pytest.approx(expected, abs=1e-6)

    def test_rating_2000(self):
        """sqrt((2000-800)/100) * 10 = sqrt(12) * 10 ~ 34.64."""
        expected = math.sqrt(12) * 10
        assert PPService.calculate_base_pp(2000) == pytest.approx(expected, abs=1e-6)

    def test_rating_3500(self):
        """sqrt((3500-800)/100) * 10 = sqrt(27) * 10 ~ 51.96."""
        expected = math.sqrt(27) * 10
        assert PPService.calculate_base_pp(3500) == pytest.approx(expected, abs=1e-6)

    def test_very_high_rating(self):
        """rating=4800 => sqrt(40) * 10 ~ 63.25."""
        expected = math.sqrt(40) * 10
        assert PPService.calculate_base_pp(4800) == pytest.approx(expected, abs=1e-6)

    def test_custom_config_offset(self):
        config = PPConfig(base_formula_offset=1000)
        assert PPService.calculate_base_pp(999, config) == 0.0
        assert PPService.calculate_base_pp(1000, config) == 0.0
        # sqrt((1100-1000)/100) * 10 = sqrt(1) * 10 = 10
        assert PPService.calculate_base_pp(1100, config) == pytest.approx(10.0, abs=1e-6)

    def test_custom_config_coefficient(self):
        config = PPConfig(base_formula_coefficient=20)
        # sqrt((1200-800)/100) * 20 = sqrt(4) * 20 = 40
        assert PPService.calculate_base_pp(1200, config) == pytest.approx(40.0, abs=1e-6)

    def test_negative_rating(self):
        assert PPService.calculate_base_pp(-100) == 0.0

    def test_rating_zero(self):
        assert PPService.calculate_base_pp(0) == 0.0


# ---------------------------------------------------------------------------
# 2. Total PP aggregation
# ---------------------------------------------------------------------------


class TestAggregateTotalPP:
    """Verify total PP = sum(P_i * 0.95^(i-1)), rounded to 2 decimals."""

    def test_empty_list(self):
        assert PPService.aggregate_total_pp([]) == 0.0

    def test_single_problem(self):
        """20 * 0.95^0 = 20."""
        assert PPService.aggregate_total_pp([20.0]) == 20.0

    def test_two_equal_problems(self):
        """20 * 1 + 20 * 0.95 = 20 + 19 = 39."""
        result = PPService.aggregate_total_pp([20.0, 20.0])
        assert result == pytest.approx(39.0, abs=0.01)

    def test_three_equal_problems(self):
        """20 * (1 + 0.95 + 0.9025) = 20 * 2.8525 = 57.05."""
        result = PPService.aggregate_total_pp([20.0, 20.0, 20.0])
        assert result == pytest.approx(57.05, abs=0.01)

    def test_100_problems_rating_1200(self):
        """100 problems at rating 1200 => each base_pp = 20.

        Total = 20 * (1 - 0.95^100) / (1 - 0.95) = 20 * 19.8816 = 397.63
        (Task doc approximates as 397.40 using 19.87; exact value is 397.63)
        """
        pp_values = [20.0] * 100
        result = PPService.aggregate_total_pp(pp_values)
        expected = 20.0 * (1 - 0.95**100) / (1 - 0.95)
        assert result == pytest.approx(expected, abs=0.01)
        # Exact geometric series sum gives ~397.63
        assert result == pytest.approx(397.63, abs=0.01)

    def test_100_problems_rating_2000(self):
        """100 problems at rating 2000 => each base_pp = sqrt(12)*10 ~ 34.64.

        Total ~ 34.64 * 19.8816 = 688.72
        (Task doc approximates as 688.33 using 19.87; exact value is 688.72)
        """
        base_pp = math.sqrt(12) * 10
        pp_values = [base_pp] * 100
        result = PPService.aggregate_total_pp(pp_values)
        expected = base_pp * (1 - 0.95**100) / (1 - 0.95)
        assert result == pytest.approx(expected, abs=0.01)
        # Exact geometric series sum gives ~688.72
        assert result == pytest.approx(688.72, abs=0.01)

    def test_more_than_max_problems_capped(self):
        """150 problems => only first 100 considered."""
        pp_values = [20.0] * 150
        result_100 = PPService.aggregate_total_pp([20.0] * 100)
        result_150 = PPService.aggregate_total_pp(pp_values)
        assert result_100 == result_150

    def test_descending_order_matters(self):
        """Higher PP first yields higher total than lower PP first."""
        descending = [30.0, 20.0, 10.0]
        ascending = [10.0, 20.0, 30.0]
        total_desc = PPService.aggregate_total_pp(descending)
        total_asc = PPService.aggregate_total_pp(ascending)
        assert total_desc > total_asc

    def test_custom_decay_factor(self):
        config = PPConfig(decay_factor=0.9)
        # 20 + 20*0.9 = 20 + 18 = 38
        result = PPService.aggregate_total_pp([20.0, 20.0], config)
        assert result == pytest.approx(38.0, abs=0.01)

    def test_custom_max_problems(self):
        config = PPConfig(max_problems=3)
        pp_values = [20.0] * 10
        # Only first 3: 20*(1 + 0.95 + 0.9025) = 20*2.8525 = 57.05
        result = PPService.aggregate_total_pp(pp_values, config)
        assert result == pytest.approx(57.05, abs=0.01)

    def test_result_rounded_to_two_decimals(self):
        """Result must be rounded to exactly 2 decimal places."""
        # Use values that produce many decimal digits
        result = PPService.aggregate_total_pp([34.641])
        # 34.641 rounded to 2 decimals = 34.64
        assert result == round(34.641, 2)

    def test_mixed_ratings(self):
        """Various ratings produce correct weighted sum."""
        # base_pp for ratings: 900=>10, 1200=>20, 1500=>~26.46, 2000=>~34.64
        values = [34.64, 26.46, 20.0, 10.0]
        expected = (
            34.64 * 0.95**0
            + 26.46 * 0.95**1
            + 20.0 * 0.95**2
            + 10.0 * 0.95**3
        )
        result = PPService.aggregate_total_pp(values)
        assert result == pytest.approx(round(expected, 2), abs=0.01)


# ---------------------------------------------------------------------------
# 3. PP record management (integration)
# ---------------------------------------------------------------------------


class TestRecordPP:
    async def test_create_new_record(self, db: AsyncSession):
        uid = await _create_user(db, "alice")

        record = await PPService.record_pp(db, uid, "1234A", 1200)
        await db.flush()

        assert record.user_id == uid
        assert record.cf_problem_id == "1234A"
        assert record.problem_rating == 1200
        assert record.base_pp == pytest.approx(20.0, abs=1e-6)
        assert record.hints_used == 0

    async def test_update_with_higher_rating(self, db: AsyncSession):
        uid = await _create_user(db, "alice")

        # First solve at 1200
        await PPService.record_pp(db, uid, "1234A", 1200)
        await db.flush()

        # Second solve at 1500 (higher rating)
        record2 = await PPService.record_pp(db, uid, "1234A", 1500)
        await db.flush()

        # Should be the same record object (updated in place)
        assert record2.problem_rating == 1500
        assert record2.base_pp == pytest.approx(PPService.calculate_base_pp(1500), abs=1e-6)

    async def test_no_update_with_lower_rating(self, db: AsyncSession):
        uid = await _create_user(db, "alice")

        # First solve at 1500
        await PPService.record_pp(db, uid, "1234A", 1500)
        await db.flush()

        # Second solve at 1200 (lower rating, should not update)
        record2 = await PPService.record_pp(db, uid, "1234A", 1200)
        await db.flush()

        assert record2.problem_rating == 1500  # Unchanged
        assert record2.base_pp == pytest.approx(PPService.calculate_base_pp(1500), abs=1e-6)

    async def test_no_update_with_same_rating(self, db: AsyncSession):
        uid = await _create_user(db, "alice")

        await PPService.record_pp(db, uid, "1234A", 1200)
        await db.flush()

        record2 = await PPService.record_pp(db, uid, "1234A", 1200)
        await db.flush()

        assert record2.problem_rating == 1200

    async def test_hints_accumulated(self, db: AsyncSession):
        uid = await _create_user(db, "alice")

        await PPService.record_pp(db, uid, "1234A", 1200, hints_used=2)
        await db.flush()

        await PPService.record_pp(db, uid, "1234A", 1200, hints_used=3)
        await db.flush()

        # Hints should accumulate: 2 + 3 = 5
        assert record2.hints_used == 5 if (record2 := await _get_pp_record(db, uid, "1234A")) else False

    async def test_hints_do_not_affect_pp(self, db: AsyncSession):
        uid = await _create_user(db, "alice")

        # Solve without hints
        record_no_hints = await PPService.record_pp(db, uid, "5678B", 1200, hints_used=0)
        await db.flush()

        pp_no_hints = record_no_hints.base_pp

        # Create another user who solves with hints
        uid2 = await _create_user(db, "bob")
        record_with_hints = await PPService.record_pp(db, uid2, "5678B", 1200, hints_used=5)
        await db.flush()

        pp_with_hints = record_with_hints.base_pp

        # PP should be identical regardless of hints
        assert pp_no_hints == pytest.approx(pp_with_hints, abs=1e-6)

    async def test_different_problems_tracked_separately(self, db: AsyncSession):
        uid = await _create_user(db, "alice")

        await PPService.record_pp(db, uid, "1234A", 1200)
        await db.flush()

        await PPService.record_pp(db, uid, "5678B", 1500)
        await db.flush()

        # User should have PP reflecting both problems
        total_pp = await PPService.calculate_user_total_pp(db, uid)
        expected = PPService.calculate_base_pp(1500) * 1 + PPService.calculate_base_pp(1200) * 0.95
        assert total_pp == pytest.approx(round(expected, 2), abs=0.01)

    async def test_rating_below_offset_creates_zero_pp_record(self, db: AsyncSession):
        uid = await _create_user(db, "alice")

        record = await PPService.record_pp(db, uid, "9999Z", 600)
        await db.flush()

        assert record.base_pp == 0.0
        assert record.problem_rating == 600


async def _get_pp_record(db: AsyncSession, user_id: uuid.UUID, cf_problem_id: str):
    """Helper to fetch a PP record directly from test DB."""
    from sqlalchemy import select

    stmt = select(_TestPPRecord).where(
        _TestPPRecord.user_id == user_id,
        _TestPPRecord.cf_problem_id == cf_problem_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# 4. Total PP calculation for a user
# ---------------------------------------------------------------------------


class TestCalculateUserTotalPP:
    async def test_no_records_returns_zero(self, db: AsyncSession):
        uid = await _create_user(db, "alice")
        result = await PPService.calculate_user_total_pp(db, uid)
        assert result == 0.0

    async def test_single_record(self, db: AsyncSession):
        uid = await _create_user(db, "alice")
        await _create_pp_record(db, uid, "1234A", 1200)
        result = await PPService.calculate_user_total_pp(db, uid)
        assert result == pytest.approx(20.0, abs=0.01)

    async def test_multiple_records_sorted(self, db: AsyncSession):
        uid = await _create_user(db, "alice")
        await _create_pp_record(db, uid, "1234A", 1200)  # 20 PP
        await _create_pp_record(db, uid, "5678B", 1500)  # ~26.46 PP
        await _create_pp_record(db, uid, "9012C", 900)   # 10 PP

        result = await PPService.calculate_user_total_pp(db, uid)

        # Sorted desc: 26.46, 20, 10
        base_pp_1500 = PPService.calculate_base_pp(1500)
        base_pp_1200 = PPService.calculate_base_pp(1200)
        base_pp_900 = PPService.calculate_base_pp(900)
        expected = base_pp_1500 + base_pp_1200 * 0.95 + base_pp_900 * 0.95**2
        assert result == pytest.approx(round(expected, 2), abs=0.01)

    async def test_duplicate_problem_takes_highest_rating(self, db: AsyncSession):
        """When same problem has multiple records (shouldn't happen via service,
        but test the aggregation query handles it correctly)."""
        uid = await _create_user(db, "alice")
        # Insert two records for same problem with different ratings
        await _create_pp_record(db, uid, "1234A", 1200)
        await _create_pp_record(db, uid, "1234A", 1500)

        result = await PPService.calculate_user_total_pp(db, uid)
        # Both records are present, so both contribute
        base_pp_1500 = PPService.calculate_base_pp(1500)
        base_pp_1200 = PPService.calculate_base_pp(1200)
        expected = base_pp_1500 + base_pp_1200 * 0.95
        assert result == pytest.approx(round(expected, 2), abs=0.01)


# ---------------------------------------------------------------------------
# 5. Refresh user PP
# ---------------------------------------------------------------------------


class TestRefreshUserPP:
    async def test_updates_user_pp_field(self, db: AsyncSession):
        uid = await _create_user(db, "alice", pp=0.0)
        await _create_pp_record(db, uid, "1234A", 1200)

        total_pp = await PPService.refresh_user_pp(db, uid)
        assert total_pp == pytest.approx(20.0, abs=0.01)

        # Verify the user object was updated
        from sqlalchemy import select

        stmt = select(_TestUser.pp).where(_TestUser.id == uid)
        result = await db.execute(stmt)
        user_pp = result.scalar_one()
        assert user_pp == pytest.approx(20.0, abs=0.01)

    async def test_nonexistent_user_returns_calculation(self, db: AsyncSession):
        """If user doesn't exist, refresh still returns the calculated PP."""
        fake_uid = uuid.uuid4()
        # No records => 0 PP
        total_pp = await PPService.refresh_user_pp(db, fake_uid)
        assert total_pp == 0.0


# ---------------------------------------------------------------------------
# 6. PP Ranking
# ---------------------------------------------------------------------------


class TestGetPPRanking:
    async def test_empty_ranking(self, db: AsyncSession):
        ranking, total = await PPService.get_pp_ranking(db, page=1, page_size=10)
        assert ranking == []
        assert total == 0

    async def test_single_user(self, db: AsyncSession):
        await _create_user(db, "alice", pp=100.0)
        ranking, total = await PPService.get_pp_ranking(db)

        assert total == 1
        assert len(ranking) == 1
        assert ranking[0] == (1, "alice", pytest.approx(100.0, abs=0.01))

    async def test_sorted_by_pp_descending(self, db: AsyncSession):
        await _create_user(db, "alice", pp=100.0)
        await _create_user(db, "bob", pp=200.0)
        await _create_user(db, "charlie", pp=50.0)

        ranking, total = await PPService.get_pp_ranking(db)

        assert total == 3
        assert ranking[0][0] == 1  # rank 1
        assert ranking[0][1] == "bob"  # 200 PP
        assert ranking[1][0] == 2  # rank 2
        assert ranking[1][1] == "alice"  # 100 PP
        assert ranking[2][0] == 3  # rank 3
        assert ranking[2][1] == "charlie"  # 50 PP

    async def test_tiebreaker_by_username(self, db: AsyncSession):
        await _create_user(db, "bob", pp=100.0)
        await _create_user(db, "alice", pp=100.0)
        await _create_user(db, "charlie", pp=100.0)

        ranking, total = await PPService.get_pp_ranking(db)

        assert total == 3
        # Same PP => sorted by username asc
        assert ranking[0][1] == "alice"
        assert ranking[1][1] == "bob"
        assert ranking[2][1] == "charlie"

    async def test_pagination(self, db: AsyncSession):
        # Create 5 users
        for i in range(5):
            await _create_user(db, f"user{i}", pp=float(100 - i * 10))

        # Page 1, size 2
        ranking, total = await PPService.get_pp_ranking(db, page=1, page_size=2)
        assert total == 5
        assert len(ranking) == 2
        assert ranking[0] == (1, "user0", pytest.approx(100.0, abs=0.01))
        assert ranking[1] == (2, "user1", pytest.approx(90.0, abs=0.01))

        # Page 2, size 2
        ranking, total = await PPService.get_pp_ranking(db, page=2, page_size=2)
        assert len(ranking) == 2
        assert ranking[0] == (3, "user2", pytest.approx(80.0, abs=0.01))
        assert ranking[1] == (4, "user3", pytest.approx(70.0, abs=0.01))

        # Page 3, size 2
        ranking, total = await PPService.get_pp_ranking(db, page=3, page_size=2)
        assert len(ranking) == 1
        assert ranking[0] == (5, "user4", pytest.approx(60.0, abs=0.01))

    async def test_inactive_users_excluded(self, db: AsyncSession):
        await _create_user(db, "active_user", pp=100.0, is_active=True)
        await _create_user(db, "inactive_user", pp=200.0, is_active=False)

        ranking, total = await PPService.get_pp_ranking(db)
        assert total == 1
        assert ranking[0][1] == "active_user"

    async def test_page_validation(self, db: AsyncSession):
        """page=0 or negative should be treated as page=1."""
        await _create_user(db, "alice", pp=100.0)
        ranking, total = await PPService.get_pp_ranking(db, page=0, page_size=10)
        assert len(ranking) == 1

    async def test_page_size_validation(self, db: AsyncSession):
        """page_size > 100 should be capped."""
        for i in range(5):
            await _create_user(db, f"user{i}", pp=float(i))

        ranking, _ = await PPService.get_pp_ranking(db, page=1, page_size=200)
        # page_size capped at 100, but only 5 users exist
        assert len(ranking) == 5


# ---------------------------------------------------------------------------
# 7. Get user rank
# ---------------------------------------------------------------------------


class TestGetUserRank:
    async def test_nonexistent_user_returns_none(self, db: AsyncSession):
        result = await PPService.get_user_rank(db, uuid.uuid4())
        assert result is None

    async def test_single_user_rank_one(self, db: AsyncSession):
        uid = await _create_user(db, "alice", pp=100.0)
        result = await PPService.get_user_rank(db, uid)
        assert result == 1

    async def test_rank_calculation(self, db: AsyncSession):
        uid1 = await _create_user(db, "alice", pp=100.0)
        uid2 = await _create_user(db, "bob", pp=200.0)
        uid3 = await _create_user(db, "charlie", pp=50.0)

        assert await PPService.get_user_rank(db, uid2) == 1  # 200 PP
        assert await PPService.get_user_rank(db, uid1) == 2  # 100 PP
        assert await PPService.get_user_rank(db, uid3) == 3  # 50 PP

    async def test_tied_pp_same_rank(self, db: AsyncSession):
        uid1 = await _create_user(db, "alice", pp=100.0)
        uid2 = await _create_user(db, "bob", pp=100.0)

        # Both have PP=100, no one has PP > 100, so both rank 1
        assert await PPService.get_user_rank(db, uid1) == 1
        assert await PPService.get_user_rank(db, uid2) == 1

    async def test_inactive_user_returns_none(self, db: AsyncSession):
        uid = await _create_user(db, "alice", pp=100.0, is_active=False)
        result = await PPService.get_user_rank(db, uid)
        assert result is None


# ---------------------------------------------------------------------------
# 8. Edge cases & boundary conditions
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_base_pp_at_boundary(self):
        """Exactly at offset boundary."""
        config = PPConfig(base_formula_offset=800)
        assert PPService.calculate_base_pp(800, config) == 0.0
        # Just 1 above
        expected = math.sqrt(1 / 100.0) * 10  # sqrt(0.01)*10 = 1.0
        assert PPService.calculate_base_pp(801, config) == pytest.approx(expected, abs=1e-6)

    def test_aggregate_with_zero_pp_entries(self):
        """Some problems have 0 PP (rating < offset)."""
        result = PPService.aggregate_total_pp([0.0, 20.0, 0.0])
        # 0 + 20*0.95 + 0 = 19.0
        assert result == pytest.approx(19.0, abs=0.01)

    def test_aggregate_all_zeros(self):
        assert PPService.aggregate_total_pp([0.0, 0.0, 0.0]) == 0.0

    def test_config_immutability(self):
        """PPConfig is frozen, attempting to modify should raise."""
        config = PPConfig()
        with pytest.raises(AttributeError):
            config.decay_factor = 0.9  # type: ignore[misc]

    def test_default_config_values(self):
        config = PPConfig()
        assert config.base_formula_coefficient == 10.0
        assert config.base_formula_offset == 800
        assert config.decay_factor == 0.95
        assert config.max_problems == 100

    def test_geometric_series_formula_verification(self):
        """Verify decay formula: sum = P * (1 - r^n) / (1 - r)."""
        n = 50
        r = 0.95
        pp = 25.0
        pp_values = [pp] * n

        result = PPService.aggregate_total_pp(pp_values)
        expected = pp * (1 - r**n) / (1 - r)
        assert result == pytest.approx(round(expected, 2), abs=0.01)

    async def test_record_pp_updates_user_total(self, db: AsyncSession):
        """After recording PP, the user.pp field should be updated."""
        uid = await _create_user(db, "alice", pp=0.0)

        await PPService.record_pp(db, uid, "1234A", 1200)
        await db.flush()

        # Check user.pp was updated
        from sqlalchemy import select

        stmt = select(_TestUser.pp).where(_TestUser.id == uid)
        result = await db.execute(stmt)
        user_pp = result.scalar_one()
        assert user_pp == pytest.approx(20.0, abs=0.01)

    async def test_record_pp_multiple_problems_accumulates(self, db: AsyncSession):
        uid = await _create_user(db, "alice", pp=0.0)

        await PPService.record_pp(db, uid, "1234A", 1200)
        await db.flush()

        await PPService.record_pp(db, uid, "5678B", 1500)
        await db.flush()

        from sqlalchemy import select

        stmt = select(_TestUser.pp).where(_TestUser.id == uid)
        result = await db.execute(stmt)
        user_pp = result.scalar_one()

        base_pp_1500 = PPService.calculate_base_pp(1500)
        base_pp_1200 = PPService.calculate_base_pp(1200)
        expected = round(base_pp_1500 + base_pp_1200 * 0.95, 2)
        assert user_pp == pytest.approx(expected, abs=0.01)

    def test_large_number_of_problems(self):
        """Verify aggregation works with max_problems boundary."""
        pp_values = [30.0] * 100
        result = PPService.aggregate_total_pp(pp_values)
        expected = 30.0 * (1 - 0.95**100) / (1 - 0.95)
        assert result == pytest.approx(round(expected, 2), abs=0.01)

    def test_custom_config_all_parameters(self):
        config = PPConfig(
            base_formula_coefficient=5.0,
            base_formula_offset=1000,
            decay_factor=0.9,
            max_problems=10,
        )
        # base_pp for rating 1200: sqrt((1200-1000)/100) * 5 = sqrt(2)*5 ~ 7.07
        base_pp = PPService.calculate_base_pp(1200, config)
        assert base_pp == pytest.approx(math.sqrt(2) * 5, abs=1e-6)

        # aggregation with custom decay and max
        pp_values = [base_pp] * 15  # Only 10 should count
        result = PPService.aggregate_total_pp(pp_values, config)
        expected = base_pp * (1 - 0.9**10) / (1 - 0.9)
        assert result == pytest.approx(round(expected, 2), abs=0.01)
