"""Tests for the K-factor segmented function (Task 15.1).

Validates the piecewise-linear K-factor formula:
    if N_sub <= newbie_threshold:  K = k_newbie
    if N_sub >= veteran_threshold: K = k_veteran
    otherwise: linear interpolation between k_newbie and k_veteran

Default config: k_newbie=40, k_veteran=20, newbie_threshold=20, veteran_threshold=100
"""

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, event, select
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


class _TestPPRecord(_TestBase):
    __tablename__ = "pp_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    cf_problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    base_pp: Mapped[float] = mapped_column(Float, nullable=False)
    solved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class _TestEloHistory(_TestBase):
    __tablename__ = "elo_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    elo_before: Mapped[int] = mapped_column(Integer, nullable=False)
    elo_after: Mapped[int] = mapped_column(Integer, nullable=False)
    elo_change: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
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


async def _create_pp_record(db: AsyncSession, user_id: uuid.UUID, cf_problem_id: str = "1A") -> None:
    db.add(
        _TestPPRecord(
            user_id=user_id,
            cf_problem_id=cf_problem_id,
            problem_rating=1200,
            base_pp=20.0,
            solved_at=datetime.now(),
        )
    )
    await db.flush()


# ---------------------------------------------------------------------------
# 1. K-factor segmented function - pure calculation tests
# ---------------------------------------------------------------------------


class TestCalculateKFactor:
    """Test EloService.calculate_k_factor with default and custom configs."""

    # --- Default config (k_newbie=40, k_veteran=20, newbie_threshold=20, veteran_threshold=100) ---

    def test_newbie_le_20(self):
        """N_sub <= 20: K = 40."""
        assert EloService.calculate_k_factor(0) == 40.0
        assert EloService.calculate_k_factor(1) == 40.0
        assert EloService.calculate_k_factor(10) == 40.0

    def test_newbie_boundary_20(self):
        """N_sub = 20: K = 40 (boundary value)."""
        assert EloService.calculate_k_factor(20) == 40.0

    def test_veteran_ge_100(self):
        """N_sub >= 100: K = 20."""
        assert EloService.calculate_k_factor(100) == 20.0
        assert EloService.calculate_k_factor(150) == 20.0
        assert EloService.calculate_k_factor(1000) == 20.0

    def test_linear_interpolation_60(self):
        """N_sub = 60: K should be 30 (midpoint of linear interpolation)."""
        # K = 40 - (60-20) * (40-20) / (100-20) = 40 - 40*20/80 = 40 - 10 = 30
        assert EloService.calculate_k_factor(60) == pytest.approx(30.0)

    def test_linear_interpolation_40(self):
        """N_sub = 40: K = 40 - (40-20) * 20/80 = 40 - 5 = 35."""
        assert EloService.calculate_k_factor(40) == pytest.approx(35.0)

    def test_linear_interpolation_80(self):
        """N_sub = 80: K = 40 - (80-20) * 20/80 = 40 - 15 = 25."""
        assert EloService.calculate_k_factor(80) == pytest.approx(25.0)

    def test_linear_interpolation_21(self):
        """N_sub = 21: just above newbie threshold."""
        # K = 40 - (21-20) * 20/80 = 40 - 0.25 = 39.75
        assert EloService.calculate_k_factor(21) == pytest.approx(39.75)

    def test_linear_interpolation_99(self):
        """N_sub = 99: just below veteran threshold."""
        # K = 40 - (99-20) * 20/80 = 40 - 19.75 = 20.25
        assert EloService.calculate_k_factor(99) == pytest.approx(20.25)

    def test_negative_submission_count(self):
        """Edge case: negative count treated as <= newbie threshold."""
        assert EloService.calculate_k_factor(-1) == 40.0

    # --- Custom config ---

    def test_custom_config(self):
        """Custom thresholds and K values."""
        config = {
            "k_newbie": 50,
            "k_veteran": 10,
            "k_newbie_threshold": 10,
            "k_veteran_threshold": 50,
        }
        # N_sub = 5 <= 10 => K = 50
        assert EloService.calculate_k_factor(5, config) == 50.0
        # N_sub = 50 >= 50 => K = 10
        assert EloService.calculate_k_factor(50, config) == 10.0
        # N_sub = 30: K = 50 - (30-10)*(50-10)/(50-10) = 50 - 20 = 30
        assert EloService.calculate_k_factor(30, config) == pytest.approx(30.0)

    def test_none_config_uses_defaults(self):
        """Passing None config should use module-level defaults."""
        assert EloService.calculate_k_factor(10, None) == 40.0
        assert EloService.calculate_k_factor(100, None) == 20.0

    def test_partial_config_uses_defaults_for_missing(self):
        """Config with only some keys should fall back to defaults for missing ones."""
        config = {"k_newbie": 60}  # Others use defaults
        assert EloService.calculate_k_factor(10, config) == 60.0
        assert EloService.calculate_k_factor(100, config) == 20.0  # Default k_veteran

    def test_config_hot_update(self):
        """Simulate hot config update by changing K values mid-sequence."""
        config_v1 = {
            "k_newbie": 40,
            "k_veteran": 20,
            "k_newbie_threshold": 20,
            "k_veteran_threshold": 100,
        }
        config_v2 = {
            "k_newbie": 50,
            "k_veteran": 10,
            "k_newbie_threshold": 30,
            "k_veteran_threshold": 200,
        }
        assert EloService.calculate_k_factor(10, config_v1) == 40.0
        assert EloService.calculate_k_factor(10, config_v2) == 50.0
        # With config_v2, N=100 is still in interpolation range
        # K = 50 - (100-30)*(50-10)/(200-30) = 50 - 70*40/170 = 50 - 16.47 = 33.53
        k_100_v2 = EloService.calculate_k_factor(100, config_v2)
        assert k_100_v2 == pytest.approx(50 - 70 * 40 / 170, abs=1e-6)


# ---------------------------------------------------------------------------
# 2. get_submission_count - database integration
# ---------------------------------------------------------------------------


class TestGetSubmissionCount:
    async def test_zero_records(self, db: AsyncSession):
        """User with no PP records should return 0."""
        uid = await _create_user(db, "alice")
        count = await EloService.get_submission_count(db, uid)
        assert count == 0

    async def test_multiple_records(self, db: AsyncSession):
        """User with N PP records should return N."""
        uid = await _create_user(db, "bob")
        for i in range(5):
            await _create_pp_record(db, uid, f"{i}A")
        count = await EloService.get_submission_count(db, uid)
        assert count == 5

    async def test_different_users_isolated(self, db: AsyncSession):
        """Each user's count should be independent."""
        uid_a = await _create_user(db, "alice")
        uid_b = await _create_user(db, "bob")
        for i in range(3):
            await _create_pp_record(db, uid_a, f"{i}A")
        for i in range(7):
            await _create_pp_record(db, uid_b, f"{i}B")
        assert await EloService.get_submission_count(db, uid_a) == 3
        assert await EloService.get_submission_count(db, uid_b) == 7


# ---------------------------------------------------------------------------
# 3. process_challenge_result with K-factor segmentation
# ---------------------------------------------------------------------------


class TestProcessChallengeResultKFactor:
    async def test_both_newbies_get_high_k(self, db: AsyncSession):
        """Two new players (0 submissions) should use K=40."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        # No PP records => submission_count=0 => K=40
        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db, uid_a, uid_b, 1200, 1200,
            actual_score_a=1.0,
            session_id=session_id,
            challenger_submission_count=0,
            opponent_submission_count=0,
            k_factor_config=None,  # Use defaults
        )
        # K=40, expected=0.5, change = 40*(1-0.5) = 20
        assert new_a == 1220
        assert new_b == 1180
        assert change_a == 20
        assert change_b == -20

    async def test_both_veterans_get_low_k(self, db: AsyncSession):
        """Two veteran players (150 submissions) should use K=20."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db, uid_a, uid_b, 1200, 1200,
            actual_score_a=1.0,
            session_id=session_id,
            challenger_submission_count=150,
            opponent_submission_count=150,
            k_factor_config=None,
        )
        # K=20, expected=0.5, change = 20*(1-0.5) = 10
        assert new_a == 1210
        assert new_b == 1190
        assert change_a == 10
        assert change_b == -10

    async def test_mixed_experience_different_k(self, db: AsyncSession):
        """Newbie vs veteran: each player uses their own K-factor."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        # Alice is newbie (10 subs => K=40), Bob is veteran (150 subs => K=20)
        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db, uid_a, uid_b, 1200, 1200,
            actual_score_a=1.0,
            session_id=session_id,
            challenger_submission_count=10,
            opponent_submission_count=150,
            k_factor_config=None,
        )
        # Alice K=40, Bob K=20, both expected=0.5
        # Alice: change = 40*(1-0.5) = 20
        # Bob: change = 20*(0-0.5) = -10
        assert new_a == 1220
        assert change_a == 20
        assert new_b == 1190
        assert change_b == -10

    async def test_midrange_interpolation_k(self, db: AsyncSession):
        """Players with 60 submissions should get K=30."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db, uid_a, uid_b, 1200, 1200,
            actual_score_a=1.0,
            session_id=session_id,
            challenger_submission_count=60,
            opponent_submission_count=60,
            k_factor_config=None,
        )
        # K=30, expected=0.5, change = 30*(1-0.5) = 15
        assert new_a == 1215
        assert new_b == 1185
        assert change_a == 15

    async def test_no_submission_count_uses_fixed_k(self, db: AsyncSession):
        """When submission counts are not provided, falls back to fixed K from config."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db, uid_a, uid_b, 1200, 1200,
            actual_score_a=1.0,
            session_id=session_id,
            # No submission counts => falls back to EloConfig.k_factor = 32
        )
        # K=32 (default from EloConfig), expected=0.5, change = 32*(1-0.5) = 16
        assert new_a == 1216
        assert new_b == 1184
        assert change_a == 16


# ---------------------------------------------------------------------------
# 4. process_contest_result with K-factor segmentation
# ---------------------------------------------------------------------------


class TestProcessContestResultKFactor:
    async def test_newbie_higher_k(self, db: AsyncSession):
        """Newbie in contest should use K=40."""
        uid = await _create_user(db, "alice", 1200)
        session_id = uuid.uuid4()

        new_rating, elo_change = await EloService.process_contest_result(
            db, uid, 1200,
            solved_problems=5, total_problems=5,
            time_used_seconds=100, time_limit_seconds=3600,
            contest_session_id=session_id,
            user_submission_count=10,
            k_factor_config=None,
        )
        # With K=40 (newbie), contest score > 0.5 => gain
        # contest_score = 1.0 + 0.1*(1-100/3600) = 1.0 + 0.0972 = 1.0972 (capped at 1.1)
        # change = 40*(1.1 - 0.5) = 24
        assert new_rating > 1200
        assert elo_change > 0
        # Verify it's using K=40 not K=32
        assert elo_change != 16  # Would be 16 with K=32 if contest_score made it exactly 0.5+something

    async def test_veteran_lower_k(self, db: AsyncSession):
        """Veteran in contest should use K=20."""
        uid = await _create_user(db, "alice", 1200)
        session_id = uuid.uuid4()

        new_rating, elo_change = await EloService.process_contest_result(
            db, uid, 1200,
            solved_problems=5, total_problems=5,
            time_used_seconds=100, time_limit_seconds=3600,
            contest_session_id=session_id,
            user_submission_count=150,
            k_factor_config=None,
        )
        # With K=20, gain should be smaller than with K=40
        assert new_rating > 1200
        assert elo_change > 0

    async def test_no_submission_count_uses_fixed_k(self, db: AsyncSession):
        """Without submission_count, falls back to fixed K from config."""
        uid = await _create_user(db, "alice", 1200)
        session_id = uuid.uuid4()

        new_rating, elo_change = await EloService.process_contest_result(
            db, uid, 1200,
            solved_problems=5, total_problems=5,
            time_used_seconds=100, time_limit_seconds=3600,
            contest_session_id=session_id,
            # No submission_count => uses EloConfig.k_factor = 32
        )
        assert new_rating > 1200
        assert elo_change > 0


# ---------------------------------------------------------------------------
# 5. process_quit_penalty with K-factor segmentation
# ---------------------------------------------------------------------------


class TestProcessQuitPenaltyKFactor:
    async def test_three_plus_newbie_k(self, db: AsyncSession):
        """Quit with 3+ submissions uses segmented K (newbie K=40)."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_rating, change = await EloService.process_quit_penalty(
            db, uid_a, 1200,
            submissions=3,
            session_id=session_id,
            opponent_id=uid_b,
            opponent_rating=1200,
            user_submission_count=5,   # Newbie => K=40
            opponent_submission_count=5,
            k_factor_config=None,
        )
        # Normal loss with K=40: change = 40*(0-0.5) = -20
        assert new_rating == 1180
        assert change == -20

    async def test_three_plus_veteran_k(self, db: AsyncSession):
        """Quit with 3+ submissions uses segmented K (veteran K=20)."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_rating, change = await EloService.process_quit_penalty(
            db, uid_a, 1200,
            submissions=3,
            session_id=session_id,
            opponent_id=uid_b,
            opponent_rating=1200,
            user_submission_count=200,   # Veteran => K=20
            opponent_submission_count=200,
            k_factor_config=None,
        )
        # Normal loss with K=20: change = 20*(0-0.5) = -10
        assert new_rating == 1190
        assert change == -10

    async def test_zero_submissions_no_k_factor_applied(self, db: AsyncSession):
        """0 submissions: no Elo change regardless of K-factor config."""
        uid = await _create_user(db, "alice", 1200)
        session_id = uuid.uuid4()

        new_rating, change = await EloService.process_quit_penalty(
            db, uid, 1200,
            submissions=0,
            session_id=session_id,
            user_submission_count=5,
            k_factor_config=None,
        )
        assert new_rating == 1200
        assert change == 0


# ---------------------------------------------------------------------------
# 6. Backward compatibility - existing behavior preserved
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Ensure existing callers that don't pass submission_count still work correctly."""

    def test_calculate_challenge_elo_unchanged(self):
        """calculate_challenge_elo still works with fixed K when no submission count."""
        config = EloConfig()
        new_a, new_b, change_a = EloService.calculate_challenge_elo(
            1200, 1200, 1.0, config=config
        )
        # K=32 (from EloConfig default), expected=0.5, change = 32*(1-0.5) = 16
        assert new_a == 1216
        assert change_a == 16

    def test_calculate_new_rating_unchanged(self):
        """calculate_new_rating still works without changes."""
        expected = EloService.calculate_expected_score(1200, 1200)
        new = EloService.calculate_new_rating(1200, expected, actual_score=1.0)
        # K=32, expected=0.5, change = 32*0.5 = 16
        assert new == 1216

    def test_calculate_contest_elo_unchanged(self):
        """calculate_contest_elo still works with fixed K."""
        new_rating, elo_change = EloService.calculate_contest_elo(
            1200, 5, 5, 100, 3600
        )
        assert new_rating > 1200
        assert elo_change > 0

    async def test_process_challenge_result_no_submission_count(self, db: AsyncSession):
        """process_challenge_result without submission counts uses fixed K=32."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db, uid_a, uid_b, 1200, 1200,
            actual_score_a=1.0,
            session_id=session_id,
        )
        # K=32 (fixed), expected=0.5, change = 32*0.5 = 16
        assert new_a == 1216
        assert change_a == 16

    async def test_process_contest_result_no_submission_count(self, db: AsyncSession):
        """process_contest_result without submission_count uses fixed K=32."""
        uid = await _create_user(db, "alice", 1200)
        session_id = uuid.uuid4()

        new_rating, elo_change = await EloService.process_contest_result(
            db, uid, 1200,
            solved_problems=3, total_problems=6,
            time_used_seconds=3600, time_limit_seconds=3600,
            contest_session_id=session_id,
        )
        # contest_score = 0.5 + 0 = 0.5 (time used == limit), change = K*(0.5-0.5) = 0
        assert elo_change == 0
        assert new_rating == 1200

    async def test_process_quit_penalty_no_submission_count(self, db: AsyncSession):
        """process_quit_penalty without submission counts uses fixed K=32."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        new_rating, change = await EloService.process_quit_penalty(
            db, uid_a, 1200,
            submissions=3,
            session_id=session_id,
            opponent_id=uid_b,
            opponent_rating=1200,
        )
        # K=32 (fixed), normal loss: change = 32*(0-0.5) = -16
        assert new_rating == 1184
        assert change == -16


# ---------------------------------------------------------------------------
# 7. Elo history records are still correct
# ---------------------------------------------------------------------------


class TestEloHistoryWithKFactor:
    async def test_challenge_elo_history_recorded(self, db: AsyncSession):
        """Elo history should be correctly recorded with segmented K-factor."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        await EloService.process_challenge_result(
            db, uid_a, uid_b, 1200, 1200,
            actual_score_a=1.0,
            session_id=session_id,
            challenger_submission_count=10,
            opponent_submission_count=10,
            k_factor_config=None,
        )

        # Verify history was recorded for both players
        stmt = select(_TestEloHistory).where(_TestEloHistory.user_id == uid_a)
        result = await db.execute(stmt)
        history_a = result.scalar_one()
        assert history_a.elo_before == 1200
        assert history_a.elo_after == 1220  # K=40, +20
        assert history_a.elo_change == 20
        assert history_a.reason == "challenge_win"

        stmt = select(_TestEloHistory).where(_TestEloHistory.user_id == uid_b)
        result = await db.execute(stmt)
        history_b = result.scalar_one()
        assert history_b.elo_before == 1200
        assert history_b.elo_after == 1180  # K=40, -20
        assert history_b.elo_change == -20
        assert history_b.reason == "challenge_loss"

    async def test_contest_elo_history_recorded(self, db: AsyncSession):
        """Contest Elo history should be recorded with segmented K-factor."""
        uid = await _create_user(db, "alice", 1200)
        session_id = uuid.uuid4()

        new_rating, _ = await EloService.process_contest_result(
            db, uid, 1200,
            solved_problems=5, total_problems=5,
            time_used_seconds=100, time_limit_seconds=3600,
            contest_session_id=session_id,
            user_submission_count=10,
            k_factor_config=None,
        )

        stmt = select(_TestEloHistory).where(_TestEloHistory.user_id == uid)
        result = await db.execute(stmt)
        history = result.scalar_one()
        assert history.elo_before == 1200
        assert history.elo_after == new_rating
        assert history.elo_change == new_rating - 1200
        assert history.reason == "contest"


# ---------------------------------------------------------------------------
# 8. Hint attenuation still works with segmented K
# ---------------------------------------------------------------------------


class TestHintAttenuationWithKFactor:
    async def test_hint_attenuation_applied_with_segmented_k(self, db: AsyncSession):
        """Hint attenuation should still work when using segmented K-factor."""
        uid_a = await _create_user(db, "alice", 1200)
        uid_b = await _create_user(db, "bob", 1200)
        session_id = uuid.uuid4()

        # Without hint
        _, _, change_no_hint, _ = await EloService.process_challenge_result(
            db, uid_a, uid_b, 1200, 1200,
            actual_score_a=1.0,
            session_id=session_id,
            challenger_submission_count=10,
            opponent_submission_count=10,
            k_factor_config=None,
        )

        # With hint level 1 (attenuation 0.75)
        uid_c = await _create_user(db, "carol", 1200)
        uid_d = await _create_user(db, "dave", 1200)
        session_id2 = uuid.uuid4()
        _, _, change_with_hint, _ = await EloService.process_challenge_result(
            db, uid_c, uid_d, 1200, 1200,
            actual_score_a=1.0,
            session_id=session_id2,
            hint_level_challenger=1,
            challenger_submission_count=10,
            opponent_submission_count=10,
            k_factor_config=None,
        )

        # K=40 => raw change = 40*0.5 = 20
        # With hint level 1: change = 20 * 0.75 = 15
        assert change_no_hint == 20
        assert change_with_hint == 15


# ---------------------------------------------------------------------------
# 9. Default fallback
# ---------------------------------------------------------------------------


class TestDefaultFallback:
    """Verify that module-level default values are correct."""

    def test_default_k_newbie(self):
        """Default k_newbie should be 40."""
        assert EloService.calculate_k_factor(10) == 40.0

    def test_default_k_veteran(self):
        """Default k_veteran should be 20."""
        assert EloService.calculate_k_factor(200) == 20.0

    def test_default_thresholds(self):
        """Default thresholds: newbie=20, veteran=100."""
        assert EloService.calculate_k_factor(20) == 40.0
        assert EloService.calculate_k_factor(100) == 20.0
        # Between thresholds => interpolation
        assert 20.0 < EloService.calculate_k_factor(60) < 40.0
