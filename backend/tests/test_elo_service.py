"""Tests for the Elo calculation engine.

All pure-calculation tests verify correctness against the mathematical formulas.
Integration-style tests that involve database writes use an in-memory SQLite
database with async sessions.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.services.elo_service import EloConfig, EloReason, EloService

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
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)


class _TestEloHistory(_TestBase):
    __tablename__ = "elo_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    elo_before: Mapped[int] = mapped_column(Integer, nullable=False)
    elo_after: Mapped[int] = mapped_column(Integer, nullable=False)
    elo_change: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    time_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> EloConfig:
    """Return a default EloConfig."""
    return EloConfig()


@pytest.fixture
def seeded_config() -> EloConfig:
    """Return a deterministic config with fixed quit penalty (no randomness)."""
    return EloConfig(
        k_factor=32.0,
        quit_penalty_min=-8,
        quit_penalty_max=-8,
        contest_time_bonus_factor=0.1,
        contest_time_bonus_cap=0.2,
    )


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

    The real EloService creates real EloHistory instances mapped to the
    production Base.  We patch ``record_elo_history`` and ``get_latest_elo``
    so they use our SQLite-compatible _TestEloHistory instead.
    """
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _test_record_elo_history(
        db_session: AsyncSession,
        user_id: uuid.UUID,
        elo_before: int,
        elo_after: int,
        reason: EloReason,
        reference_id: uuid.UUID | None = None,
    ):
        record = _TestEloHistory(
            user_id=user_id,
            elo_before=elo_before,
            elo_after=elo_after,
            elo_change=elo_after - elo_before,
            reason=reason.value,
            reference_id=reference_id,
        )
        db_session.add(record)
        await db_session.flush()
        return record

    async def _test_get_latest_elo(
        db_session: AsyncSession,
        user_id: uuid.UUID,
        fallback: int = 1200,
    ) -> int:
        from sqlalchemy import select

        stmt = (
            select(_TestEloHistory.elo_after)
            .where(_TestEloHistory.user_id == user_id)
            .order_by(_TestEloHistory.created_at.desc())
            .limit(1)
        )
        result = await db_session.execute(stmt)
        row = result.scalar_one_or_none()
        return row if row is not None else fallback

    async with session_factory() as session:
        with (
            patch.object(EloService, "record_elo_history", _test_record_elo_history),
            patch.object(EloService, "get_latest_elo", _test_get_latest_elo),
        ):
            yield session


async def _create_user(db: AsyncSession, username: str = "testuser", elo: int = 1200) -> uuid.UUID:
    """Helper: insert a _TestUser row directly and return the id."""
    uid = uuid.uuid4()
    db.add(
        _TestUser(
            id=uid,
            username=username,
            email=f"{username}@test.com",
            password_hash="hash",
            elo=elo,
        )
    )
    await db.flush()
    return uid


# ---------------------------------------------------------------------------
# 1. Expected score calculation
# ---------------------------------------------------------------------------


class TestExpectedScore:
    """Verify ``E_A = 1 / (1 + 10^((R_B - R_A) / 400))``."""

    def test_equal_ratings(self):
        assert EloService.calculate_expected_score(1200, 1200) == pytest.approx(0.5, abs=1e-6)

    def test_a_much_higher(self):
        """When A is 400 points higher, expected score should be ~0.909."""
        expected = 1.0 / (1.0 + 10.0 ** ((800 - 1200) / 400.0))
        assert EloService.calculate_expected_score(1200, 800) == pytest.approx(expected, abs=1e-10)

    def test_a_much_lower(self):
        expected = 1.0 / (1.0 + 10.0 ** ((1600 - 1200) / 400.0))
        assert EloService.calculate_expected_score(1200, 1600) == pytest.approx(expected, abs=1e-10)

    def test_symmetry(self):
        """E_A + E_B should sum to 1.0 when ratings are swapped."""
        e_ab = EloService.calculate_expected_score(1500, 1300)
        e_ba = EloService.calculate_expected_score(1300, 1500)
        assert e_ab + e_ba == pytest.approx(1.0, abs=1e-10)

    def test_formula_precision(self):
        """Cross-check against a hand-computed value."""
        # R_A=1800, R_B=1600 => exponent = (1600-1800)/400 = -0.5
        # 10^-0.5 = 0.316227766...
        # E = 1 / (1 + 0.316227766) = 0.759746926...
        result = EloService.calculate_expected_score(1800, 1600)
        expected = float(Decimal("1") / (Decimal("1") + Decimal("10") ** (Decimal("-0.5"))))
        assert result == pytest.approx(expected, abs=1e-6)


# ---------------------------------------------------------------------------
# 2. New rating calculation
# ---------------------------------------------------------------------------


class TestNewRating:
    def test_win_against_equal(self, config):
        expected = EloService.calculate_expected_score(1200, 1200)
        new = EloService.calculate_new_rating(1200, expected, actual_score=1.0, k_factor=config.k_factor)
        # 1200 + 32*(1 - 0.5) = 1200 + 16 = 1216
        assert new == 1216

    def test_loss_against_equal(self, config):
        expected = EloService.calculate_expected_score(1200, 1200)
        new = EloService.calculate_new_rating(1200, expected, actual_score=0.0, k_factor=config.k_factor)
        # 1200 + 32*(0 - 0.5) = 1200 - 16 = 1184
        assert new == 1184

    def test_draw_against_equal(self, config):
        expected = EloService.calculate_expected_score(1200, 1200)
        new = EloService.calculate_new_rating(1200, expected, actual_score=0.5, k_factor=config.k_factor)
        # 1200 + 32*(0.5 - 0.5) = 1200
        assert new == 1200

    def test_upset_win_gives_more(self, config):
        """Lower-rated player who beats a higher-rated player gains more."""
        expected_underdog = EloService.calculate_expected_score(1000, 1400)
        gain_underdog = EloService.calculate_new_rating(1000, expected_underdog, 1.0, config.k_factor) - 1000

        expected_favored = EloService.calculate_expected_score(1400, 1000)
        gain_favored = EloService.calculate_new_rating(1400, expected_favored, 1.0, config.k_factor) - 1400

        assert gain_underdog > gain_favored

    def test_custom_k_factor(self):
        new = EloService.calculate_new_rating(1200, 0.5, 1.0, k_factor=16)
        # 1200 + 16*(1-0.5) = 1208
        assert new == 1208


# ---------------------------------------------------------------------------
# 3. Challenge Elo (two-player)
# ---------------------------------------------------------------------------


class TestChallengeElo:
    def test_symmetric_draw(self, config):
        """A draw between equal-rated players changes nothing."""
        new_a, new_b, change_a = EloService.calculate_challenge_elo(1200, 1200, 0.5, config=config)
        assert new_a == 1200
        assert new_b == 1200
        assert change_a == 0

    def test_win_loss_roundtrip(self, config):
        """When A wins, A gains and B loses (equal ratings)."""
        new_a, new_b, change_a = EloService.calculate_challenge_elo(1200, 1200, 1.0, config=config)
        assert new_a > 1200
        assert new_b < 1200
        assert change_a > 0
        # Gains and losses should be symmetric for equal ratings
        assert (new_a - 1200) == -(new_b - 1200)

    def test_hint_no_effect_on_loss(self, config):
        """Hint attenuation must NOT reduce a loss."""
        _, _, change_no_hint = EloService.calculate_challenge_elo(1200, 1200, 0.0, config=config)
        _, _, change_with_hint = EloService.calculate_challenge_elo(1200, 1200, 0.0, hint_level=3, config=config)
        assert change_no_hint == change_with_hint  # Both negative, equal

    def test_hint_level_1_attenuates_gain(self, config):
        """Hint level 1 => Elo gain * 0.75."""
        new_a_raw, _, _ = EloService.calculate_challenge_elo(1200, 1200, 1.0, config=config)
        new_a_hint, _, _ = EloService.calculate_challenge_elo(1200, 1200, 1.0, hint_level=1, config=config)

        raw_gain = new_a_raw - 1200
        attenuated_gain = new_a_hint - 1200
        assert attenuated_gain == pytest.approx(raw_gain * 0.75, abs=1)

    def test_hint_level_2_attenuates_gain(self, config):
        new_a_raw, _, _ = EloService.calculate_challenge_elo(1200, 1200, 1.0, config=config)
        new_a_hint, _, _ = EloService.calculate_challenge_elo(1200, 1200, 1.0, hint_level=2, config=config)
        raw_gain = new_a_raw - 1200
        attenuated_gain = new_a_hint - 1200
        assert attenuated_gain == pytest.approx(raw_gain * 0.50, abs=1)

    def test_hint_level_3_attenuates_gain(self, config):
        new_a_raw, _, _ = EloService.calculate_challenge_elo(1200, 1200, 1.0, config=config)
        new_a_hint, _, _ = EloService.calculate_challenge_elo(1200, 1200, 1.0, hint_level=3, config=config)
        raw_gain = new_a_raw - 1200
        attenuated_gain = new_a_hint - 1200
        assert attenuated_gain == pytest.approx(raw_gain * 0.25, abs=1)

    def test_hint_zero_no_effect(self, config):
        new_a_0, _, _ = EloService.calculate_challenge_elo(1200, 1200, 1.0, hint_level=0, config=config)
        new_a_none, _, _ = EloService.calculate_challenge_elo(1200, 1200, 1.0, config=config)
        assert new_a_0 == new_a_none

    def test_formula_precision_full(self):
        """Cross-check entire flow against hand-computed values.

        R_A=1500, R_B=1600, actual=1, K=32, no hints.
        E_A = 1/(1+10^(100/400)) = 1/(1+10^0.25) = 0.359935...
        change = 32 * (1 - 0.359935) = 32 * 0.640065 = 20.482
        new_A = round(1500 + 20.482) = 1520
        """
        new_a, new_b, change_a = EloService.calculate_challenge_elo(1500, 1600, 1.0, k_factor=32.0, hint_level=0)
        e_a = 1.0 / (1.0 + 10.0 ** (100 / 400.0))
        expected_change = 32.0 * (1.0 - e_a)
        assert new_a == round(1500 + expected_change)
        assert change_a == round(expected_change)
        # B loses
        e_b = 1.0 - e_a
        expected_change_b = 32.0 * (0.0 - e_b)
        assert new_b == round(1600 + expected_change_b)


# ---------------------------------------------------------------------------
# 4. Quit penalty
# ---------------------------------------------------------------------------


class TestQuitPenalty:
    def test_zero_submissions_no_penalty(self, config):
        assert EloService.calculate_quit_penalty(0, config) == 0

    def test_one_submission_penalty_range(self, config):
        """Result must be in [-10, -5]."""
        for _ in range(50):
            penalty = EloService.calculate_quit_penalty(1, config)
            assert config.quit_penalty_min <= penalty <= config.quit_penalty_max

    def test_two_submissions_penalty_range(self, config):
        for _ in range(50):
            penalty = EloService.calculate_quit_penalty(2, config)
            assert config.quit_penalty_min <= penalty <= config.quit_penalty_max

    def test_three_plus_returns_sentinel(self, config):
        """3+ submissions => -1 sentinel (use normal loss)."""
        assert EloService.calculate_quit_penalty(3, config) == -1
        assert EloService.calculate_quit_penalty(5, config) == -1
        assert EloService.calculate_quit_penalty(100, config) == -1

    def test_seeded_config_deterministic(self, seeded_config):
        assert EloService.calculate_quit_penalty(1, seeded_config) == -8
        assert EloService.calculate_quit_penalty(2, seeded_config) == -8


# ---------------------------------------------------------------------------
# 5. Hint attenuation (standalone helper)
# ---------------------------------------------------------------------------


class TestHintAttenuation:
    def test_positive_gain_level1(self, config):
        assert EloService.apply_hint_attenuation(16.0, 1, config) == pytest.approx(12.0)

    def test_positive_gain_level2(self, config):
        assert EloService.apply_hint_attenuation(16.0, 2, config) == pytest.approx(8.0)

    def test_positive_gain_level3(self, config):
        assert EloService.apply_hint_attenuation(16.0, 3, config) == pytest.approx(4.0)

    def test_negative_change_unchanged(self, config):
        """Losses must NOT be attenuated."""
        assert EloService.apply_hint_attenuation(-10.0, 3, config) == -10.0

    def test_zero_change_unchanged(self, config):
        assert EloService.apply_hint_attenuation(0.0, 3, config) == 0.0

    def test_level_zero_unchanged(self, config):
        assert EloService.apply_hint_attenuation(16.0, 0, config) == 16.0

    def test_invalid_level_unchanged(self, config):
        """Level > 3 is not in config dict => attenuation factor is 0.0 (full suppression)."""
        result = EloService.apply_hint_attenuation(16.0, 4, config)
        assert result == 0.0


# ---------------------------------------------------------------------------
# 6. M-Elo (contest Elo)
# ---------------------------------------------------------------------------


class TestContestScore:
    def test_perfect_score_no_time(self, config):
        score = EloService.calculate_contest_score(5, 5, 0, 3600, config)
        # base = 1.0, time_bonus = 0.1 * (1-0) = 0.1, capped at 0.2
        assert score == pytest.approx(1.1, abs=1e-6)

    def test_half_solved_half_time(self, config):
        score = EloService.calculate_contest_score(3, 6, 1800, 3600, config)
        # base = 0.5, time_bonus = 0.1 * (1-0.5) = 0.05
        assert score == pytest.approx(0.55, abs=1e-6)

    def test_zero_solved(self, config):
        score = EloService.calculate_contest_score(0, 5, 1800, 3600, config)
        # base = 0.0, time_bonus = 0.05
        assert score == pytest.approx(0.05, abs=1e-6)

    def test_total_problems_zero(self, config):
        assert EloService.calculate_contest_score(0, 0, 100, 3600, config) == 0.0

    def test_time_bonus_capped(self, config):
        """Time bonus should not exceed the cap."""
        score = EloService.calculate_contest_score(1, 1, 0, 3600, config)
        # base=1.0, time_bonus = 0.1*(1-0)=0.1 <= 0.2 cap => score=1.1
        assert score == pytest.approx(1.1, abs=1e-6)

    def test_time_limit_zero(self, config):
        """When time limit is 0, time bonus is skipped."""
        score = EloService.calculate_contest_score(3, 5, 0, 0, config)
        assert score == pytest.approx(0.6, abs=1e-6)

    def test_time_used_exceeds_limit_clamped(self, config):
        score = EloService.calculate_contest_score(3, 5, 7200, 3600, config)
        # time_ratio clamped to 1.0 => time_bonus = 0.1*(1-1) = 0
        assert score == pytest.approx(0.6, abs=1e-6)


class TestContestElo:
    def test_above_average_gains(self, config):
        """Solving all problems quickly should yield a gain."""
        new_rating, change = EloService.calculate_contest_elo(1200, 5, 5, 100, 3600, config=config)
        assert new_rating > 1200
        assert change > 0

    def test_below_average_loses(self, config):
        """Solving nothing should yield a loss."""
        new_rating, change = EloService.calculate_contest_elo(1200, 0, 5, 3500, 3600, config=config)
        assert new_rating < 1200
        assert change < 0

    def test_exact_average(self, config):
        """Contest score == 0.5 => no change."""
        # base=0.5, time_bonus=0 => need solved/total = 0.5 and time_ratio such that bonus=0
        # solved=3, total=6, time_used=time_limit => time_bonus=0
        new_rating, change = EloService.calculate_contest_elo(1200, 3, 6, 3600, 3600, config=config)
        assert change == 0
        assert new_rating == 1200


# ---------------------------------------------------------------------------
# 7. Elo history persistence (integration)
# ---------------------------------------------------------------------------


class TestRecordEloHistory:
    async def test_record_created(self, db: AsyncSession):
        uid = await _create_user(db)
        record = await EloService.record_elo_history(db, uid, 1200, 1216, EloReason.CHALLENGE_WIN)
        await db.flush()

        assert record.user_id == uid
        assert record.elo_before == 1200
        assert record.elo_after == 1216
        assert record.elo_change == 16
        assert record.reason == "challenge_win"
        assert record.reference_id is None

    async def test_record_with_reference(self, db: AsyncSession):
        uid = await _create_user(db)
        ref_id = uuid.uuid4()
        record = await EloService.record_elo_history(db, uid, 1200, 1184, EloReason.CHALLENGE_LOSS, reference_id=ref_id)
        await db.flush()

        assert record.reference_id == ref_id
        assert record.reason == "challenge_loss"
        assert record.elo_change == -16


class TestProcessChallengeResult:
    async def test_win_loss_recorded(self, db: AsyncSession):
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db, uid_a, uid_b, 1200, 1200, actual_score_a=1.0, session_id=session_id
        )

        assert new_a == 1216
        assert new_b == 1184
        assert change_a == 16
        assert change_b == -16

    async def test_draw_no_change(self, db: AsyncSession):
        uid_a = await _create_user(db, "alice", 1300)
        uid_b = await _create_user(db, "bob", 1300)
        session_id = uuid.uuid4()

        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db, uid_a, uid_b, 1300, 1300, actual_score_a=0.5, session_id=session_id
        )
        assert change_a == 0
        assert change_b == 0


class TestProcessQuitPenalty:
    async def test_zero_submissions_no_change(self, db: AsyncSession):
        uid = await _create_user(db, "alice", 1200)
        session_id = uuid.uuid4()

        new_rating, change = await EloService.process_quit_penalty(db, uid, 1200, submissions=0, session_id=session_id)
        assert new_rating == 1200
        assert change == 0

    async def test_one_submission_penalty(self, db: AsyncSession, seeded_config):
        uid = await _create_user(db, "alice", 1200)
        session_id = uuid.uuid4()

        new_rating, change = await EloService.process_quit_penalty(
            db, uid, 1200, submissions=1, session_id=session_id, config=seeded_config
        )
        assert new_rating == 1192
        assert change == -8

    async def test_three_plus_normal_loss(self, db: AsyncSession, seeded_config):
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_rating, change = await EloService.process_quit_penalty(
            db,
            uid_a,
            1200,
            submissions=3,
            session_id=session_id,
            opponent_id=uid_b,
            opponent_rating=1200,
            config=seeded_config,
        )
        # Normal loss against equal-rated opponent => -16
        assert new_rating == 1184
        assert change == -16


class TestProcessContestResult:
    async def test_good_contest_gains(self, db: AsyncSession, seeded_config):
        uid = await _create_user(db, "alice", 1200)
        session_id = uuid.uuid4()

        new_rating, change = await EloService.process_contest_result(
            db, uid, 1200, 5, 5, 100, 3600, session_id, config=seeded_config
        )
        assert new_rating > 1200
        assert change > 0

    async def test_poor_contest_loses(self, db: AsyncSession, seeded_config):
        uid = await _create_user(db, "alice", 1200)
        session_id = uuid.uuid4()

        new_rating, change = await EloService.process_contest_result(
            db, uid, 1200, 0, 5, 3500, 3600, session_id, config=seeded_config
        )
        assert new_rating < 1200
        assert change < 0


# ---------------------------------------------------------------------------
# 8. Get latest Elo utility
# ---------------------------------------------------------------------------


class TestGetLatestElo:
    async def test_returns_fallback_when_no_history(self, db: AsyncSession):
        uid = uuid.uuid4()  # No user in DB, no history
        result = await EloService.get_latest_elo(db, uid, fallback=1000)
        assert result == 1000

    async def test_returns_latest_after_multiple(self, db: AsyncSession, seeded_config):
        uid = await _create_user(db, "alice", 1200)

        # Record two changes
        await EloService.record_elo_history(db, uid, 1200, 1216, EloReason.CHALLENGE_WIN)
        await db.flush()
        await EloService.record_elo_history(db, uid, 1216, 1200, EloReason.CHALLENGE_LOSS)
        await db.flush()

        result = await EloService.get_latest_elo(db, uid)
        assert result == 1200


# ---------------------------------------------------------------------------
# 9. Edge cases & boundary conditions
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_extreme_rating_difference(self, config):
        """Very large rating gap should still produce valid results."""
        new_a, new_b, _ = EloService.calculate_challenge_elo(500, 2500, 1.0, config=config)
        # The underdog winning should gain a lot
        assert new_a > 500
        gain = new_a - 500
        # Max gain with K=32 is 32 (when expected ≈ 0)
        assert gain <= 32
        # Favored player losing should lose a lot
        assert new_b < 2500

    def test_rating_near_zero_with_moderate_opponent(self, config):
        """A very low-rated player losing to a moderate opponent drops."""
        new_a, _, _ = EloService.calculate_challenge_elo(100, 500, 0.0, config=config)
        assert new_a < 100

    def test_hint_attenuation_only_positive(self, config):
        """Verify multiple times that hint only affects positive changes."""
        for actual_score in [0.0, 0.5]:
            _, _, no_hint = EloService.calculate_challenge_elo(1200, 1200, actual_score, hint_level=0, config=config)
            _, _, with_hint = EloService.calculate_challenge_elo(1200, 1200, actual_score, hint_level=3, config=config)
            assert no_hint == with_hint

    def test_contest_score_boundary_values(self, config):
        """All problems solved, maximum time used => time bonus = 0."""
        score = EloService.calculate_contest_score(5, 5, 3600, 3600, config)
        assert score == pytest.approx(1.0, abs=1e-6)

    async def test_process_quit_three_plus_requires_opponent(self, db: AsyncSession, seeded_config):
        """process_quit_penalty with 3+ submissions must raise if opponent info missing."""
        uid = await _create_user(db, "alice", 1200)
        session_id = uuid.uuid4()

        with pytest.raises(ValueError, match="opponent_id and opponent_rating are required"):
            await EloService.process_quit_penalty(
                db, uid, 1200, submissions=3, session_id=session_id, config=seeded_config
            )

    def test_default_config_values(self):
        cfg = EloConfig()
        assert cfg.k_factor == 32.0
        assert cfg.hint_attenuation == {1: 0.75, 2: 0.50, 3: 0.25}
        assert cfg.quit_penalty_min == -10
        assert cfg.quit_penalty_max == -5
        assert cfg.contest_time_bonus_factor == 0.1
        assert cfg.contest_time_bonus_cap == 0.2

    def test_elo_reason_enum_values(self):
        assert EloReason.CHALLENGE_WIN.value == "challenge_win"
        assert EloReason.CHALLENGE_LOSS.value == "challenge_loss"
        assert EloReason.CHALLENGE_DRAW.value == "challenge_draw"
        assert EloReason.QUIT_PENALTY.value == "quit_penalty"
        assert EloReason.CONTEST.value == "contest"
