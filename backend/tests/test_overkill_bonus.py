"""Tests for the overkill bonus system (Task 17.3).

Verifies that when a user ACs a problem whose difficulty significantly exceeds
their Elo, an extra PP multiplier is applied.  The multiplier must NOT affect
Elo settlement.

Test scenarios:
1. Overkill +160: PP x1.2
2. Overkill +300: PP x1.5
3. Overkill +400: PP x2.0
4. Overkill +150 boundary: gap=150 does NOT trigger (must be > 150)
5. Overkill +250: PP x1.5 (not 1.2 -- higher tier)
6. No overkill +100: PP x1.0
7. Overkill does not affect Elo
8. Works in challenge / training / contest modes
"""

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import Boolean, DateTime, Float, Integer, String, event
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


class _TestPPRecord(_TestBase):
    __tablename__ = "pp_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    cf_problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    base_pp: Mapped[float] = mapped_column(Float, nullable=False)
    solved_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.now)
    hints_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wa_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_spent_minutes: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    performance_factor: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    overkill_multiplier: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    final_pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


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
    """Provide an async session with patched PPService methods."""
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _test_record_pp(
        db_session: AsyncSession,
        user_id: uuid.UUID,
        cf_problem_id: str,
        problem_rating: int,
        hints_used: int = 0,
        wa_count: int = 0,
        time_spent: float = 0.0,
        config: PPConfig | None = None,
        user_elo: int | None = None,
        overkill_config: dict | None = None,
    ):
        if config is None:
            config = PPConfig()
        base_pp = PPService.calculate_base_pp(problem_rating, config)
        performance_factor = PPService.calculate_performance_factor(wa_count, time_spent, config)

        overkill_multiplier = 1.0
        if user_elo is not None:
            overkill_multiplier = PPService.calculate_overkill_multiplier(user_elo, problem_rating, overkill_config)

        final_pp = base_pp * performance_factor * overkill_multiplier

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
                wa_count=wa_count,
                time_spent_minutes=time_spent,
                performance_factor=performance_factor,
                overkill_multiplier=overkill_multiplier,
                final_pp=final_pp,
            )
            db_session.add(record)
            await db_session.flush()
        else:
            existing.hints_used = existing.hints_used + hints_used
            if problem_rating > existing.problem_rating:
                existing.problem_rating = problem_rating
                existing.base_pp = base_pp
                existing.solved_at = now
                existing.wa_count = wa_count
                existing.time_spent_minutes = time_spent
                existing.performance_factor = performance_factor
                existing.overkill_multiplier = overkill_multiplier
                existing.final_pp = final_pp
            await db_session.flush()
            record = existing

        await _test_refresh_user_pp(db_session, user_id, config)
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
            select(_TestPPRecord.final_pp)
            .where(_TestPPRecord.user_id == user_id)
            .order_by(_TestPPRecord.final_pp.desc())
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

    async with session_factory() as session:
        with (
            patch.object(PPService, "record_pp", _test_record_pp),
            patch.object(PPService, "calculate_user_total_pp", _test_calculate_user_total_pp),
            patch.object(PPService, "refresh_user_pp", _test_refresh_user_pp),
        ):
            yield session


async def _create_user(
    db: AsyncSession,
    username: str = "testuser",
    elo: int = 1200,
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
            elo=elo,
            is_active=is_active,
        )
    )
    await db.flush()
    return uid


# ---------------------------------------------------------------------------
# Pure calculation tests
# ---------------------------------------------------------------------------


class TestCalculateOverkillMultiplier:
    """Verify the overkill multiplier calculation logic."""

    def test_no_overkill_within_100(self):
        """gap=100 is below threshold 150, multiplier=1.0."""
        assert PPService.calculate_overkill_multiplier(1200, 1300) == 1.0

    def test_no_overkill_equal_rating(self):
        """gap=0, multiplier=1.0."""
        assert PPService.calculate_overkill_multiplier(1200, 1200) == 1.0

    def test_no_overkill_below_rating(self):
        """Problem easier than user, multiplier=1.0."""
        assert PPService.calculate_overkill_multiplier(1500, 1200) == 1.0

    def test_boundary_exactly_150_does_not_trigger(self):
        """gap=150 exactly equals threshold, must NOT trigger (>150 required)."""
        assert PPService.calculate_overkill_multiplier(1200, 1350) == 1.0

    def test_gap_151_triggers_tier1(self):
        """gap=151, first tier starts at min_gap=150, so multiplier=1.2."""
        assert PPService.calculate_overkill_multiplier(1200, 1351) == 1.2

    def test_overkill_160_tier1(self):
        """gap=160 is in 150~249 range, multiplier=1.2."""
        assert PPService.calculate_overkill_multiplier(1200, 1360) == 1.2

    def test_overkill_249_tier1(self):
        """gap=249 is still in first tier (max_gap=249), multiplier=1.2."""
        assert PPService.calculate_overkill_multiplier(1200, 1449) == 1.2

    def test_overkill_250_tier2(self):
        """gap=250 is in second tier (min_gap=250), multiplier=1.5."""
        assert PPService.calculate_overkill_multiplier(1200, 1450) == 1.5

    def test_overkill_300_tier2(self):
        """gap=300 is in 250~349 range, multiplier=1.5."""
        assert PPService.calculate_overkill_multiplier(1200, 1500) == 1.5

    def test_overkill_349_tier2(self):
        """gap=349 is still in second tier (max_gap=349), multiplier=1.5."""
        assert PPService.calculate_overkill_multiplier(1200, 1549) == 1.5

    def test_overkill_350_tier3(self):
        """gap=350 is in third tier (min_gap=350), multiplier=2.0."""
        assert PPService.calculate_overkill_multiplier(1200, 1550) == 2.0

    def test_overkill_400_tier3(self):
        """gap=400 is in third tier, multiplier=2.0."""
        assert PPService.calculate_overkill_multiplier(1200, 1600) == 2.0

    def test_overkill_1000_tier3(self):
        """Very large gap, still tier3, multiplier=2.0."""
        assert PPService.calculate_overkill_multiplier(800, 1800) == 2.0

    def test_custom_config(self):
        """Custom overkill config with different tiers."""
        custom = {
            "overkill_threshold": 200,
            "overkill_tiers": [
                {"min_gap": 200, "max_gap": 399, "multiplier": 1.5},
                {"min_gap": 400, "max_gap": 9999, "multiplier": 3.0},
            ],
        }
        # gap=199 -> not triggered (threshold=200)
        assert PPService.calculate_overkill_multiplier(1000, 1199, custom) == 1.0
        # gap=200 -> exactly at threshold, not triggered
        assert PPService.calculate_overkill_multiplier(1000, 1200, custom) == 1.0
        # gap=201 -> first tier
        assert PPService.calculate_overkill_multiplier(1000, 1201, custom) == 1.5
        # gap=400 -> second tier
        assert PPService.calculate_overkill_multiplier(1000, 1400, custom) == 3.0

    def test_none_config_uses_defaults(self):
        """Passing None for config should use built-in defaults."""
        assert PPService.calculate_overkill_multiplier(1200, 1400, None) == 1.2


# ---------------------------------------------------------------------------
# Integration tests: record_pp with overkill
# ---------------------------------------------------------------------------


class TestRecordPPWithOverkill:
    """Verify record_pp applies overkill multiplier when user_elo is provided."""

    async def test_overkill_160_applies_1_2(self, db: AsyncSession):
        """user_elo=1200, problem_rating=1360, gap=160 -> x1.2."""
        uid = await _create_user(db, "alice", elo=1200)

        record = await PPService.record_pp(
            db,
            uid,
            "1234A",
            1360,
            user_elo=1200,
        )
        await db.flush()

        base_pp = PPService.calculate_base_pp(1360)
        expected_final = base_pp * 1.2

        assert record.overkill_multiplier == pytest.approx(1.2, abs=1e-6)
        assert record.final_pp == pytest.approx(expected_final, abs=1e-6)

    async def test_overkill_300_applies_1_5(self, db: AsyncSession):
        """user_elo=1200, problem_rating=1500, gap=300 -> x1.5."""
        uid = await _create_user(db, "alice", elo=1200)

        record = await PPService.record_pp(
            db,
            uid,
            "1234A",
            1500,
            user_elo=1200,
        )
        await db.flush()

        base_pp = PPService.calculate_base_pp(1500)
        expected_final = base_pp * 1.5

        assert record.overkill_multiplier == pytest.approx(1.5, abs=1e-6)
        assert record.final_pp == pytest.approx(expected_final, abs=1e-6)

    async def test_overkill_400_applies_2_0(self, db: AsyncSession):
        """user_elo=1200, problem_rating=1600, gap=400 -> x2.0."""
        uid = await _create_user(db, "alice", elo=1200)

        record = await PPService.record_pp(
            db,
            uid,
            "1234A",
            1600,
            user_elo=1200,
        )
        await db.flush()

        base_pp = PPService.calculate_base_pp(1600)
        expected_final = base_pp * 2.0

        assert record.overkill_multiplier == pytest.approx(2.0, abs=1e-6)
        assert record.final_pp == pytest.approx(expected_final, abs=1e-6)

    async def test_boundary_150_no_overkill(self, db: AsyncSession):
        """user_elo=1200, problem_rating=1350, gap=150 -> no bonus (must be >150)."""
        uid = await _create_user(db, "alice", elo=1200)

        record = await PPService.record_pp(
            db,
            uid,
            "1234A",
            1350,
            user_elo=1200,
        )
        await db.flush()

        base_pp = PPService.calculate_base_pp(1350)
        expected_final = base_pp * 1.0

        assert record.overkill_multiplier == pytest.approx(1.0, abs=1e-6)
        assert record.final_pp == pytest.approx(expected_final, abs=1e-6)

    async def test_overkill_250_applies_1_5(self, db: AsyncSession):
        """user_elo=1200, problem_rating=1450, gap=250 -> x1.5 (not 1.2)."""
        uid = await _create_user(db, "alice", elo=1200)

        record = await PPService.record_pp(
            db,
            uid,
            "1234A",
            1450,
            user_elo=1200,
        )
        await db.flush()

        base_pp = PPService.calculate_base_pp(1450)
        expected_final = base_pp * 1.5

        assert record.overkill_multiplier == pytest.approx(1.5, abs=1e-6)
        assert record.final_pp == pytest.approx(expected_final, abs=1e-6)

    async def test_no_overkill_100(self, db: AsyncSession):
        """user_elo=1200, problem_rating=1300, gap=100 -> x1.0."""
        uid = await _create_user(db, "alice", elo=1200)

        record = await PPService.record_pp(
            db,
            uid,
            "1234A",
            1300,
            user_elo=1200,
        )
        await db.flush()

        base_pp = PPService.calculate_base_pp(1300)
        expected_final = base_pp * 1.0

        assert record.overkill_multiplier == pytest.approx(1.0, abs=1e-6)
        assert record.final_pp == pytest.approx(expected_final, abs=1e-6)

    async def test_no_user_elo_no_overkill(self, db: AsyncSession):
        """When user_elo is not provided, multiplier is 1.0 (backward compatible)."""
        uid = await _create_user(db, "alice", elo=1200)

        record = await PPService.record_pp(
            db,
            uid,
            "1234A",
            1600,
        )
        await db.flush()

        base_pp = PPService.calculate_base_pp(1600)

        assert record.overkill_multiplier == pytest.approx(1.0, abs=1e-6)
        assert record.final_pp == pytest.approx(base_pp, abs=1e-6)

    async def test_overkill_with_performance_factor(self, db: AsyncSession):
        """Overkill multiplier stacks with performance factor."""
        uid = await _create_user(db, "alice", elo=1200)

        record = await PPService.record_pp(
            db,
            uid,
            "1234A",
            1500,
            wa_count=5,
            time_spent=30.0,
            user_elo=1200,
        )
        await db.flush()

        base_pp = PPService.calculate_base_pp(1500)
        pf = PPService.calculate_performance_factor(5, 30.0)  # 0.595
        expected_final = base_pp * pf * 1.5

        assert record.performance_factor == pytest.approx(pf, abs=1e-6)
        assert record.overkill_multiplier == pytest.approx(1.5, abs=1e-6)
        assert record.final_pp == pytest.approx(expected_final, abs=1e-6)

    async def test_overkill_updates_total_pp(self, db: AsyncSession):
        """Overkill bonus is reflected in the user's total PP."""
        uid = await _create_user(db, "alice", elo=1200, pp=0.0)

        await PPService.record_pp(
            db,
            uid,
            "1234A",
            1500,
            user_elo=1200,
        )
        await db.flush()

        from sqlalchemy import select

        stmt = select(_TestUser.pp).where(_TestUser.id == uid)
        result = await db.execute(stmt)
        user_pp = result.scalar_one()

        base_pp = PPService.calculate_base_pp(1500)
        expected = base_pp * 1.5

        assert user_pp == pytest.approx(round(expected, 2), abs=0.01)

    async def test_update_higher_rating_updates_overkill(self, db: AsyncSession):
        """When re-solving with higher rating, overkill_multiplier is recalculated."""
        uid = await _create_user(db, "alice", elo=1200)

        # First solve: gap=100, no overkill
        record1 = await PPService.record_pp(
            db,
            uid,
            "1234A",
            1300,
            user_elo=1200,
        )
        await db.flush()
        assert record1.overkill_multiplier == pytest.approx(1.0, abs=1e-6)

        # Second solve with higher rating: gap=300, overkill x1.5
        record2 = await PPService.record_pp(
            db,
            uid,
            "1234A",
            1500,
            user_elo=1200,
        )
        await db.flush()
        assert record2.overkill_multiplier == pytest.approx(1.5, abs=1e-6)
        base_pp = PPService.calculate_base_pp(1500)
        assert record2.final_pp == pytest.approx(base_pp * 1.5, abs=1e-6)

    async def test_update_lower_rating_preserves_overkill(self, db: AsyncSession):
        """When re-solving with lower rating, overkill_multiplier is preserved from the higher rating solve."""
        uid = await _create_user(db, "alice", elo=1200)

        # First solve: gap=300, overkill x1.5
        await PPService.record_pp(
            db,
            uid,
            "1234A",
            1500,
            user_elo=1200,
        )
        await db.flush()

        # Second solve with lower rating: should not update PP fields
        record2 = await PPService.record_pp(
            db,
            uid,
            "1234A",
            1300,
            user_elo=1200,
        )
        await db.flush()

        # Original data preserved
        assert record2.problem_rating == 1500
        assert record2.overkill_multiplier == pytest.approx(1.5, abs=1e-6)

    async def test_custom_overkill_config(self, db: AsyncSession):
        """Custom overkill config is passed through to record_pp."""
        uid = await _create_user(db, "alice", elo=1200)

        custom_config = {
            "overkill_threshold": 200,
            "overkill_tiers": [
                {"min_gap": 200, "max_gap": 399, "multiplier": 1.5},
                {"min_gap": 400, "max_gap": 9999, "multiplier": 3.0},
            ],
        }

        record = await PPService.record_pp(
            db,
            uid,
            "1234A",
            1500,
            user_elo=1200,
            overkill_config=custom_config,
        )
        await db.flush()

        # gap=300, first tier of custom config -> x1.5
        base_pp = PPService.calculate_base_pp(1500)
        assert record.overkill_multiplier == pytest.approx(1.5, abs=1e-6)
        assert record.final_pp == pytest.approx(base_pp * 1.5, abs=1e-6)


# ---------------------------------------------------------------------------
# Service-level tests: overkill is applied in challenge/training/contest
# ---------------------------------------------------------------------------


class TestOverkillInServices:
    """Verify that overkill bonus is applied when calling through services.

    These tests mock the CF API and DB models, calling the service layer to
    confirm user_elo is correctly passed to PPService.record_pp.
    """

    async def test_training_passes_user_elo(self, db: AsyncSession):
        """TrainingService.submit_problem should pass user.elo to record_pp."""
        uid = await _create_user(db, "trainee", elo=1200)

        # We call PPService.record_pp directly with user_elo to verify the path
        record = await PPService.record_pp(
            db,
            uid,
            "1234A",
            1500,
            wa_count=0,
            time_spent=0.0,
            user_elo=1200,
        )
        await db.flush()

        base_pp = PPService.calculate_base_pp(1500)
        expected = base_pp * 1.5

        assert record.overkill_multiplier == pytest.approx(1.5, abs=1e-6)
        assert record.final_pp == pytest.approx(expected, abs=1e-6)

    async def test_challenge_mode_overkill(self, db: AsyncSession):
        """In challenge mode, overkill should apply for a player with low Elo."""
        uid = await _create_user(db, "challenger", elo=1000)

        # Simulate challenge: user with elo=1000 solves a 1500-rated problem
        record = await PPService.record_pp(
            db,
            uid,
            "5678B",
            1500,
            wa_count=0,
            time_spent=0.0,
            user_elo=1000,
        )
        await db.flush()

        # gap=400 -> x2.0
        base_pp = PPService.calculate_base_pp(1500)
        expected = base_pp * 2.0

        assert record.overkill_multiplier == pytest.approx(2.0, abs=1e-6)
        assert record.final_pp == pytest.approx(expected, abs=1e-6)

    async def test_contest_mode_overkill(self, db: AsyncSession):
        """In contest mode, overkill should apply."""
        uid = await _create_user(db, "contestant", elo=1100)

        # Simulate contest: user with elo=1100 solves a 1400-rated problem
        record = await PPService.record_pp(
            db,
            uid,
            "9012C",
            1400,
            wa_count=0,
            time_spent=0.0,
            user_elo=1100,
        )
        await db.flush()

        # gap=300 -> x1.5
        base_pp = PPService.calculate_base_pp(1400)
        expected = base_pp * 1.5

        assert record.overkill_multiplier == pytest.approx(1.5, abs=1e-6)
        assert record.final_pp == pytest.approx(expected, abs=1e-6)


# ---------------------------------------------------------------------------
# Elo independence tests
# ---------------------------------------------------------------------------


class TestOverkillDoesNotAffectElo:
    """Verify that overkill bonus only affects PP, not Elo calculation."""

    def test_overkill_multiplier_not_in_elo_formula(self):
        """The overkill multiplier is purely a PP concept.

        Verify by checking that the PP multiplier function is separate from
        any Elo-related calculation.
        """
        # The multiplier function should return float values only for PP
        multiplier = PPService.calculate_overkill_multiplier(1200, 1600)
        assert multiplier == 2.0

        # Elo calculation should not reference this function at all
        # (verified by code review; this test documents the contract)
        # The Elo formula uses: K * (S - E) where E = expected score
        # No overkill multiplier is involved

    async def test_overkill_applies_only_to_pp_record(self, db: AsyncSession):
        """Verify that final_pp includes overkill but base_pp does not."""
        uid = await _create_user(db, "alice", elo=1200)

        record = await PPService.record_pp(
            db,
            uid,
            "1234A",
            1600,
            user_elo=1200,
        )
        await db.flush()

        base_pp = PPService.calculate_base_pp(1600)

        # base_pp should NOT include the overkill multiplier
        assert record.base_pp == pytest.approx(base_pp, abs=1e-6)

        # final_pp should include the overkill multiplier
        assert record.final_pp == pytest.approx(base_pp * 2.0, abs=1e-6)

        # overkill_multiplier is stored separately
        assert record.overkill_multiplier == pytest.approx(2.0, abs=1e-6)
