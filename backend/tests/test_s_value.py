"""Tests for the S-value grading system (Task 15.2).

Validates the S-value formula:
    Perfect AC (first attempt): S = 1.0
    Flawed AC (with errors):    S = max(0.7, 1.0 - 0.05 * N_errors)
    Not solved:                 S = 0.0

Covers:
- Pure S-value calculation (all boundary and edge cases)
- S-value integration in challenge settlement (PvP dual S-values)
- S-value integration in training settlement
- S-value integration in contest settlement
- Backward compatibility when S-values are not provided
"""

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.services.elo_service import EloReason, EloService

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
    solved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hints_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wa_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_spent_minutes: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    performance_factor: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    final_pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    overkill_multiplier: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)


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
    """Provide an async session with patched EloService methods for SQLite compatibility."""
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
# 1. Pure S-value calculation tests
# ---------------------------------------------------------------------------


class TestCalculateSValue:
    """Test EloService.calculate_s_value with all cases."""

    # --- Not solved ---

    def test_not_solved_returns_zero(self):
        """Unsolved problem always returns S=0.0."""
        assert EloService.calculate_s_value(is_solved=False, is_first_ac=False, error_count=0) == 0.0

    def test_not_solved_ignores_error_count(self):
        """Unsolved problem: error_count and is_first_ac are irrelevant."""
        assert EloService.calculate_s_value(is_solved=False, is_first_ac=True, error_count=5) == 0.0

    # --- Perfect AC (first attempt) ---

    def test_perfect_ac_first_attempt(self):
        """Solved on first attempt (submissions=1, errors=0): S=1.0."""
        assert EloService.calculate_s_value(is_solved=True, is_first_ac=True, error_count=0) == 1.0

    def test_perfect_ac_ignores_error_count_when_first_ac(self):
        """When is_first_ac=True, error_count is ignored -- always returns 1.0."""
        # This shouldn't happen in practice (is_first_ac implies 0 errors),
        # but the function should handle it correctly
        assert EloService.calculate_s_value(is_solved=True, is_first_ac=True, error_count=99) == 1.0

    # --- Flawed AC (with errors) ---

    def test_flawed_ac_1_error(self):
        """1 error: S = max(0.7, 1.0 - 0.05*1) = max(0.7, 0.95) = 0.95."""
        assert EloService.calculate_s_value(is_solved=True, is_first_ac=False, error_count=1) == pytest.approx(0.95)

    def test_flawed_ac_2_errors(self):
        """2 errors: S = max(0.7, 1.0 - 0.05*2) = max(0.7, 0.90) = 0.90."""
        assert EloService.calculate_s_value(is_solved=True, is_first_ac=False, error_count=2) == pytest.approx(0.90)

    def test_flawed_ac_3_errors(self):
        """3 errors: S = max(0.7, 1.0 - 0.05*3) = max(0.7, 0.85) = 0.85."""
        assert EloService.calculate_s_value(is_solved=True, is_first_ac=False, error_count=3) == pytest.approx(0.85)

    def test_flawed_ac_4_errors(self):
        """4 errors: S = max(0.7, 1.0 - 0.05*4) = max(0.7, 0.80) = 0.80."""
        assert EloService.calculate_s_value(is_solved=True, is_first_ac=False, error_count=4) == pytest.approx(0.80)

    def test_flawed_ac_5_errors(self):
        """5 errors: S = max(0.7, 1.0 - 0.05*5) = max(0.7, 0.75) = 0.75."""
        assert EloService.calculate_s_value(is_solved=True, is_first_ac=False, error_count=5) == pytest.approx(0.75)

    def test_flawed_ac_6_errors_hits_floor(self):
        """6 errors: S = max(0.7, 1.0 - 0.05*6) = max(0.7, 0.70) = 0.70."""
        assert EloService.calculate_s_value(is_solved=True, is_first_ac=False, error_count=6) == pytest.approx(0.70)

    def test_flawed_ac_10_errors_floor_protection(self):
        """10 errors: S = max(0.7, 1.0 - 0.05*10) = max(0.7, 0.50) = 0.70 (floor)."""
        assert EloService.calculate_s_value(is_solved=True, is_first_ac=False, error_count=10) == pytest.approx(0.70)

    def test_flawed_ac_100_errors_floor_protection(self):
        """100 errors: floor still protects at 0.70."""
        assert EloService.calculate_s_value(is_solved=True, is_first_ac=False, error_count=100) == pytest.approx(0.70)

    def test_flawed_ac_zero_errors_but_not_first(self):
        """Edge case: is_first_ac=False but error_count=0.
        This can happen if submissions=1 but the system couldn't confirm first-AC.
        S = max(0.7, 1.0 - 0) = 1.0."""
        assert EloService.calculate_s_value(is_solved=True, is_first_ac=False, error_count=0) == pytest.approx(1.0)

    def test_mixed_error_types_equal_weight(self):
        """All error types (WA/TLE/RE/MLE) are counted equally.
        Since calculate_s_value only takes a count, this is implicitly handled --
        the caller counts all non-AC submissions regardless of type."""
        # Simulate: 2 WA + 1 TLE + 1 RE = 4 errors total
        total_errors = 4
        s_val = EloService.calculate_s_value(is_solved=True, is_first_ac=False, error_count=total_errors)
        assert s_val == pytest.approx(0.80)

    # --- Return type ---

    def test_returns_float(self):
        """All results should be float type."""
        assert isinstance(EloService.calculate_s_value(False, False, 0), float)
        assert isinstance(EloService.calculate_s_value(True, True, 0), float)
        assert isinstance(EloService.calculate_s_value(True, False, 3), float)

    # --- S-value is in valid range ---

    def test_s_value_range(self):
        """S-value should always be in [0.0, 1.0]."""
        for errors in range(0, 20):
            s = EloService.calculate_s_value(True, False, errors)
            assert 0.0 <= s <= 1.0, f"S={s} out of range for errors={errors}"
        assert 0.0 <= EloService.calculate_s_value(False, False, 0) <= 1.0
        assert 0.0 <= EloService.calculate_s_value(True, True, 0) <= 1.0


# ---------------------------------------------------------------------------
# 2. S-value in challenge settlement (PvP dual S-values)
# ---------------------------------------------------------------------------


class TestChallengeSValue:
    """Test that S-values are used correctly in PvP challenge settlement."""

    async def test_both_perfect_ac(self, db: AsyncSession):
        """Both players have perfect AC: S_A=1.0, S_B=1.0.
        Challenger wins (faster time), actual_score_a=1.0.
        With S-values, both players' Elo changes are based on their own S-value
        vs their expected score. Since both have S=1.0, both gain Elo relative
        to the expected 0.5."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db,
            uid_a,
            uid_b,
            1200,
            1200,
            actual_score_a=1.0,
            session_id=session_id,
            challenger_submission_count=10,
            opponent_submission_count=10,
            s_value_challenger=1.0,
            s_value_opponent=1.0,
        )
        # K=40, expected_a=0.5, expected_b=0.5
        # Both have S=1.0: challenger change = 40*(1.0-0.5) = 20
        # Opponent also has S=1.0: opponent change = 40*(1.0-0.5) = 20
        assert new_a == 1220
        assert new_b == 1220
        assert change_a == 20
        assert change_b == 20

    async def test_challenger_flawed_ac(self, db: AsyncSession):
        """Challenger wins but with 2 errors (S=0.90), opponent lost (S=0.0).
        Challenger gets reduced Elo gain."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db,
            uid_a,
            uid_b,
            1200,
            1200,
            actual_score_a=1.0,
            session_id=session_id,
            challenger_submission_count=10,
            opponent_submission_count=10,
            s_value_challenger=0.90,  # 2 errors
            s_value_opponent=0.0,  # didn't solve
        )
        # Challenger: K=40, expected=0.5, change = 40*(0.90-0.5) = 16
        # Opponent: K=40, expected=0.5, change = 40*(0.0-0.5) = -20
        assert new_a == 1216
        assert change_a == 16
        assert new_b == 1180
        assert change_b == -20

    async def test_both_solved_challenger_flawed(self, db: AsyncSession):
        """Both solved. Challenger slower but also with errors.
        actual_score_a=0.0 (opponent won), but S-values are independent."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db,
            uid_a,
            uid_b,
            1200,
            1200,
            actual_score_a=0.0,  # opponent won
            session_id=session_id,
            challenger_submission_count=10,
            opponent_submission_count=10,
            s_value_challenger=0.80,  # 4 errors
            s_value_opponent=1.0,  # perfect AC
        )
        # Challenger (lost): K=40, expected=0.5, change = 40*(0.80-0.5) = 12
        # Wait -- challenger lost the match but had S=0.80 (they did solve, just slower)
        # The S-value affects the Elo magnitude, but actual_score_a determines win/loss
        # Actually, with S-values the formula uses S directly: change = K*(S - expected)
        # Challenger: 40*(0.80 - 0.5) = 12 (positive, even though they "lost" the match)
        # Opponent: 40*(1.0 - 0.5) = 20
        assert change_a == 12
        assert change_b == 20
        assert new_a == 1212
        assert new_b == 1220

    async def test_independent_s_values_asymmetric(self, db: AsyncSession):
        """Different Elo ratings with different S-values."""
        uid_a = await _create_user(db, "alice", 1500)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db,
            uid_a,
            uid_b,
            1500,
            1200,
            actual_score_a=1.0,
            session_id=session_id,
            challenger_submission_count=10,
            opponent_submission_count=10,
            s_value_challenger=0.85,  # 3 errors
            s_value_opponent=0.0,
        )
        # Expected: alice expected to win (higher Elo)
        # E_a = 1/(1+10^((1200-1500)/400)) = 1/(1+10^(-0.75)) = ~0.856
        expected_a = EloService.calculate_expected_score(1500, 1200)
        expected_b = 1.0 - expected_a
        # Challenger: 40*(0.85 - 0.856) = 40*(-0.006) = -0.24 => round to 0
        expected_change_a = round(40 * (0.85 - expected_a))
        # Opponent: 40*(0.0 - 0.144) = -5.76 => round to -6
        expected_change_b = round(40 * (0.0 - expected_b))
        assert change_a == expected_change_a
        assert change_b == expected_change_b

    async def test_no_s_values_backward_compatible(self, db: AsyncSession):
        """When S-values are not provided, behavior should be identical to before."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db,
            uid_a,
            uid_b,
            1200,
            1200,
            actual_score_a=1.0,
            session_id=session_id,
            challenger_submission_count=10,
            opponent_submission_count=10,
            # No s_value parameters
        )
        # K=40, expected=0.5, actual_score_a=1.0 => change = 40*(1.0-0.5) = 20
        assert new_a == 1220
        assert change_a == 20


# ---------------------------------------------------------------------------
# 3. S-value in contest settlement
# ---------------------------------------------------------------------------


class TestContestSValue:
    """Test S-value integration with contest score calculation."""

    def test_contest_score_with_s_values(self):
        """Contest score should use S-value weighting when provided."""
        # 5 problems total, solved 3 with S-values [1.0, 0.90, 0.80]
        s_values = [1.0, 0.90, 0.80]
        score = EloService.calculate_contest_score(
            solved_problems=3,
            total_problems=5,
            time_used_seconds=3600,  # full time used => no time bonus
            time_limit_seconds=3600,
            s_values=s_values,
        )
        # base_score = (1.0 + 0.90 + 0.80) / 5 = 2.70 / 5 = 0.54
        # time_used == limit => time_bonus = 0
        assert score == pytest.approx(0.54)

    def test_contest_score_without_s_values(self):
        """Contest score without S-values uses simple solved/total ratio."""
        score = EloService.calculate_contest_score(
            solved_problems=3,
            total_problems=5,
            time_used_seconds=3600,
            time_limit_seconds=3600,
            # No s_values
        )
        # base_score = 3/5 = 0.6, no time bonus
        assert score == pytest.approx(0.6)

    def test_contest_score_s_values_lower_than_binary(self):
        """S-values can lower the contest score compared to simple ratio."""
        # 3 solved, but with errors: S-values lower than 1.0
        s_values = [0.70, 0.70, 0.70]  # Each had many errors
        score_s = EloService.calculate_contest_score(
            solved_problems=3,
            total_problems=5,
            time_used_seconds=3600,
            time_limit_seconds=3600,
            s_values=s_values,
        )
        score_plain = EloService.calculate_contest_score(
            solved_problems=3,
            total_problems=5,
            time_used_seconds=3600,
            time_limit_seconds=3600,
        )
        # S-value score: 2.10/5 = 0.42 < 3/5 = 0.6
        assert score_s < score_plain

    def test_contest_score_all_perfect_ac(self):
        """All perfect ACs: S-values should match plain ratio."""
        s_values = [1.0, 1.0, 1.0]
        score_s = EloService.calculate_contest_score(
            solved_problems=3,
            total_problems=5,
            time_used_seconds=3600,
            time_limit_seconds=3600,
            s_values=s_values,
        )
        score_plain = EloService.calculate_contest_score(
            solved_problems=3,
            total_problems=5,
            time_used_seconds=3600,
            time_limit_seconds=3600,
        )
        assert score_s == pytest.approx(score_plain)

    def test_contest_elo_with_s_values(self):
        """calculate_contest_elo should use S-values."""
        s_values = [0.90, 0.80]  # 2 solved with errors
        new_rating, elo_change = EloService.calculate_contest_elo(
            current_rating=1200,
            solved_problems=2,
            total_problems=4,
            time_used_seconds=3600,
            time_limit_seconds=3600,
            s_values=s_values,
        )
        # base_score = (0.90+0.80)/4 = 1.70/4 = 0.425
        # expected = 0.5
        # change = K*(0.425 - 0.5) = 32*(-0.075) = -2.4 => round(-2) = -2
        assert new_rating == 1198
        assert elo_change == -2

    async def test_process_contest_result_with_s_values(self, db: AsyncSession):
        """process_contest_result should pass S-values through."""
        uid = await _create_user(db, "alice", 1200)
        session_id = uuid.uuid4()

        s_values = [1.0, 0.90]  # 2 solved, 1 perfect, 1 with 2 errors

        new_rating, elo_change = await EloService.process_contest_result(
            db,
            uid,
            1200,
            solved_problems=2,
            total_problems=4,
            time_used_seconds=3600,
            time_limit_seconds=3600,
            contest_session_id=session_id,
            s_values=s_values,
        )
        # base_score = (1.0+0.90)/4 = 0.475
        # expected = 0.5, K=32 (default from EloConfig)
        # change = 32*(0.475 - 0.5) = 32*(-0.025) = -0.8 => round to -1
        assert new_rating == 1199
        assert elo_change == -1

    async def test_process_contest_result_without_s_values(self, db: AsyncSession):
        """Without S-values, contest result should work as before."""
        uid = await _create_user(db, "alice", 1200)
        session_id = uuid.uuid4()

        new_rating, elo_change = await EloService.process_contest_result(
            db,
            uid,
            1200,
            solved_problems=2,
            total_problems=4,
            time_used_seconds=3600,
            time_limit_seconds=3600,
            contest_session_id=session_id,
            # No s_values
        )
        # base_score = 2/4 = 0.5, expected = 0.5, change = 0
        assert new_rating == 1200
        assert elo_change == 0

    def test_contest_score_empty_s_values(self):
        """Empty S-values list (no solved problems)."""
        score = EloService.calculate_contest_score(
            solved_problems=0,
            total_problems=5,
            time_used_seconds=3600,
            time_limit_seconds=3600,
            s_values=[],
        )
        assert score == pytest.approx(0.0)

    def test_contest_score_with_time_bonus_and_s_values(self):
        """Time bonus should be added on top of S-value base score."""
        s_values = [1.0, 1.0]
        score = EloService.calculate_contest_score(
            solved_problems=2,
            total_problems=5,
            time_used_seconds=100,
            time_limit_seconds=3600,
            s_values=s_values,
        )
        # base_score = 2.0/5 = 0.4
        # time_ratio = 100/3600 = 0.0278
        # time_bonus = 0.1 * (1 - 0.0278) = 0.0972
        # capped at 0.2 => 0.0972
        # total = 0.4 + 0.0972 = 0.4972
        assert score > 0.4  # Has time bonus
        assert score < 0.7  # Reasonable bound


# ---------------------------------------------------------------------------
# 4. S-value derivation from session data (integration scenarios)
# ---------------------------------------------------------------------------


class TestSValueDerivation:
    """Test deriving S-value parameters from session data as the services do."""

    def test_challenge_perfect_ac_submissions_1(self):
        """submissions=1 and solved: is_first_ac=True, error_count=0."""
        submissions = 1
        solved = True
        is_first_ac = solved and submissions <= 1
        error_count = max(0, submissions - 1) if solved else 0
        s = EloService.calculate_s_value(solved, is_first_ac, error_count)
        assert s == 1.0

    def test_challenge_flawed_ac_submissions_3(self):
        """submissions=3 and solved: is_first_ac=False, error_count=2."""
        submissions = 3
        solved = True
        is_first_ac = solved and submissions <= 1
        error_count = max(0, submissions - 1) if solved else 0
        s = EloService.calculate_s_value(solved, is_first_ac, error_count)
        assert s == pytest.approx(0.90)

    def test_challenge_not_solved(self):
        """Not solved: S=0.0 regardless of submissions."""
        submissions = 5
        solved = False
        is_first_ac = solved and submissions <= 1  # False (not solved)
        error_count = max(0, submissions - 1) if solved else 0  # 0 (not solved)
        s = EloService.calculate_s_value(solved, is_first_ac, error_count)
        assert s == 0.0

    def test_training_attempts_1(self):
        """Training: attempts=1 (first AC), error_count=0."""
        attempts = 1
        is_first_ac = attempts <= 1
        error_count = max(0, attempts - 1)
        s = EloService.calculate_s_value(True, is_first_ac, error_count)
        assert s == 1.0

    def test_training_attempts_7(self):
        """Training: attempts=7, error_count=6 => S = max(0.7, 0.70) = 0.70."""
        attempts = 7
        is_first_ac = attempts <= 1
        error_count = max(0, attempts - 1)
        s = EloService.calculate_s_value(True, is_first_ac, error_count)
        assert s == pytest.approx(0.70)

    def test_contest_problem_attempts_4(self):
        """Contest: one problem with attempts=4, error_count=3 => S=0.85."""
        attempts = 4
        is_first_ac = attempts <= 1
        error_count = max(0, attempts - 1)
        s = EloService.calculate_s_value(True, is_first_ac, error_count)
        assert s == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# 5. Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Ensure existing behavior is preserved when S-values are not used."""

    async def test_challenge_without_s_values(self, db: AsyncSession):
        """Challenge settlement without S-values matches original behavior."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_a, _, change_a, _ = await EloService.process_challenge_result(
            db,
            uid_a,
            uid_b,
            1200,
            1200,
            actual_score_a=1.0,
            session_id=session_id,
            challenger_submission_count=10,
            opponent_submission_count=10,
        )
        # K=40, expected=0.5, change = 40*(1.0-0.5) = 20
        assert change_a == 20

    async def test_contest_without_s_values(self, db: AsyncSession):
        """Contest settlement without S-values matches original behavior."""
        uid = await _create_user(db, "alice", 1200)
        session_id = uuid.uuid4()

        new_rating, elo_change = await EloService.process_contest_result(
            db,
            uid,
            1200,
            solved_problems=3,
            total_problems=6,
            time_used_seconds=3600,
            time_limit_seconds=3600,
            contest_session_id=session_id,
        )
        # base_score = 3/6 = 0.5, expected = 0.5, change = 0
        assert new_rating == 1200
        assert elo_change == 0

    async def test_quit_penalty_unaffected_by_s_values(self, db: AsyncSession):
        """Quit penalty should not involve S-values at all."""
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
            user_submission_count=10,
            opponent_submission_count=10,
        )
        # K=40, normal loss: change = 40*(0-0.5) = -20
        assert new_rating == 1180
        assert change == -20

    def test_calculate_contest_score_unchanged_without_s_values(self):
        """calculate_contest_score without S-values produces same result."""
        score = EloService.calculate_contest_score(3, 5, 100, 3600)
        assert score > 0.6  # base 0.6 + time bonus

    def test_calculate_new_rating_unchanged(self):
        """calculate_new_rating is unaffected by S-value feature."""
        expected = EloService.calculate_expected_score(1200, 1200)
        new = EloService.calculate_new_rating(1200, expected, actual_score=1.0)
        assert new == 1216


# ---------------------------------------------------------------------------
# 6. Reason labels unchanged
# ---------------------------------------------------------------------------


class TestReasonLabelsWithSValue:
    """Ensure Elo history reason labels still work correctly with S-values."""

    async def test_win_reason_with_s_value(self, db: AsyncSession):
        """Win reason should still be 'challenge_win' even with S < 1.0."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        await EloService.process_challenge_result(
            db,
            uid_a,
            uid_b,
            1200,
            1200,
            actual_score_a=1.0,
            session_id=session_id,
            challenger_submission_count=10,
            opponent_submission_count=10,
            s_value_challenger=0.85,
            s_value_opponent=0.0,
        )

        stmt = select(_TestEloHistory).where(_TestEloHistory.user_id == uid_a)
        result = await db.execute(stmt)
        history_a = result.scalar_one()
        assert history_a.reason == "challenge_win"

        stmt = select(_TestEloHistory).where(_TestEloHistory.user_id == uid_b)
        result = await db.execute(stmt)
        history_b = result.scalar_one()
        assert history_b.reason == "challenge_loss"

    async def test_draw_reason_with_s_values(self, db: AsyncSession):
        """Draw reason should still work when both have S-values."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        await EloService.process_challenge_result(
            db,
            uid_a,
            uid_b,
            1200,
            1200,
            actual_score_a=0.5,  # draw
            session_id=session_id,
            challenger_submission_count=10,
            opponent_submission_count=10,
            s_value_challenger=0.90,
            s_value_opponent=0.90,
        )

        stmt = select(_TestEloHistory).where(_TestEloHistory.user_id == uid_a)
        result = await db.execute(stmt)
        history_a = result.scalar_one()
        assert history_a.reason == "challenge_draw"


# ---------------------------------------------------------------------------
# 7. Hint attenuation with S-value
# ---------------------------------------------------------------------------


class TestHintAttenuationWithSValue:
    """Hint attenuation should work correctly when S-values are used."""

    async def test_hint_attenuation_reduces_gain_with_s_value(self, db: AsyncSession):
        """Hint attenuation should apply to S-value-based gains."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)

        # Without hint, S=0.90 (2 errors)
        session_id1 = uuid.uuid4()
        _, _, change_no_hint, _ = await EloService.process_challenge_result(
            db,
            uid_a,
            uid_b,
            1200,
            1200,
            actual_score_a=1.0,
            session_id=session_id1,
            challenger_submission_count=10,
            opponent_submission_count=10,
            s_value_challenger=0.90,
            s_value_opponent=0.0,
        )

        # With hint level 1, S=0.90
        uid_c = await _create_user(db, "carol", 1200)
        uid_d = await _create_user(db, "dave", 1200)
        session_id2 = uuid.uuid4()
        _, _, change_with_hint, _ = await EloService.process_challenge_result(
            db,
            uid_c,
            uid_d,
            1200,
            1200,
            actual_score_a=1.0,
            session_id=session_id2,
            hint_level_challenger=1,
            challenger_submission_count=10,
            opponent_submission_count=10,
            s_value_challenger=0.90,
            s_value_opponent=0.0,
        )

        # Without hint: 40*(0.90-0.5) = 16
        # With hint: 40*(0.90-0.5) = 16, then * 0.75 = 12
        assert change_no_hint == 16
        assert change_with_hint == 12

    async def test_hint_no_effect_on_loss_with_s_value(self, db: AsyncSession):
        """Hint attenuation should NOT apply when the Elo change is negative."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        _, _, change_a, _ = await EloService.process_challenge_result(
            db,
            uid_a,
            uid_b,
            1200,
            1200,
            actual_score_a=0.0,  # loss
            session_id=session_id,
            hint_level_challenger=2,
            challenger_submission_count=10,
            opponent_submission_count=10,
            s_value_challenger=0.0,
            s_value_opponent=1.0,
        )
        # Change should be negative: 40*(0.0-0.5) = -20
        # Hint attenuation should NOT apply to losses
        assert change_a == -20
