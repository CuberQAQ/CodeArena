"""Tests for Free Play service and API.

Covers:
- Search problems: rating range + tag filtering
- No match scenarios
- Adaptive recommendation: M-Elo weighted tag selection
- Start session: validation, active session check
- Submit result: Elo/M-Elo/PP/token settlement
- Quit session
- Submission tracker integration for free_play type
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.free_play_session import FreePlaySession
from app.models.user import User
from app.services.free_play_service import FreePlayService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    user_id: uuid.UUID | None = None,
    elo: int = 1200,
    pp: float = 0.0,
    tokens: int = 100,
) -> User:
    """Create a mock User object for testing."""
    user = MagicMock(spec=User)
    user.id = user_id or uuid.uuid4()
    user.elo = elo
    user.pp = pp
    user.tokens = tokens
    user.daily_tokens_earned = 0
    user.daily_tokens_reset_at = None
    return user


def _make_problem(
    contest_id: int = 1920,
    index: str = "A",
    name: str = "Test Problem",
    rating: int = 1500,
    tags: list[str] | None = None,
) -> dict:
    """Create a CF API problem dict."""
    return {
        "contestId": contest_id,
        "index": index,
        "name": name,
        "rating": rating,
        "tags": tags or ["dp", "greedy"],
    }


def _make_cf_response(problems: list[dict]) -> dict:
    """Create a CF API problemset response."""
    return {"problems": problems, "statistics": []}


# ---------------------------------------------------------------------------
# Search problems tests
# ---------------------------------------------------------------------------


class TestSearchProblems:
    """Tests for FreePlayService.search_problems."""

    @pytest.mark.asyncio
    async def test_search_finds_matching_problem(self):
        """Search with rating range and tags returns a matching problem."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user()
        cf_service = AsyncMock()

        # Mock solved IDs
        with patch.object(
            FreePlayService,
            "_get_solved_problem_ids",
            return_value=set(),
        ):
            cf_service.get_problemset_problems.return_value = _make_cf_response(
                [
                    _make_problem(rating=1400, tags=["dp"]),
                    _make_problem(contest_id=1921, index="B", rating=1600, tags=["greedy"]),
                    _make_problem(contest_id=1922, index="C", rating=1500, tags=["dp"]),
                ]
            )

            result = await FreePlayService.search_problems(
                db=db,
                user=user,
                min_rating=1400,
                max_rating=1500,
                tags=["dp"],
                cf_service=cf_service,
            )

        assert result.found is True
        assert result.problem is not None
        assert result.problem.rating in (1400, 1500)
        assert "dp" in result.problem.tags

    @pytest.mark.asyncio
    async def test_search_no_matching_rating(self):
        """Search with very high rating returns no results."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user()
        cf_service = AsyncMock()

        with patch.object(
            FreePlayService,
            "_get_solved_problem_ids",
            return_value=set(),
        ):
            cf_service.get_problemset_problems.return_value = _make_cf_response(
                [
                    _make_problem(rating=1500),
                    _make_problem(rating=1600),
                ]
            )

            result = await FreePlayService.search_problems(
                db=db,
                user=user,
                min_rating=3500,
                max_rating=3600,
                tags=[],
                cf_service=cf_service,
            )

        assert result.found is False
        assert result.problem is None
        assert "No unsolved" in result.message

    @pytest.mark.asyncio
    async def test_search_excludes_solved_problems(self):
        """Search excludes problems the user has already solved."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user()
        cf_service = AsyncMock()

        # User has solved 1920A
        with patch.object(
            FreePlayService,
            "_get_solved_problem_ids",
            return_value={"1920A"},
        ):
            cf_service.get_problemset_problems.return_value = _make_cf_response(
                [
                    _make_problem(contest_id=1920, index="A", rating=1500, tags=["dp"]),
                    _make_problem(contest_id=1921, index="B", rating=1500, tags=["dp"]),
                ]
            )

            result = await FreePlayService.search_problems(
                db=db,
                user=user,
                min_rating=1400,
                max_rating=1600,
                tags=["dp"],
                cf_service=cf_service,
            )

        assert result.found is True
        assert result.problem is not None
        assert result.problem.contest_id != 1920 or result.problem.index != "A"

    @pytest.mark.asyncio
    async def test_search_cf_api_unavailable(self):
        """Search returns friendly message when CF API is unavailable."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user()
        cf_service = AsyncMock()
        cf_service.get_problemset_problems.side_effect = Exception("Network error")

        with patch.object(
            FreePlayService,
            "_get_solved_problem_ids",
            return_value=set(),
        ):
            result = await FreePlayService.search_problems(
                db=db,
                user=user,
                min_rating=1400,
                max_rating=1600,
                tags=[],
                cf_service=cf_service,
            )

        assert result.found is False
        assert "unavailable" in result.message.lower()


# ---------------------------------------------------------------------------
# Recommend problem tests
# ---------------------------------------------------------------------------


class TestRecommendProblem:
    """Tests for FreePlayService.recommend_problem."""

    @pytest.mark.asyncio
    async def test_recommend_uses_melo_weights(self):
        """Recommendation picks tags where user's M-Elo is weakest."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user(elo=1200)
        cf_service = AsyncMock()

        # Mock M-Elo: DP is weakest (1000), graphs is strong (1500)
        melo_dp = MagicMock()
        melo_dp.tag = "dp"
        melo_dp.elo = 1000
        melo_graphs = MagicMock()
        melo_graphs.tag = "graphs"
        melo_graphs.elo = 1500

        with patch("app.services.free_play_service.MEloService") as mock_melo:
            mock_melo.get_all_melos = AsyncMock(return_value=[melo_dp, melo_graphs])
            with patch.object(
                FreePlayService,
                "_get_solved_problem_ids",
                return_value=set(),
            ):
                cf_service.get_problemset_problems.return_value = _make_cf_response(
                    [
                        _make_problem(contest_id=100, index="A", rating=1100, tags=["dp"]),
                        _make_problem(contest_id=200, index="B", rating=1500, tags=["graphs"]),
                    ]
                )

                result = await FreePlayService.recommend_problem(
                    db=db,
                    user=user,
                    cf_service=cf_service,
                )

        # DP tag has lower M-Elo (1000), so [1000-100, 1000+200] = [900, 1200]
        # The DP problem at 1100 is in range
        assert result.found is True
        # With weighted random, DP should be chosen with much higher probability
        # (weight = 1500 - 1000 + 100 = 600 vs 1500 - 1500 + 100 = 100)
        # We just verify a result was found
        assert result.problem is not None

    @pytest.mark.asyncio
    async def test_recommend_no_melo_fallback(self):
        """Recommendation falls back to global Elo range when no M-Elo data."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user(elo=1200)
        cf_service = AsyncMock()

        with patch("app.services.free_play_service.MEloService") as mock_melo:
            mock_melo.get_all_melos = AsyncMock(return_value=[])
            with patch.object(
                FreePlayService,
                "_get_solved_problem_ids",
                return_value=set(),
            ):
                cf_service.get_problemset_problems.return_value = _make_cf_response(
                    [
                        _make_problem(rating=1100),
                        _make_problem(rating=1300),
                    ]
                )

                result = await FreePlayService.recommend_problem(
                    db=db,
                    user=user,
                    cf_service=cf_service,
                )

        assert result.found is True
        # User elo 1200, range [1100, 1400]
        assert result.problem.rating in (1100, 1300)

    @pytest.mark.asyncio
    async def test_recommend_no_suitable_problem(self):
        """Recommendation returns not found when no matching problems exist."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user(elo=1200)
        cf_service = AsyncMock()

        melo_dp = MagicMock()
        melo_dp.tag = "dp"
        melo_dp.elo = 3000

        with patch("app.services.free_play_service.MEloService") as mock_melo:
            mock_melo.get_all_melos = AsyncMock(return_value=[melo_dp])
            with patch.object(
                FreePlayService,
                "_get_solved_problem_ids",
                return_value=set(),
            ):
                cf_service.get_problemset_problems.return_value = _make_cf_response(
                    [
                        _make_problem(rating=800, tags=["math"]),
                    ]
                )

                result = await FreePlayService.recommend_problem(
                    db=db,
                    user=user,
                    cf_service=cf_service,
                )

        assert result.found is False
        assert "No suitable problem" in result.message


# ---------------------------------------------------------------------------
# Start session tests
# ---------------------------------------------------------------------------


class TestStartSession:
    """Tests for FreePlayService.start_session."""

    @pytest.mark.asyncio
    async def test_start_session_success(self):
        """Starting a session creates a valid FreePlaySession."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user()

        # Track the session object so we can set its id after add()
        added_session = None
        original_add = db.add

        def track_add(obj):
            nonlocal added_session
            added_session = obj
            original_add(obj)

        db.add = MagicMock(side_effect=track_add)

        async def fake_flush():
            if added_session is not None:
                added_session.id = uuid.uuid4()

        db.flush = AsyncMock(side_effect=fake_flush)

        with patch.object(FreePlayService, "_assert_no_active_session", return_value=None):
            with patch("app.services.free_play_service.SubmissionTracker") as mock_tracker:
                mock_tracker.register_pending = AsyncMock()

                result = await FreePlayService.start_session(
                    db=db,
                    user=user,
                    problem_contest_id=1920,
                    problem_index="A",
                    problem_rating=1500,
                    problem_tags=["dp", "greedy"],
                    problem_name="Test Problem",
                )

        assert result.status == "active"
        assert result.problem.contest_id == 1920
        assert result.problem.index == "A"
        assert result.problem.rating == 1500
        assert result.problem.tags == ["dp", "greedy"]
        assert result.session_id is not None
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_session_rejects_duplicate_active(self):
        """Starting a session when one is already active raises BadRequest."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user()

        with (
            patch.object(
                FreePlayService,
                "_assert_no_active_session",
                side_effect=BadRequestException(message="You already have an active Free Play session"),
            ),
            pytest.raises(BadRequestException, match="already have an active"),
        ):
            await FreePlayService.start_session(
                db=db,
                user=user,
                problem_contest_id=1920,
                problem_index="A",
                problem_rating=1500,
                problem_tags=["dp"],
            )


# ---------------------------------------------------------------------------
# Submit result tests
# ---------------------------------------------------------------------------


class TestSubmitResult:
    """Tests for FreePlayService.submit_result."""

    @pytest.mark.asyncio
    async def test_submit_solved_updates_elo(self):
        """Submitting a solved result updates user Elo correctly."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user(elo=1200)
        session_id = uuid.uuid4()

        session = FreePlaySession(
            id=session_id,
            user_id=user.id,
            problem_id="1920A",
            problem_contest_id=1920,
            problem_index="A",
            problem_rating=1500,
            problem_tags=["dp"],
            status="active",
        )
        session.id = session_id

        with patch.object(FreePlayService, "_get_session_or_raise", return_value=session):
            with patch("app.services.free_play_service.ConfigService") as mock_config:
                mock_config.get_config = AsyncMock(
                    return_value={
                        "k_newbie": 40,
                        "k_veteran": 20,
                        "k_newbie_threshold": 20,
                        "k_veteran_threshold": 100,
                    }
                )
                with patch("app.services.free_play_service.EloService") as mock_elo:
                    mock_elo.calculate_s_value.return_value = 1.0
                    mock_elo.calculate_k_factor.return_value = 32.0
                    mock_elo.calculate_expected_score.return_value = 0.2
                    mock_elo.apply_hint_attenuation.return_value = 32.0 * 0.8  # K*(1-0.2)
                    mock_elo.get_submission_count = AsyncMock(return_value=10)
                    mock_elo.record_elo_history = AsyncMock()

                    with patch("app.services.free_play_service.HintService") as mock_hint:
                        mock_hint.get_max_hint_level = AsyncMock(return_value=0)

                        with patch("app.services.free_play_service.PPService") as mock_pp:
                            mock_pp.record_pp = AsyncMock()
                            mock_pp.calculate_overkill_multiplier.return_value = 1.2

                            with patch("app.services.free_play_service.economy_svc") as mock_econ:
                                mock_econ.tokens_for_rating.return_value = 20
                                mock_econ.award_tokens = AsyncMock(return_value=20)
                                mock_econ.TIME_BONUS_THRESHOLD_SECONDS = 1200

                                with patch("app.services.free_play_service.MEloService") as mock_melo:
                                    mock_melo.batch_update_melo_for_problem = AsyncMock(return_value={"dp": 5})

                                    result = await FreePlayService.submit_result(
                                        db=db,
                                        user=user,
                                        session_id=session_id,
                                        solved=True,
                                        time_spent=300,
                                        attempts=1,
                                        error_count=0,
                                        cf_service=None,
                                    )

        assert result.solved is True
        assert result.status == "completed"
        assert result.elo_change is not None
        # Elo should increase (solved a harder problem)
        assert result.elo_change > 0

    @pytest.mark.asyncio
    async def test_submit_not_solved_reduces_elo(self):
        """Submitting a failed result reduces user Elo."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user(elo=1200)
        session_id = uuid.uuid4()

        session = FreePlaySession(
            id=session_id,
            user_id=user.id,
            problem_id="1920A",
            problem_contest_id=1920,
            problem_index="A",
            problem_rating=1500,
            problem_tags=["dp"],
            status="active",
        )
        session.id = session_id

        with patch.object(FreePlayService, "_get_session_or_raise", return_value=session):
            with patch("app.services.free_play_service.ConfigService") as mock_config:
                mock_config.get_config = AsyncMock(
                    return_value={
                        "k_newbie": 40,
                        "k_veteran": 20,
                        "k_newbie_threshold": 20,
                        "k_veteran_threshold": 100,
                    }
                )
                with patch("app.services.free_play_service.EloService") as mock_elo:
                    mock_elo.calculate_s_value.return_value = 0.0
                    mock_elo.calculate_k_factor.return_value = 32.0
                    mock_elo.calculate_expected_score.return_value = 0.2
                    mock_elo.apply_hint_attenuation.return_value = -32.0 * 0.2
                    mock_elo.get_submission_count = AsyncMock(return_value=10)
                    mock_elo.record_elo_history = AsyncMock()

                    with patch("app.services.free_play_service.HintService") as mock_hint:
                        mock_hint.get_max_hint_level = AsyncMock(return_value=0)

                        with patch("app.services.free_play_service.economy_svc") as mock_econ:
                            mock_econ.attempt_tokens_for_rating.return_value = 3
                            mock_econ.award_tokens = AsyncMock(return_value=3)

                            with patch("app.services.free_play_service.MEloService") as mock_melo:
                                mock_melo.batch_update_melo_for_problem = AsyncMock(return_value={"dp": -5})

                                result = await FreePlayService.submit_result(
                                    db=db,
                                    user=user,
                                    session_id=session_id,
                                    solved=False,
                                    time_spent=600,
                                    attempts=3,
                                    error_count=2,
                                    cf_service=None,
                                )

        assert result.solved is False
        assert result.status == "completed"
        assert result.elo_change is not None
        assert result.elo_change < 0

    @pytest.mark.asyncio
    async def test_submit_overkill_triggers_pp_multiplier(self):
        """Solving a problem far above user Elo triggers overkill PP multiplier."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user(elo=1200)
        session_id = uuid.uuid4()

        session = FreePlaySession(
            id=session_id,
            user_id=user.id,
            problem_id="1920A",
            problem_contest_id=1920,
            problem_index="A",
            problem_rating=1600,  # 400 above user
            problem_tags=["dp"],
            status="active",
        )
        session.id = session_id

        with patch.object(FreePlayService, "_get_session_or_raise", return_value=session):
            with patch("app.services.free_play_service.ConfigService") as mock_config:
                mock_config.get_config = AsyncMock(
                    return_value={
                        "k_newbie": 40,
                        "k_veteran": 20,
                        "k_newbie_threshold": 20,
                        "k_veteran_threshold": 100,
                    }
                )
                with patch("app.services.free_play_service.EloService") as mock_elo:
                    mock_elo.calculate_s_value.return_value = 1.0
                    mock_elo.calculate_k_factor.return_value = 32.0
                    mock_elo.calculate_expected_score.return_value = 0.1
                    mock_elo.apply_hint_attenuation.return_value = 32.0 * 0.9
                    mock_elo.get_submission_count = AsyncMock(return_value=10)
                    mock_elo.record_elo_history = AsyncMock()

                    with patch("app.services.free_play_service.HintService") as mock_hint:
                        mock_hint.get_max_hint_level = AsyncMock(return_value=0)

                        with patch("app.services.free_play_service.PPService") as mock_pp:
                            mock_pp.record_pp = AsyncMock()
                            mock_pp.calculate_overkill_multiplier.return_value = 2.0

                            with patch("app.services.free_play_service.economy_svc") as mock_econ:
                                mock_econ.tokens_for_rating.return_value = 25
                                mock_econ.award_tokens = AsyncMock(return_value=25)
                                mock_econ.TIME_BONUS_THRESHOLD_SECONDS = 1200

                                with patch("app.services.free_play_service.MEloService") as mock_melo:
                                    mock_melo.batch_update_melo_for_problem = AsyncMock(return_value={"dp": 10})

                                    result = await FreePlayService.submit_result(
                                        db=db,
                                        user=user,
                                        session_id=session_id,
                                        solved=True,
                                        time_spent=300,
                                        attempts=1,
                                        error_count=0,
                                        cf_service=None,
                                    )

        assert result.overkill_multiplier == 2.0
        assert result.solved is True

    @pytest.mark.asyncio
    async def test_submit_melo_updated(self):
        """M-Elo is updated with correct coefficient (1.0, no training polarization)."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user(elo=1200)
        session_id = uuid.uuid4()

        session = FreePlaySession(
            id=session_id,
            user_id=user.id,
            problem_id="1920A",
            problem_contest_id=1920,
            problem_index="A",
            problem_rating=1500,
            problem_tags=["dp", "greedy"],
            status="active",
        )
        session.id = session_id

        with patch.object(FreePlayService, "_get_session_or_raise", return_value=session):
            with patch("app.services.free_play_service.ConfigService") as mock_config:
                mock_config.get_config = AsyncMock(
                    return_value={
                        "k_newbie": 40,
                        "k_veteran": 20,
                        "k_newbie_threshold": 20,
                        "k_veteran_threshold": 100,
                    }
                )
                with patch("app.services.free_play_service.EloService") as mock_elo:
                    mock_elo.calculate_s_value.return_value = 1.0
                    mock_elo.calculate_k_factor.return_value = 32.0
                    mock_elo.calculate_expected_score.return_value = 0.2
                    mock_elo.apply_hint_attenuation.return_value = 32.0 * 0.8
                    mock_elo.get_submission_count = AsyncMock(return_value=10)
                    mock_elo.record_elo_history = AsyncMock()

                    with patch("app.services.free_play_service.HintService") as mock_hint:
                        mock_hint.get_max_hint_level = AsyncMock(return_value=0)

                        with patch("app.services.free_play_service.PPService") as mock_pp:
                            mock_pp.record_pp = AsyncMock()
                            mock_pp.calculate_overkill_multiplier.return_value = 1.0

                            with patch("app.services.free_play_service.economy_svc") as mock_econ:
                                mock_econ.tokens_for_rating.return_value = 20
                                mock_econ.award_tokens = AsyncMock(return_value=20)
                                mock_econ.TIME_BONUS_THRESHOLD_SECONDS = 1200

                                with patch("app.services.free_play_service.MEloService") as mock_melo:
                                    mock_melo.batch_update_melo_for_problem = AsyncMock(
                                        return_value={"dp": 5, "greedy": 3}
                                    )

                                    result = await FreePlayService.submit_result(
                                        db=db,
                                        user=user,
                                        session_id=session_id,
                                        solved=True,
                                        time_spent=300,
                                        attempts=1,
                                        error_count=0,
                                        cf_service=None,
                                    )

                        # Verify M-Elo was called with coefficient=1.0
                        mock_melo.batch_update_melo_for_problem.assert_called_once()
                        call_kwargs = mock_melo.batch_update_melo_for_problem.call_args
                        assert call_kwargs.kwargs["coefficient"] == 1.0
                        assert call_kwargs.kwargs["problem_tags"] == ["dp", "greedy"]

        assert result.solved is True

    @pytest.mark.asyncio
    async def test_submit_wrong_session_raises(self):
        """Submitting to another user's session raises Forbidden."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user()
        uuid.uuid4()

        with (
            patch.object(
                FreePlayService,
                "_get_session_or_raise",
                side_effect=ForbiddenException(message="Not the owner"),
            ),
            pytest.raises(ForbiddenException),
        ):
            await FreePlayService.submit_result(
                db=db,
                user=user,
                session_id=uuid.uuid4(),
                solved=True,
                time_spent=300,
                attempts=1,
            )

    @pytest.mark.asyncio
    async def test_submit_nonexistent_session_raises(self):
        """Submitting to a non-existent session raises NotFound."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user()

        with (
            patch.object(
                FreePlayService,
                "_get_session_or_raise",
                side_effect=NotFoundException(message="not found"),
            ),
            pytest.raises(NotFoundException),
        ):
            await FreePlayService.submit_result(
                db=db,
                user=user,
                session_id=uuid.uuid4(),
                solved=True,
                time_spent=300,
                attempts=1,
            )


# ---------------------------------------------------------------------------
# Quit session tests
# ---------------------------------------------------------------------------


class TestQuitSession:
    """Tests for FreePlayService.quit_session."""

    @pytest.mark.asyncio
    async def test_quit_session_no_submissions(self):
        """Quitting with 0 submissions: no Elo change (FR-4.6)."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user(elo=1200)
        session_id = uuid.uuid4()

        session = FreePlaySession(
            id=session_id,
            user_id=user.id,
            problem_id="1920A",
            problem_contest_id=1920,
            problem_index="A",
            problem_rating=1500,
            problem_tags=["dp"],
            status="active",
            error_count=0,
        )
        session.id = session_id

        with (
            patch.object(FreePlayService, "_get_session_or_raise", return_value=session),
            patch("app.services.free_play_service.SubmissionTracker") as mock_tracker,
        ):
            mock_tracker.get_tracking_for_session = AsyncMock(return_value=None)
            db.flush = AsyncMock()

            result = await FreePlayService.quit_session(
                db=db,
                user=user,
                session_id=session_id,
            )

        assert result.status == "quit"
        assert result.elo_change == 0
        assert result.penalty == 0

    @pytest.mark.asyncio
    async def test_quit_session_few_submissions(self):
        """Quitting with 1-2 submissions: mild Elo penalty -5 to -10 (FR-4.6)."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user(elo=1200)
        session_id = uuid.uuid4()

        session = FreePlaySession(
            id=session_id,
            user_id=user.id,
            problem_id="1920A",
            problem_contest_id=1920,
            problem_index="A",
            problem_rating=1500,
            problem_tags=["dp"],
            status="active",
            error_count=1,
        )
        session.id = session_id

        mock_tracking = AsyncMock()
        mock_tracking.status = "matched"

        with (
            patch.object(FreePlayService, "_get_session_or_raise", return_value=session),
            patch("app.services.free_play_service.SubmissionTracker") as mock_tracker,
        ):
            mock_tracker.get_tracking_for_session = AsyncMock(return_value=mock_tracking)
            db.flush = AsyncMock()

            result = await FreePlayService.quit_session(
                db=db,
                user=user,
                session_id=session_id,
            )

        assert result.status == "quit"
        assert -10 <= result.elo_change <= -5
        assert result.penalty == abs(result.elo_change)

    @pytest.mark.asyncio
    async def test_quit_non_active_session_raises(self):
        """Quitting a non-active session raises BadRequest."""
        db = AsyncMock(spec=AsyncSession)
        user = _make_user()

        with (
            patch.object(
                FreePlayService,
                "_get_session_or_raise",
                side_effect=BadRequestException(message="not active"),
            ),
            pytest.raises(BadRequestException),
        ):
            await FreePlayService.quit_session(
                db=db,
                user=user,
                session_id=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# Session ownership tests
# ---------------------------------------------------------------------------


class TestSessionOwnership:
    """Tests for session ownership validation."""

    @pytest.mark.asyncio
    async def test_get_session_wrong_user_raises_forbidden(self):
        """Accessing another user's session raises Forbidden."""
        db = AsyncMock(spec=AsyncSession)
        user_id = uuid.uuid4()
        other_user_id = uuid.uuid4()
        session_id = uuid.uuid4()

        session = FreePlaySession(
            id=session_id,
            user_id=other_user_id,
            problem_id="1920A",
            problem_contest_id=1920,
            problem_index="A",
            problem_rating=1500,
            problem_tags=["dp"],
            status="active",
        )
        session.id = session_id

        # Mock db.get to return the session
        db.get = AsyncMock(return_value=session)

        with pytest.raises(ForbiddenException, match="Not the owner"):
            await FreePlayService._get_session_or_raise(
                db,
                session_id,
                user_id,
            )

    @pytest.mark.asyncio
    async def test_get_session_not_found(self):
        """Accessing a non-existent session raises NotFound."""
        db = AsyncMock(spec=AsyncSession)
        db.get = AsyncMock(return_value=None)

        with pytest.raises(NotFoundException, match="not found"):
            await FreePlayService._get_session_or_raise(
                db,
                uuid.uuid4(),
                uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# Problem info builder tests
# ---------------------------------------------------------------------------


class TestBuildProblemInfo:
    """Tests for FreePlayService._build_problem_info."""

    def test_build_problem_info_complete(self):
        """Building problem info from CF API dict."""
        problem = _make_problem(contest_id=1920, index="A", name="Test", rating=1500, tags=["dp"])
        info = FreePlayService._build_problem_info(problem)

        assert info.contest_id == 1920
        assert info.index == "A"
        assert info.name == "Test"
        assert info.rating == 1500
        assert info.tags == ["dp"]
        assert "codeforces.com" in info.url

    def test_build_problem_info_no_contest(self):
        """Building problem info when contest ID is 0."""
        problem = {"contestId": 0, "index": "", "name": "X", "rating": None, "tags": []}
        info = FreePlayService._build_problem_info(problem)

        assert info.contest_id == 0
        assert info.url == ""
