"""Tests for the async submission tracking system.

Covers:
  1. register_pending: creating tracking records
  2. poll_submissions: CF API polling and matching
  3. match_and_update: verdict matching (final vs non-final)
  4. settle_matched: idempotent settlement dispatch
  5. handle_timeout: marking stale records
  6. get_tracking_for_session: session lookup
  7. _find_matching_submission: matching logic
  8. TaskScheduler: start/stop lifecycle
  9. _get_submission_stats: CF API stats extraction
  10. settle_matched with cf_service: real data passing
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import DateTime, Integer, String, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.services import submission_tracker as tracker_module
from app.services.submission_tracker import SubmissionTracker

# ---------------------------------------------------------------------------
# Lightweight SQLite-compatible test models
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _TestUser(_TestBase):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    cf_handle: Mapped[str | None] = mapped_column(String(100), nullable=True)
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)


class _TestSubmissionTracking(_TestBase):
    __tablename__ = "submission_tracking"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    session_type: Mapped[str] = mapped_column(String(20), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    cf_submission_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cf_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    expected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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
    """Provide an async session with patched model references."""
    session_factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False,
    )

    async with session_factory() as session:
        with (
            patch.object(tracker_module, "SubmissionTracking", _TestSubmissionTracking),
            patch.object(tracker_module, "User", _TestUser),
        ):
            yield session


def _make_user(
    user_id: uuid.UUID | None = None,
    cf_handle: str = "testhandle",
    elo: int = 1200,
) -> _TestUser:
    return _TestUser(
        id=user_id or uuid.uuid4(),
        username=f"user_{uuid.uuid4().hex[:6]}",
        cf_handle=cf_handle,
        elo=elo,
    )


def _make_tracking(
    user_id: uuid.UUID,
    session_type: str = "pve",
    session_id: uuid.UUID | None = None,
    problem_id: str = "800A",
    status: str = "pending",
    expected_at: datetime | None = None,
    cf_submission_id: int | None = None,
    cf_verdict: str | None = None,
    matched_at: datetime | None = None,
    created_at: datetime | None = None,
) -> _TestSubmissionTracking:
    return _TestSubmissionTracking(
        user_id=user_id,
        session_type=session_type,
        session_id=session_id or uuid.uuid4(),
        problem_id=problem_id,
        status=status,
        expected_at=expected_at or datetime.now(UTC),
        cf_submission_id=cf_submission_id,
        cf_verdict=cf_verdict,
        matched_at=matched_at,
        created_at=created_at or datetime.now(UTC),
    )


def _make_cf_submission(
    submission_id: int = 100,
    contest_id: int = 800,
    index: str = "A",
    verdict: str = "OK",
    creation_time: datetime | None = None,
) -> dict:
    """Build a CF API user.status submission dict."""
    ts = int(creation_time.timestamp()) if creation_time else int(datetime.now(UTC).timestamp())
    return {
        "id": submission_id,
        "contestId": contest_id,
        "problem": {"index": index},
        "verdict": verdict,
        "creationTimeSeconds": ts,
    }


# ---------------------------------------------------------------------------
# 1. register_pending tests
# ---------------------------------------------------------------------------


class TestRegisterPending:
    async def test_creates_pending_record(self, db):
        """register_pending should create a tracking record with status 'pending'."""
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        expected_at = datetime.now(UTC)

        record = await SubmissionTracker.register_pending(
            db=db,
            user_id=user_id,
            session_type="pve",
            session_id=session_id,
            problem_id="800A",
            expected_at=expected_at,
        )

        assert record.status == "pending"
        assert record.user_id == user_id
        assert record.session_id == session_id
        assert record.problem_id == "800A"
        assert record.session_type == "pve"

    async def test_multiple_registrations_for_same_session(self, db):
        """Should allow registering multiple tracking records."""
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()

        r1 = await SubmissionTracker.register_pending(
            db=db, user_id=user_id, session_type="pve",
            session_id=session_id, problem_id="800A",
            expected_at=datetime.now(UTC),
        )
        r2 = await SubmissionTracker.register_pending(
            db=db, user_id=user_id, session_type="pve",
            session_id=session_id, problem_id="800B",
            expected_at=datetime.now(UTC),
        )

        assert r1.id != r2.id
        assert r1.problem_id == "800A"
        assert r2.problem_id == "800B"


# ---------------------------------------------------------------------------
# 2. match_and_update tests
# ---------------------------------------------------------------------------


class TestMatchAndUpdate:
    async def test_final_verdict_transitions_to_matched(self, db):
        """A final verdict should transition tracking to 'matched'."""
        tracking = _make_tracking(user_id=uuid.uuid4(), status="pending")
        db.add(tracking)
        await db.flush()

        cf_sub = _make_cf_submission(verdict="OK")

        result = await SubmissionTracker.match_and_update(db, tracking, cf_sub)

        assert result is True
        assert tracking.status == "matched"
        assert tracking.cf_submission_id == 100
        assert tracking.cf_verdict == "OK"
        assert tracking.matched_at is not None

    async def test_non_final_verdict_stays_pending(self, db):
        """A non-final verdict (TESTING) should keep status as 'pending'."""
        tracking = _make_tracking(user_id=uuid.uuid4(), status="pending")
        db.add(tracking)
        await db.flush()

        cf_sub = _make_cf_submission(verdict="TESTING")

        result = await SubmissionTracker.match_and_update(db, tracking, cf_sub)

        assert result is False
        assert tracking.status == "pending"
        assert tracking.cf_submission_id == 100
        assert tracking.cf_verdict == "TESTING"

    async def test_null_verdict_stays_pending(self, db):
        """A null verdict (still running) should keep status as 'pending'."""
        tracking = _make_tracking(user_id=uuid.uuid4(), status="pending")
        db.add(tracking)
        await db.flush()

        cf_sub = _make_cf_submission(verdict=None)

        result = await SubmissionTracker.match_and_update(db, tracking, cf_sub)

        assert result is False
        assert tracking.status == "pending"

    async def test_all_final_verdicts_recognized(self, db):
        """All recognized final verdicts should transition to 'matched'."""
        final_verdicts = [
            "OK", "WRONG_ANSWER", "TIME_LIMIT_EXCEEDED",
            "MEMORY_LIMIT_EXCEEDED", "COMPILATION_ERROR",
            "RUNTIME_ERROR", "CHALLENGED", "SKIPPED",
        ]

        for verdict in final_verdicts:
            tracking = _make_tracking(user_id=uuid.uuid4(), status="pending")
            db.add(tracking)
            await db.flush()

            cf_sub = _make_cf_submission(verdict=verdict)
            result = await SubmissionTracker.match_and_update(db, tracking, cf_sub)

            assert result is True, f"Verdict '{verdict}' should be final"
            assert tracking.status == "matched"


# ---------------------------------------------------------------------------
# 3. _find_matching_submission tests
# ---------------------------------------------------------------------------


class TestFindMatchingSubmission:
    def test_matches_problem_id(self):
        """Should match submission with correct problem ID."""
        tracking = _make_tracking(
            user_id=uuid.uuid4(),
            problem_id="800A",
            expected_at=datetime.now(UTC),
        )

        submissions = [
            _make_cf_submission(contest_id=800, index="B"),  # Wrong problem
            _make_cf_submission(contest_id=800, index="A", verdict="OK"),  # Match
            _make_cf_submission(contest_id=900, index="A"),  # Wrong contest
        ]

        result = SubmissionTracker._find_matching_submission(tracking, submissions)
        assert result is not None
        assert result["verdict"] == "OK"

    def test_no_match_returns_none(self):
        """Should return None when no submission matches."""
        tracking = _make_tracking(
            user_id=uuid.uuid4(),
            problem_id="999Z",
            expected_at=datetime.now(UTC),
        )

        submissions = [
            _make_cf_submission(contest_id=800, index="A"),
        ]

        result = SubmissionTracker._find_matching_submission(tracking, submissions)
        assert result is None

    def test_time_window_filtering(self):
        """Should only match submissions within the time window."""
        now = datetime.now(UTC)
        # expected_at is 1 hour ago
        tracking = _make_tracking(
            user_id=uuid.uuid4(),
            problem_id="800A",
            expected_at=now - timedelta(hours=1),
        )

        # Submission from 3 hours ago -- outside 5min-before window
        old_sub = _make_cf_submission(
            contest_id=800, index="A",
            creation_time=now - timedelta(hours=3),
        )
        # Submission from 30 min ago -- within 30min-after window
        recent_sub = _make_cf_submission(
            submission_id=101, contest_id=800, index="A",
            creation_time=now - timedelta(minutes=30),
        )

        result = SubmissionTracker._find_matching_submission(tracking, [old_sub, recent_sub])
        assert result is not None
        assert result["id"] == 101

    def test_picks_most_recent_submission(self):
        """When multiple submissions match, pick the one with highest ID."""
        now = datetime.now(UTC)
        tracking = _make_tracking(
            user_id=uuid.uuid4(),
            problem_id="800A",
            expected_at=now,
        )

        subs = [
            _make_cf_submission(
                submission_id=100, contest_id=800, index="A",
                creation_time=now - timedelta(minutes=1),
            ),
            _make_cf_submission(
                submission_id=200, contest_id=800, index="A",
                creation_time=now,
            ),
            _make_cf_submission(
                submission_id=150, contest_id=800, index="A",
                creation_time=now - timedelta(seconds=30),
            ),
        ]

        result = SubmissionTracker._find_matching_submission(tracking, subs)
        assert result is not None
        assert result["id"] == 200

    def test_empty_submissions_list(self):
        """Should return None for empty submissions list."""
        tracking = _make_tracking(
            user_id=uuid.uuid4(),
            problem_id="800A",
            expected_at=datetime.now(UTC),
        )
        result = SubmissionTracker._find_matching_submission(tracking, [])
        assert result is None


# ---------------------------------------------------------------------------
# 4. poll_submissions tests (with mocked CF API)
# ---------------------------------------------------------------------------


class TestPollSubmissions:
    async def test_no_pending_records(self, db):
        """Should return 0 when no pending records exist."""
        cf_mock = AsyncMock()
        result = await SubmissionTracker.poll_submissions(db, cf_mock)
        assert result == 0
        cf_mock.get_user_status.assert_not_called()

    async def test_polls_for_user_with_cf_handle(self, db):
        """Should poll CF API for users with pending records and a CF handle."""
        user = _make_user(cf_handle="testhandle")
        db.add(user)
        await db.flush()

        tracking = _make_tracking(user_id=user.id, problem_id="800A")
        db.add(tracking)
        await db.flush()

        now = datetime.now(UTC)
        cf_sub = _make_cf_submission(
            contest_id=800, index="A", verdict="OK",
            creation_time=now,
        )
        cf_mock = AsyncMock()
        cf_mock.get_user_status.return_value = [cf_sub]

        matched = await SubmissionTracker.poll_submissions(db, cf_mock)
        assert matched == 1
        cf_mock.get_user_status.assert_called_once_with(handle="testhandle", count=50)

    async def test_skips_user_without_cf_handle(self, db):
        """Should skip users that have no CF handle."""
        user = _make_user(cf_handle=None)
        db.add(user)
        await db.flush()

        tracking = _make_tracking(user_id=user.id)
        db.add(tracking)
        await db.flush()

        cf_mock = AsyncMock()
        matched = await SubmissionTracker.poll_submissions(db, cf_mock)
        assert matched == 0
        cf_mock.get_user_status.assert_not_called()

    async def test_cf_api_error_continues(self, db):
        """Should continue if CF API fails for one user."""
        user = _make_user(cf_handle="testhandle")
        db.add(user)
        await db.flush()

        tracking = _make_tracking(user_id=user.id)
        db.add(tracking)
        await db.flush()

        cf_mock = AsyncMock()
        cf_mock.get_user_status.side_effect = Exception("CF API down")

        matched = await SubmissionTracker.poll_submissions(db, cf_mock)
        assert matched == 0

    async def test_multiple_users_polled(self, db):
        """Should poll CF API for each user with pending records."""
        user1 = _make_user(cf_handle="handle1")
        user2 = _make_user(cf_handle="handle2")
        db.add_all([user1, user2])
        await db.flush()

        t1 = _make_tracking(user_id=user1.id, problem_id="800A")
        t2 = _make_tracking(user_id=user2.id, problem_id="800B")
        db.add_all([t1, t2])
        await db.flush()

        cf_mock = AsyncMock()
        cf_mock.get_user_status.return_value = []  # No matching submissions

        matched = await SubmissionTracker.poll_submissions(db, cf_mock)
        assert matched == 0
        assert cf_mock.get_user_status.call_count == 2


# ---------------------------------------------------------------------------
# 5. settle_matched tests
# ---------------------------------------------------------------------------


class TestSettleMatched:
    async def test_no_matched_records(self, db):
        """Should return 0 when no matched records exist."""
        count = await SubmissionTracker.settle_matched(db)
        assert count == 0

    async def test_settles_pve_session(self, db):
        """Should settle a matched PvE tracking record."""
        user = _make_user()
        db.add(user)
        await db.flush()

        tracking = _make_tracking(
            user_id=user.id,
            session_type="pve",
            status="matched",
            cf_verdict="OK",
            matched_at=datetime.now(UTC),
        )
        db.add(tracking)
        await db.flush()

        # Mock the PvE settlement -- patch at the import location
        mock_submit = AsyncMock()
        with patch("app.services.pve_challenge_service.PvEChallengeService") as mock_pve:
            mock_pve.submit_result = mock_submit
            count = await SubmissionTracker.settle_matched(db)

        assert count == 1
        assert tracking.status == "settled"

    async def test_settlement_failure_leaves_as_matched(self, db):
        """If settlement raises, record should remain 'matched'."""
        user = _make_user()
        db.add(user)
        await db.flush()

        tracking = _make_tracking(
            user_id=user.id,
            session_type="pve",
            status="matched",
            cf_verdict="OK",
            matched_at=datetime.now(UTC),
        )
        db.add(tracking)
        await db.flush()

        with patch("app.services.pve_challenge_service.PvEChallengeService") as mock_pve:
            mock_pve.submit_result = AsyncMock(side_effect=Exception("Settlement error"))
            count = await SubmissionTracker.settle_matched(db)

        assert count == 0
        assert tracking.status == "matched"

    async def test_idempotent_no_double_settlement(self, db):
        """Already settled records should not be processed again."""
        user = _make_user()
        db.add(user)
        await db.flush()

        tracking = _make_tracking(
            user_id=user.id,
            session_type="pve",
            status="settled",
            cf_verdict="OK",
        )
        db.add(tracking)
        await db.flush()

        count = await SubmissionTracker.settle_matched(db)
        assert count == 0


# ---------------------------------------------------------------------------
# 6. handle_timeout tests
# ---------------------------------------------------------------------------


class TestHandleTimeout:
    async def test_marks_old_pending_as_timeout(self, db):
        """Pending records older than 2 hours should be marked as timeout."""
        user = _make_user()
        db.add(user)
        await db.flush()

        # expected_at is 3 hours ago
        old_tracking = _make_tracking(
            user_id=user.id,
            status="pending",
            expected_at=datetime.now(UTC) - timedelta(hours=3),
        )
        db.add(old_tracking)
        await db.flush()

        count = await SubmissionTracker.handle_timeout(db)
        assert count == 1

        await db.refresh(old_tracking)
        assert old_tracking.status == "timeout"

    async def test_recent_pending_not_timed_out(self, db):
        """Recent pending records should not be marked as timeout."""
        user = _make_user()
        db.add(user)
        await db.flush()

        recent_tracking = _make_tracking(
            user_id=user.id,
            status="pending",
            expected_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        db.add(recent_tracking)
        await db.flush()

        count = await SubmissionTracker.handle_timeout(db)
        assert count == 0

        await db.refresh(recent_tracking)
        assert recent_tracking.status == "pending"

    async def test_only_pending_records_affected(self, db):
        """Only pending records should be marked as timeout."""
        user = _make_user()
        db.add(user)
        await db.flush()

        matched_tracking = _make_tracking(
            user_id=user.id,
            status="matched",
            expected_at=datetime.now(UTC) - timedelta(hours=3),
        )
        db.add(matched_tracking)
        await db.flush()

        count = await SubmissionTracker.handle_timeout(db)
        assert count == 0

        await db.refresh(matched_tracking)
        assert matched_tracking.status == "matched"

    async def test_no_pending_records(self, db):
        """Should return 0 when no pending records exist."""
        count = await SubmissionTracker.handle_timeout(db)
        assert count == 0


# ---------------------------------------------------------------------------
# 7. get_tracking_for_session tests
# ---------------------------------------------------------------------------


class TestGetTrackingForSession:
    async def test_returns_matching_record(self, db):
        """Should return the tracking record for the given session."""
        user = _make_user()
        db.add(user)
        await db.flush()

        session_id = uuid.uuid4()
        tracking = _make_tracking(
            user_id=user.id,
            session_type="pve",
            session_id=session_id,
        )
        db.add(tracking)
        await db.flush()

        result = await SubmissionTracker.get_tracking_for_session(
            db, user.id, "pve", session_id,
        )
        assert result is not None
        assert result.id == tracking.id

    async def test_returns_none_when_not_found(self, db):
        """Should return None when no tracking record exists."""
        result = await SubmissionTracker.get_tracking_for_session(
            db, uuid.uuid4(), "pve", uuid.uuid4(),
        )
        assert result is None

    async def test_returns_most_recent(self, db):
        """Should return the most recent tracking record for a session."""
        user = _make_user()
        db.add(user)
        await db.flush()

        session_id = uuid.uuid4()
        old = _make_tracking(
            user_id=user.id, session_type="pve", session_id=session_id,
            status="timeout",
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
        recent = _make_tracking(
            user_id=user.id, session_type="pve", session_id=session_id,
            status="pending",
        )
        db.add_all([old, recent])
        await db.flush()

        result = await SubmissionTracker.get_tracking_for_session(
            db, user.id, "pve", session_id,
        )
        assert result is not None
        assert result.id == recent.id


# ---------------------------------------------------------------------------
# 8. TaskScheduler lifecycle tests
# ---------------------------------------------------------------------------


class TestTaskScheduler:
    async def test_start_and_stop(self):
        """Scheduler should start and stop cleanly."""
        from app.core.task_scheduler import TaskScheduler

        sched = TaskScheduler(poll_interval=1)
        assert not sched.running

        mock_app = MagicMock()
        sched.start(mock_app)
        assert sched.running
        assert sched._task is not None

        await sched.stop()

        assert not sched.running
        assert sched._task is None

    async def test_start_idempotent(self):
        """Calling start() twice should be a no-op."""
        from app.core.task_scheduler import TaskScheduler

        sched = TaskScheduler(poll_interval=60)
        mock_app = MagicMock()
        sched.start(mock_app)
        task = sched._task

        sched.start(mock_app)  # Should not create a new task
        assert sched._task is task

        await sched.stop()

    async def test_stop_when_not_running(self):
        """Stopping a non-running scheduler should be a no-op."""
        from app.core.task_scheduler import TaskScheduler

        sched = TaskScheduler()
        await sched.stop()
        assert not sched.running


# ---------------------------------------------------------------------------
# 9. Full flow integration test
# ---------------------------------------------------------------------------


class TestFullFlow:
    async def test_register_poll_match_settle_flow(self, db):
        """Test: register -> poll -> match -> settle full lifecycle."""
        user = _make_user(cf_handle="testcf")
        db.add(user)
        await db.flush()

        # Step 1: Register pending
        now = datetime.now(UTC)
        tracking = await SubmissionTracker.register_pending(
            db=db,
            user_id=user.id,
            session_type="pve",
            session_id=uuid.uuid4(),
            problem_id="800A",
            expected_at=now,
        )
        assert tracking.status == "pending"

        # Step 2: Poll CF API -- user submits and gets OK
        cf_sub = _make_cf_submission(
            contest_id=800, index="A", verdict="OK",
            creation_time=now,
        )
        cf_mock = AsyncMock()
        cf_mock.get_user_status.return_value = [cf_sub]

        matched = await SubmissionTracker.poll_submissions(db, cf_mock)
        assert matched == 1

        await db.refresh(tracking)
        assert tracking.status == "matched"
        assert tracking.cf_verdict == "OK"

        # Step 3: Settle matched
        with patch("app.services.pve_challenge_service.PvEChallengeService") as mock_pve:
            mock_pve.submit_result = AsyncMock()
            settled = await SubmissionTracker.settle_matched(db)

        assert settled == 1

        await db.refresh(tracking)
        assert tracking.status == "settled"

    async def test_register_timeout_flow(self, db):
        """Test: register -> wait -> timeout."""
        user = _make_user(cf_handle="testcf")
        db.add(user)
        await db.flush()

        # Register with expected_at far in the past
        old_time = datetime.now(UTC) - timedelta(hours=3)
        tracking = await SubmissionTracker.register_pending(
            db=db,
            user_id=user.id,
            session_type="pve",
            session_id=uuid.uuid4(),
            problem_id="800A",
            expected_at=old_time,
        )
        assert tracking.status == "pending"

        # Handle timeout
        timeout_count = await SubmissionTracker.handle_timeout(db)
        assert timeout_count == 1

        await db.refresh(tracking)
        assert tracking.status == "timeout"

    async def test_non_final_verdict_keeps_polling(self, db):
        """Non-final verdict should keep record as pending for next poll."""
        user = _make_user(cf_handle="testcf")
        db.add(user)
        await db.flush()

        now = datetime.now(UTC)
        tracking = _make_tracking(
            user_id=user.id,
            problem_id="800A",
            expected_at=now,
        )
        db.add(tracking)
        await db.flush()

        # First poll: TESTING verdict
        cf_sub_testing = _make_cf_submission(
            contest_id=800, index="A", verdict="TESTING",
            creation_time=now,
        )
        cf_mock = AsyncMock()
        cf_mock.get_user_status.return_value = [cf_sub_testing]

        matched = await SubmissionTracker.poll_submissions(db, cf_mock)
        assert matched == 0  # Not matched yet (TESTING is not final)

        await db.refresh(tracking)
        assert tracking.status == "pending"

        # Second poll: OK verdict
        cf_sub_ok = _make_cf_submission(
            submission_id=101, contest_id=800, index="A", verdict="OK",
            creation_time=now,
        )
        cf_mock.get_user_status.return_value = [cf_sub_testing, cf_sub_ok]

        matched = await SubmissionTracker.poll_submissions(db, cf_mock)
        assert matched == 1

        await db.refresh(tracking)
        assert tracking.status == "matched"


# ---------------------------------------------------------------------------
# 9. _get_submission_stats tests
# ---------------------------------------------------------------------------


class TestGetSubmissionStats:
    async def test_returns_accurate_error_count(self, db):
        """Should count WA/TLE/RE submissions as errors."""
        from app.services.submission_tracker import SubmissionStats

        user = _make_user(cf_handle="statshandle")
        db.add(user)
        await db.flush()

        now = datetime.now(UTC)
        expected = now - timedelta(minutes=5)
        tracking = _make_tracking(
            user_id=user.id,
            problem_id="800A",
            expected_at=expected,
            matched_at=now + timedelta(minutes=5),
            status="matched",
            cf_verdict="OK",
        )
        db.add(tracking)
        await db.flush()

        # 2 WA + 1 TLE + 1 OK = 4 total, 3 errors
        # All within window: expected=now-5min, window = [expected-5min, expected+30min]
        cf_submissions = [
            _make_cf_submission(submission_id=1, contest_id=800, index="A",
                                verdict="WRONG_ANSWER", creation_time=now - timedelta(minutes=3)),
            _make_cf_submission(submission_id=2, contest_id=800, index="A",
                                verdict="WRONG_ANSWER", creation_time=now - timedelta(minutes=2)),
            _make_cf_submission(submission_id=3, contest_id=800, index="A",
                                verdict="TIME_LIMIT_EXCEEDED", creation_time=now - timedelta(minutes=1)),
            _make_cf_submission(submission_id=4, contest_id=800, index="A",
                                verdict="OK", creation_time=now),
        ]

        cf_mock = AsyncMock()
        cf_mock.get_user_status.return_value = cf_submissions

        stats = await SubmissionTracker._get_submission_stats(db, cf_mock, tracking)

        assert isinstance(stats, SubmissionStats)
        assert stats.total_submissions == 4
        assert stats.error_count == 3
        assert stats.last_ac_creation_time is not None
        assert stats.time_spent > 0

    async def test_no_ac_uses_matched_at_fallback(self, db):
        """When no AC submission, time_spent falls back to matched_at - expected_at."""
        user = _make_user(cf_handle="statshandle")
        db.add(user)
        await db.flush()

        now = datetime.now(UTC)
        expected = now - timedelta(minutes=10)
        matched = now - timedelta(minutes=3)
        tracking = _make_tracking(
            user_id=user.id,
            problem_id="800A",
            expected_at=expected,
            matched_at=matched,
            status="matched",
            cf_verdict="WRONG_ANSWER",
        )
        db.add(tracking)
        await db.flush()

        # Only WA submissions
        cf_submissions = [
            _make_cf_submission(submission_id=1, contest_id=800, index="A",
                                verdict="WRONG_ANSWER", creation_time=now - timedelta(minutes=4)),
        ]

        cf_mock = AsyncMock()
        cf_mock.get_user_status.return_value = cf_submissions

        stats = await SubmissionTracker._get_submission_stats(db, cf_mock, tracking)

        assert stats.total_submissions == 1
        assert stats.error_count == 1
        assert stats.last_ac_creation_time is None
        # Fallback: matched_at - expected_at = 7 minutes = 420 seconds
        assert abs(stats.time_spent - 420) < 5

    async def test_no_matching_subs_returns_defaults(self, db):
        """When CF API returns no matching submissions, returns defaults."""
        user = _make_user(cf_handle="statshandle")
        db.add(user)
        await db.flush()

        now = datetime.now(UTC)
        tracking = _make_tracking(
            user_id=user.id,
            problem_id="800A",
            expected_at=now,
            status="matched",
            cf_verdict="OK",
        )
        db.add(tracking)
        await db.flush()

        # Submissions for a different problem
        cf_submissions = [
            _make_cf_submission(contest_id=999, index="Z", verdict="OK",
                                creation_time=now),
        ]

        cf_mock = AsyncMock()
        cf_mock.get_user_status.return_value = cf_submissions

        stats = await SubmissionTracker._get_submission_stats(db, cf_mock, tracking)

        assert stats.total_submissions == 1
        assert stats.error_count == 0
        assert stats.time_spent == 0.0

    async def test_cf_api_error_returns_defaults(self, db):
        """When CF API fails, should return default stats."""
        user = _make_user(cf_handle="statshandle")
        db.add(user)
        await db.flush()

        tracking = _make_tracking(
            user_id=user.id,
            problem_id="800A",
            expected_at=datetime.now(UTC),
            status="matched",
        )
        db.add(tracking)
        await db.flush()

        cf_mock = AsyncMock()
        cf_mock.get_user_status.side_effect = Exception("CF API down")

        stats = await SubmissionTracker._get_submission_stats(db, cf_mock, tracking)

        assert stats.total_submissions == 1
        assert stats.error_count == 0

    async def test_time_spent_from_ac_creation_time(self, db):
        """time_spent should be AC creation_time - expected_at."""
        user = _make_user(cf_handle="statshandle")
        db.add(user)
        await db.flush()

        now = datetime.now(UTC)
        expected = now - timedelta(minutes=15)
        ac_time = now - timedelta(minutes=2)  # AC came 13 min after expected

        tracking = _make_tracking(
            user_id=user.id,
            problem_id="800A",
            expected_at=expected,
            matched_at=now,
            status="matched",
            cf_verdict="OK",
        )
        db.add(tracking)
        await db.flush()

        cf_submissions = [
            _make_cf_submission(submission_id=1, contest_id=800, index="A",
                                verdict="WRONG_ANSWER", creation_time=now - timedelta(minutes=5)),
            _make_cf_submission(submission_id=2, contest_id=800, index="A",
                                verdict="OK", creation_time=ac_time),
        ]

        cf_mock = AsyncMock()
        cf_mock.get_user_status.return_value = cf_submissions

        stats = await SubmissionTracker._get_submission_stats(db, cf_mock, tracking)

        assert stats.total_submissions == 2
        assert stats.error_count == 1
        # 13 minutes = 780 seconds
        assert abs(stats.time_spent - 780) < 5
        assert stats.last_ac_creation_time is not None

    async def test_user_without_cf_handle_returns_defaults(self, db):
        """User without CF handle should return defaults."""
        user = _make_user(cf_handle=None)
        db.add(user)
        await db.flush()

        tracking = _make_tracking(
            user_id=user.id,
            problem_id="800A",
            expected_at=datetime.now(UTC),
            status="matched",
        )
        db.add(tracking)
        await db.flush()

        cf_mock = AsyncMock()

        stats = await SubmissionTracker._get_submission_stats(db, cf_mock, tracking)

        assert stats.total_submissions == 1
        assert stats.error_count == 0
        cf_mock.get_user_status.assert_not_called()


# ---------------------------------------------------------------------------
# 10. settle_matched with cf_service tests
# ---------------------------------------------------------------------------


class TestSettleWithStats:
    async def test_settle_passes_real_stats_to_pve(self, db):
        """settle_matched should pass real stats from CF API to PvE service."""
        user = _make_user()
        db.add(user)
        await db.flush()

        now = datetime.now(UTC)
        tracking = _make_tracking(
            user_id=user.id,
            session_type="pve",
            status="matched",
            cf_verdict="OK",
            matched_at=now,
            expected_at=now - timedelta(minutes=10),
        )
        db.add(tracking)
        await db.flush()

        # Mock CF service with stats
        cf_mock = AsyncMock()
        cf_mock.get_user_status.return_value = [
            _make_cf_submission(submission_id=1, contest_id=800, index="A",
                                verdict="WRONG_ANSWER", creation_time=now - timedelta(minutes=5)),
            _make_cf_submission(submission_id=2, contest_id=800, index="A",
                                verdict="OK", creation_time=now),
        ]

        with patch("app.services.pve_challenge_service.PvEChallengeService") as mock_pve:
            mock_pve.submit_result = AsyncMock()
            count = await SubmissionTracker.settle_matched(db, cf_service=cf_mock)

        assert count == 1
        assert tracking.status == "settled"

        # Verify real data was passed
        call_kwargs = mock_pve.submit_result.call_args
        assert call_kwargs.kwargs["attempts"] == 2  # 2 submissions total
        assert call_kwargs.kwargs["error_count"] == 1  # 1 WA
        assert call_kwargs.kwargs["time_spent"] > 0

    async def test_settle_without_cf_service_uses_defaults(self, db):
        """settle_matched without cf_service should use default values."""
        user = _make_user()
        db.add(user)
        await db.flush()

        tracking = _make_tracking(
            user_id=user.id,
            session_type="pve",
            status="matched",
            cf_verdict="OK",
            matched_at=datetime.now(UTC),
        )
        db.add(tracking)
        await db.flush()

        with patch("app.services.pve_challenge_service.PvEChallengeService") as mock_pve:
            mock_pve.submit_result = AsyncMock()
            count = await SubmissionTracker.settle_matched(db)

        assert count == 1
        assert tracking.status == "settled"

        call_kwargs = mock_pve.submit_result.call_args
        assert call_kwargs.kwargs["attempts"] == 1  # Default
        assert call_kwargs.kwargs["error_count"] == 0  # Default

    async def test_settle_passes_real_stats_to_training(self, db):
        """settle_matched should pass real stats to training service."""
        user = _make_user()
        db.add(user)
        await db.flush()

        now = datetime.now(UTC)
        tracking = _make_tracking(
            user_id=user.id,
            session_type="training",
            status="matched",
            cf_verdict="OK",
            matched_at=now,
            expected_at=now - timedelta(minutes=5),
        )
        db.add(tracking)
        await db.flush()

        cf_mock = AsyncMock()
        cf_mock.get_user_status.return_value = [
            _make_cf_submission(submission_id=1, contest_id=800, index="A",
                                verdict="OK", creation_time=now),
        ]

        with patch("app.services.training_service.TrainingService") as mock_training:
            mock_training.submit_problem = AsyncMock()
            count = await SubmissionTracker.settle_matched(db, cf_service=cf_mock)

        assert count == 1
        call_kwargs = mock_training.submit_problem.call_args
        assert call_kwargs.kwargs["attempts"] == 1
        assert call_kwargs.kwargs["time_spent"] >= 0

    async def test_settle_passes_real_stats_to_contest(self, db):
        """settle_matched should pass real stats to contest service."""
        user = _make_user()
        db.add(user)
        await db.flush()

        now = datetime.now(UTC)
        tracking = _make_tracking(
            user_id=user.id,
            session_type="contest",
            status="matched",
            cf_verdict="OK",
            matched_at=now,
            expected_at=now - timedelta(minutes=8),
        )
        db.add(tracking)
        await db.flush()

        cf_mock = AsyncMock()
        cf_mock.get_user_status.return_value = [
            _make_cf_submission(submission_id=1, contest_id=800, index="A",
                                verdict="TIME_LIMIT_EXCEEDED", creation_time=now - timedelta(minutes=2)),
            _make_cf_submission(submission_id=2, contest_id=800, index="A",
                                verdict="OK", creation_time=now),
        ]

        with patch("app.services.contest_service.ContestService") as mock_contest:
            mock_contest.submit_problem = AsyncMock()
            count = await SubmissionTracker.settle_matched(db, cf_service=cf_mock)

        assert count == 1
        call_kwargs = mock_contest.submit_problem.call_args
        assert call_kwargs.kwargs["attempts"] == 2
        assert call_kwargs.kwargs["time_spent"] > 0

    async def test_settle_passes_real_stats_to_pvp(self, db):
        """settle_matched should pass real stats to PvP challenge service."""
        user = _make_user()
        db.add(user)
        await db.flush()

        now = datetime.now(UTC)
        tracking = _make_tracking(
            user_id=user.id,
            session_type="pvp",
            status="matched",
            cf_verdict="OK",
            matched_at=now,
            expected_at=now - timedelta(minutes=12),
        )
        db.add(tracking)
        await db.flush()

        cf_mock = AsyncMock()
        cf_mock.get_user_status.return_value = [
            _make_cf_submission(submission_id=1, contest_id=800, index="A",
                                verdict="WRONG_ANSWER", creation_time=now - timedelta(minutes=10)),
            _make_cf_submission(submission_id=2, contest_id=800, index="A",
                                verdict="WRONG_ANSWER", creation_time=now - timedelta(minutes=8)),
            _make_cf_submission(submission_id=3, contest_id=800, index="A",
                                verdict="OK", creation_time=now),
        ]

        with patch("app.services.challenge_service.ChallengeService") as mock_pvp:
            mock_pvp.submit_result = AsyncMock()
            count = await SubmissionTracker.settle_matched(db, cf_service=cf_mock)

        assert count == 1
        call_kwargs = mock_pvp.submit_result.call_args
        assert call_kwargs.kwargs["attempts"] == 3
        assert call_kwargs.kwargs["time_spent"] > 0

    async def test_settle_stats_error_falls_back_to_defaults(self, db):
        """If stats extraction fails, should fall back to defaults."""
        user = _make_user()
        db.add(user)
        await db.flush()

        tracking = _make_tracking(
            user_id=user.id,
            session_type="pve",
            status="matched",
            cf_verdict="OK",
            matched_at=datetime.now(UTC),
        )
        db.add(tracking)
        await db.flush()

        # CF service that raises during stats extraction
        cf_mock = AsyncMock()
        cf_mock.get_user_status.side_effect = Exception("Stats error")

        with patch("app.services.pve_challenge_service.PvEChallengeService") as mock_pve:
            mock_pve.submit_result = AsyncMock()
            count = await SubmissionTracker.settle_matched(db, cf_service=cf_mock)

        assert count == 1
        call_kwargs = mock_pve.submit_result.call_args
        assert call_kwargs.kwargs["attempts"] == 1  # Default fallback
        assert call_kwargs.kwargs["error_count"] == 0
