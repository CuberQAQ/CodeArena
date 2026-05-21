"""Contest system business logic service.

Handles the virtual contest lifecycle:
- Tier eligibility checking and listing
- Contest session creation with problem selection from CF API
- Timing system with auto-expiry
- Problem submission and token rewards
- Settlement using M-Elo formula
- Contest history and result retrieval
"""

import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.contest_problem_record import ContestProblemRecord
from app.models.contest_session import ContestSession
from app.models.elo_history import EloHistory
from app.models.user import User
from app.schemas.contest import (
    ContestHistoryItem,
    ContestProblemInfo,
    ContestResult,
    ContestSessionInfo,
    LeaderboardResponse,
    SubmitContestResponse,
    TierInfo,
)
from app.services import economy_service as economy_svc
from app.services.achievement_service import AchievementService
from app.services.cf_api_service import CFApiService
from app.services.config_service import ConfigService
from app.services.contest_simulation_service import ContestSimulationService
from app.services.elo_service import EloService
from app.services.hint_service import HintService
from app.services.medal_service import MedalService
from app.services.melo_service import MEloService
from app.services.pp_service import PPService
from app.services.submission_tracker import SubmissionTracker
from app.services.time_factor_service import TimeFactorService

logger = logging.getLogger("code_arena.contest")

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

TIER_CONFIGS: dict[str, dict] = {
    "beginner": {
        "name": "Beginner Contest",
        "max_elo": 1400,
        "min_elo": None,
        "duration_minutes": 90,
        "problem_count": 4,
        "rating_range": [800, 1400],
    },
    "advanced": {
        "name": "Advanced Contest",
        "min_elo": 1400,
        "max_elo": 1800,
        "duration_minutes": 120,
        "problem_count": 5,
        "rating_range": [1200, 2000],
    },
    "master": {
        "name": "Master Contest",
        "min_elo": 1800,
        "max_elo": None,
        "duration_minutes": 150,
        "problem_count": 6,
        "rating_range": [1600, 2600],
    },
}

# ---------------------------------------------------------------------------
# Token reward tiers (same as challenge/training)
# ---------------------------------------------------------------------------

_TOKEN_TIERS: list[tuple[int, int]] = [
    (1200, 10),   # gray (800-1199)
    (1400, 20),   # green (1200-1399)
    (1600, 25),   # cyan (1400-1599)
    (1900, 35),   # blue (1600-1899)
    (2100, 45),   # purple (1900-2099)
    (2400, 55),   # orange (2100-2399)
    (9999, 65),   # red (2400+)
]


def _tokens_for_rating(rating: int) -> int:
    """Return the AC token reward for a problem at the given rating."""
    for threshold, reward in _TOKEN_TIERS:
        if rating < threshold:
            return reward
    return 65


# ---------------------------------------------------------------------------
# Contest Service
# ---------------------------------------------------------------------------


class ContestService:
    """Orchestrates virtual contest sessions.

    Stateless service class -- each method receives the resources
    it needs (db session, external services) as parameters.
    """

    # ------------------------------------------------------------------
    # 1. Get available tiers
    # ------------------------------------------------------------------

    @staticmethod
    async def get_tiers(db: AsyncSession, user: User) -> list[TierInfo]:
        """Return all tiers with eligibility info for the user.

        A user can join tiers at their level or below, but not above.
        """
        tiers: list[TierInfo] = []
        for tier_key, cfg in TIER_CONFIGS.items():
            min_elo = cfg.get("min_elo")
            max_elo = cfg.get("max_elo")

            # Eligibility: user Elo must be >= min (if set) and < max (if set)
            # Users can join lower tiers (downgrade allowed) but not higher
            eligible = True
            if min_elo is not None and user.elo < min_elo:
                eligible = False
            if max_elo is not None and user.elo >= max_elo:
                eligible = False

            # Also allow users to downgrade: check if user elo meets the max
            # For "beginner": elo < 1400 directly, OR elo >= 1400 means downgrade allowed
            # For "advanced": 1400 <= elo < 1800 directly, OR elo >= 1800 downgrade allowed
            # For "master": elo >= 1800 directly
            #
            # Rule: can join if elo >= min_elo (if set). max_elo is the upper bound
            # for the tier's target audience but doesn't block higher-Elo users.
            eligible = not (min_elo is not None and user.elo < min_elo)

            tiers.append(TierInfo(
                tier=tier_key,
                name=cfg["name"],
                min_elo=min_elo,
                max_elo=max_elo,
                duration_minutes=cfg["duration_minutes"],
                problem_count=cfg["problem_count"],
                rating_range=cfg["rating_range"],
                eligible=eligible,
            ))

        return tiers

    # ------------------------------------------------------------------
    # 2. Start contest
    # ------------------------------------------------------------------

    @staticmethod
    async def start_contest(
        db: AsyncSession,
        user: User,
        tier: str,
        cf_service: CFApiService,
    ) -> ContestSessionInfo:
        """Start a new contest session for the user."""
        if tier not in TIER_CONFIGS:
            raise BadRequestException(message=f"Invalid tier: {tier}")

        cfg = TIER_CONFIGS[tier]

        # Check eligibility
        min_elo = cfg.get("min_elo")
        if min_elo is not None and user.elo < min_elo:
            raise BadRequestException(
                message=f"Elo {user.elo} is too low for {tier} contest (min: {min_elo})"
            )

        # Check for existing active contest
        active_stmt = select(ContestSession).where(
            ContestSession.user_id == user.id,
            ContestSession.status == "active",
        )
        active_result = await db.execute(active_stmt)
        active_session = active_result.scalar_one_or_none()
        if active_session is not None:
            raise BadRequestException(message="You already have an active contest session")

        # Select problems from CF API
        problems = await ContestService._select_problems(
            cf_service=cf_service,
            user_id=user.id,
            db=db,
            rating_range=cfg["rating_range"],
            count=cfg["problem_count"],
        )

        now = datetime.now(UTC)
        session = ContestSession(
            user_id=user.id,
            contest_tier=tier,
            problems=[p.model_dump() for p in problems],
            total_problems=len(problems),
            time_limit=cfg["duration_minutes"],
            started_at=now,
            status="active",
        )
        db.add(session)
        await db.flush()

        # Generate AI bots for the contest
        await ContestSimulationService.generate_bots(
            db=db,
            contest_id=session.id,
            user_elo=user.elo,
        )

        # Register pending submission tracking for each contest problem
        # so the CF API poller can automatically detect submissions.
        now_for_tracking = datetime.now(UTC)
        for p in problems:
            if p.problem_id:
                await SubmissionTracker.register_pending(
                    db=db,
                    user_id=user.id,
                    session_type="contest",
                    session_id=session.id,
                    problem_id=p.problem_id,
                    expected_at=now_for_tracking,
                )

        # Start background simulation so bots make progress over time
        await ContestSimulationService.start_simulation(
            contest_id=session.id,
            db_factory=async_session_factory,
        )

        return ContestSessionInfo(
            id=session.id,
            tier=tier,
            problems=problems,
            total_problems=len(problems),
            problems_solved=0,
            submissions=0,
            time_limit_minutes=cfg["duration_minutes"],
            started_at=now,
            remaining_seconds=float(cfg["duration_minutes"] * 60),
            end_time=now + timedelta(minutes=cfg["duration_minutes"]),
            status="active",
        )

    # ------------------------------------------------------------------
    # 3. Get active contest
    # ------------------------------------------------------------------

    @staticmethod
    async def get_active_contest(
        db: AsyncSession,
        user: User,
    ) -> ContestSessionInfo | None:
        """Get the user's currently active contest session, if any."""
        active_stmt = select(ContestSession).where(
            ContestSession.user_id == user.id,
            ContestSession.status == "active",
        )
        active_result = await db.execute(active_stmt)
        session = active_result.scalar_one_or_none()

        if session is None:
            return None

        # Calculate remaining time
        remaining = ContestService._calculate_remaining(session)

        # If time expired, auto-end the contest and return None
        if remaining is not None and remaining <= 0:
            await ContestService._auto_end_expired(db, session, user)
            return None

        # Build problem info list from stored data + problem records
        problem_infos = await ContestService._build_problem_infos(db, session)

        return ContestSessionInfo(
            id=session.id,
            tier=session.contest_tier,
            problems=problem_infos,
            total_problems=session.total_problems,
            problems_solved=session.problems_solved,
            submissions=session.submissions,
            time_limit_minutes=session.time_limit,
            started_at=session.started_at,
            ended_at=session.ended_at,
            remaining_seconds=remaining,
            end_time=(
                ContestService._ensure_utc(session.started_at) + timedelta(minutes=session.time_limit)
                if session.started_at and session.status == "active"
                else None
            ),
            status=session.status,
            elo_change=session.elo_change,
        )

    # ------------------------------------------------------------------
    # 4. Get contest status
    # ------------------------------------------------------------------

    @staticmethod
    async def get_contest_status(
        db: AsyncSession,
        user: User,
        contest_id: uuid.UUID,
    ) -> ContestSessionInfo:
        """Get the current status of a contest session with remaining time."""
        session = await ContestService._get_and_validate_session(
            db, user, contest_id
        )

        # Calculate remaining time
        remaining = ContestService._calculate_remaining(session)

        # If time expired, auto-end the contest
        if remaining is not None and remaining <= 0 and session.status == "active":
            await ContestService._auto_end_expired(db, session, user)
            remaining = 0.0

        # Build problem info list from stored data + problem records
        problem_infos = await ContestService._build_problem_infos(db, session)

        return ContestSessionInfo(
            id=session.id,
            tier=session.contest_tier,
            problems=problem_infos,
            total_problems=session.total_problems,
            problems_solved=session.problems_solved,
            submissions=session.submissions,
            time_limit_minutes=session.time_limit,
            started_at=session.started_at,
            ended_at=session.ended_at,
            remaining_seconds=remaining,
            end_time=(
                ContestService._ensure_utc(session.started_at) + timedelta(minutes=session.time_limit)
                if session.started_at and session.status == "active"
                else None
            ),
            status=session.status,
            elo_change=session.elo_change,
        )

    # ------------------------------------------------------------------
    # 5. Submit problem result
    # ------------------------------------------------------------------

    @staticmethod
    async def submit_problem(
        db: AsyncSession,
        user: User,
        contest_id: uuid.UUID,
        problem_id: str,
        solved: bool,
        attempts: int,
        time_spent: float,
    ) -> SubmitContestResponse:
        """Submit a problem result in a contest."""
        session = await ContestService._get_and_validate_session(
            db, user, contest_id
        )

        if session.status != "active":
            raise BadRequestException(message="Contest session is not active")

        # Check remaining time
        remaining = ContestService._calculate_remaining(session)
        if remaining is not None and remaining <= 0:
            raise BadRequestException(message="Contest time has expired")

        # Validate problem_id belongs to this contest
        stored_problems = session.problems or []
        problem_data = None
        problem_rating = 1000
        for p in stored_problems:
            if p.get("problem_id") == problem_id:
                problem_data = p
                problem_rating = p.get("rating", 1000)
                break

        if problem_data is None:
            raise BadRequestException(message=f"Problem {problem_id} not found in this contest")

        # Check for existing record
        existing_stmt = select(ContestProblemRecord).where(
            ContestProblemRecord.contest_id == contest_id,
            ContestProblemRecord.problem_id == problem_id,
        )
        existing_result = await db.execute(existing_stmt)
        existing_record = existing_result.scalar_one_or_none()

        if existing_record is not None and existing_record.solved:
            raise BadRequestException(message="Problem already solved in this contest")

        now = datetime.now(UTC)
        if existing_record is not None:
            # Update existing record
            existing_record.solved = solved
            existing_record.attempts = attempts
            existing_record.time_spent = time_spent
            if solved:
                existing_record.solved_at = now
            record = existing_record
        else:
            record = ContestProblemRecord(
                contest_id=contest_id,
                problem_id=problem_id,
                problem_rating=problem_rating,
                solved=solved,
                attempts=attempts,
                time_spent=time_spent,
                solved_at=now if solved else None,
            )
            db.add(record)

        # Update session submission count
        session.submissions += 1

        # Calculate token rewards
        tokens_earned = 0
        if solved:
            ac_tokens = _tokens_for_rating(problem_rating)
            tokens_earned += ac_tokens
            session.problems_solved += 1

            # Record PP
            wa_count = max(0, attempts - 1)
            time_spent_minutes = (time_spent or 0.0) / 60.0
            await PPService.record_pp(
                db=db,
                user_id=user.id,
                cf_problem_id=problem_id,
                problem_rating=problem_rating,
                wa_count=wa_count,
                time_spent=time_spent_minutes,
                user_elo=user.elo,
            )

            # Award AC tokens via economy_service (enforces daily cap)
            if tokens_earned > 0:
                await economy_svc.award_tokens(
                    db, user, tokens_earned,
                    tx_type="reward_ac",
                    reference_type="contest",
                    reference_id=contest_id,
                )

            # Time bonus: if solved and time_spent > 20 min, award extra tokens
            if time_spent > economy_svc.TIME_BONUS_THRESHOLD_SECONDS:
                time_bonus = economy_svc.time_bonus_for_rating(problem_rating)
                if time_bonus > 0:
                    await economy_svc.award_tokens(
                        db, user, time_bonus,
                        tx_type="time_bonus",
                        reference_type="contest",
                        reference_id=contest_id,
                    )
                    tokens_earned += time_bonus
        else:
            # Attempt reward: even if not AC, having submitted earns small tokens
            attempt_tokens = economy_svc.attempt_tokens_for_rating(problem_rating)
            if attempt_tokens > 0:
                awarded = await economy_svc.award_tokens(
                    db, user, attempt_tokens,
                    tx_type="reward_attempt",
                    reference_type="contest",
                    reference_id=contest_id,
                )
                tokens_earned += awarded

        # --- M-Elo update (FR-9.1) ---
        problem_tags_list = problem_data.get("tags", []) if problem_data else []
        if problem_tags_list and problem_rating > 0:
            # Calculate S-value for this problem
            is_first_ac = solved and attempts <= 1
            error_count = max(0, attempts - 1) if solved else 0
            s_val = EloService.calculate_s_value(
                is_solved=solved,
                is_first_ac=is_first_ac,
                error_count=error_count,
            )

            # Get K-factor for this user
            elo_config = await ConfigService.get_config(db, "elo")
            k_factor_config = {
                "k_newbie": elo_config.get("k_newbie", 40),
                "k_veteran": elo_config.get("k_veteran", 20),
                "k_newbie_threshold": elo_config.get("k_newbie_threshold", 20),
                "k_veteran_threshold": elo_config.get("k_veteran_threshold", 100),
            }
            user_sub_count = await EloService.get_submission_count(db, user.id)
            melo_k = EloService.calculate_k_factor(user_sub_count, k_factor_config)

            # Hint attenuation for M-Elo
            hint_level = await HintService.get_max_hint_level(db, user.id, problem_id)
            hint_att = None
            if hint_level > 0:
                from app.services.elo_service import EloConfig
                _hint_cfg = EloConfig()
                hint_att = _hint_cfg.hint_attenuation.get(hint_level)

            # Calculate time_factor for M-Elo (FR-16.7)
            contest_time_factor = 1.0
            if solved and time_spent and time_spent > 0:
                effective_t = TimeFactorService.compute_effective_time(time_spent, wa_count)
                try:
                    expected_t = await TimeFactorService.calculate_expected_time(
                        db, problem_id, user.elo
                    )
                    if expected_t and expected_t > 0:
                        contest_time_factor = TimeFactorService.calculate_time_factor(
                            effective_t, expected_t
                        )
                except Exception:
                    pass  # Fallback to 1.0 on calculation failure

            await MEloService.batch_update_melo_for_problem(
                db=db,
                user_id=user.id,
                problem_tags=problem_tags_list,
                problem_rating=problem_rating,
                s_value=s_val,
                k_factor=melo_k,
                time_factor=contest_time_factor,
                hint_attenuation=hint_att,
                coefficient=1.0,
                solved=solved,
            )

        await db.flush()

        return SubmitContestResponse(
            contest_id=contest_id,
            problem_id=problem_id,
            solved=solved,
            tokens_earned=tokens_earned,
        )

    # ------------------------------------------------------------------
    # 6. End contest
    # ------------------------------------------------------------------

    @staticmethod
    async def end_contest(
        db: AsyncSession,
        user: User,
        contest_id: uuid.UUID,
        cf_service: CFApiService | None = None,
    ) -> ContestResult:
        """End a contest session and calculate results."""
        session = await ContestService._get_and_validate_session(
            db, user, contest_id
        )

        if session.status != "active":
            raise BadRequestException(message="Contest session is not active")

        # Stop the background simulation if running
        await ContestSimulationService.stop_simulation(contest_id)

        now = datetime.now(UTC)
        session.ended_at = now
        session.status = "completed"

        # Determine Elo change based on submission count
        pr_achievements: list[dict] = []
        if session.submissions == 0:
            # 0 submissions: Elo unchanged
            elo_change = 0
            session.elo_change = 0
        elif session.submissions <= 2:
            # 1-2 submissions: quit penalty (-5 to -10)
            elo_change = random.randint(-10, -5)
            session.elo_change = elo_change
            user.elo += elo_change

            # Record Elo history
            history = EloHistory(
                user_id=user.id,
                elo_before=user.elo - elo_change,
                elo_after=user.elo,
                elo_change=elo_change,
                reason="quit_early",
                reference_id=contest_id,
            )
            db.add(history)
        else:
            # 3+ submissions: PR (Performance Rating) based settlement
            elo_change, pr_achievements = await ContestService._settle_with_pr(
                db=db,
                user=user,
                session=session,
                contest_id=contest_id,
                cf_service=cf_service,
            )
            session.elo_change = elo_change

        await db.flush()

        # Build result
        problem_infos = await ContestService._build_problem_infos(db, session)

        # Calculate PR for result display
        pr = await ContestSimulationService.calculate_performance_rating(
            db=db,
            contest_id=contest_id,
            player_solved=session.problems_solved,
        )

        # --- Achievement event detection ---
        achievements: list[dict] = list(pr_achievements) if session.submissions > 2 else []

        try:
            # Check contest win (rank 1 among all participants including bots)
            leaderboard = await ContestSimulationService.build_leaderboard(db, contest_id, user)
            player_rank = None
            total_participants = len(leaderboard.leaderboard)
            for entry in leaderboard.leaderboard:
                if not entry.is_bot:
                    player_rank = entry.rank
                    break

            if player_rank is not None:
                win_event = AchievementService.check_contest_win(
                    rank=player_rank,
                    total_participants=total_participants,
                )
                if win_event is not None:
                    achievements.append(win_event.to_dict())
        except Exception:
            # Leaderboard may not be available (e.g., no bots table in test DB).
            # Achievement detection is best-effort and must not break settlement.
            logger.debug("Achievement detection skipped: leaderboard unavailable for contest %s", contest_id)

        return ContestResult(
            id=session.id,
            tier=session.contest_tier,
            total_problems=session.total_problems,
            problems_solved=session.problems_solved,
            submissions=session.submissions,
            time_limit_minutes=session.time_limit,
            started_at=session.started_at,
            ended_at=session.ended_at,
            status="completed",
            elo_change=session.elo_change,
            performance_rating=pr,
            problems=problem_infos,
            achievements=achievements,
        )

    # ------------------------------------------------------------------
    # 7. Get contest history
    # ------------------------------------------------------------------

    @staticmethod
    async def get_contest_history(
        db: AsyncSession,
        user: User,
    ) -> list[ContestHistoryItem]:
        """Get all contest sessions for the user, newest first."""
        stmt = (
            select(ContestSession)
            .where(ContestSession.user_id == user.id)
            .order_by(ContestSession.started_at.desc())
        )
        result = await db.execute(stmt)
        sessions = result.scalars().all()

        return [
            ContestHistoryItem(
                id=s.id,
                tier=s.contest_tier,
                total_problems=s.total_problems,
                problems_solved=s.problems_solved,
                submissions=s.submissions,
                time_limit_minutes=s.time_limit,
                started_at=s.started_at,
                ended_at=s.ended_at,
                status=s.status,
                elo_change=s.elo_change,
            )
            for s in sessions
        ]

    # ------------------------------------------------------------------
    # 8. Get contest result
    # ------------------------------------------------------------------

    @staticmethod
    async def get_contest_result(
        db: AsyncSession,
        user: User,
        contest_id: uuid.UUID,
    ) -> ContestResult:
        """Get detailed results for a completed contest."""
        session = await ContestService._get_and_validate_session(
            db, user, contest_id
        )

        problem_infos = await ContestService._build_problem_infos(db, session)

        # Calculate PR for completed contests
        pr = None
        if session.status in ("completed", "ended") and session.submissions > 0:
            pr = await ContestSimulationService.calculate_performance_rating(
                db=db,
                contest_id=contest_id,
                player_solved=session.problems_solved,
            )

        return ContestResult(
            id=session.id,
            tier=session.contest_tier,
            total_problems=session.total_problems,
            problems_solved=session.problems_solved,
            submissions=session.submissions,
            time_limit_minutes=session.time_limit,
            started_at=session.started_at,
            ended_at=session.ended_at,
            status=session.status,
            elo_change=session.elo_change,
            performance_rating=pr,
            problems=problem_infos,
            achievements=[],  # Achievements are only generated at end_contest time
        )

    # ------------------------------------------------------------------
    # 9. Get leaderboard (human + bots)
    # ------------------------------------------------------------------

    @staticmethod
    async def get_leaderboard(
        db: AsyncSession,
        user: User,
        contest_id: uuid.UUID,
    ) -> LeaderboardResponse:
        """Get the combined human+bot leaderboard for a contest."""
        await ContestService._get_and_validate_session(db, user, contest_id)
        return await ContestSimulationService.build_leaderboard(db, contest_id, user)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_and_validate_session(
        db: AsyncSession,
        user: User,
        contest_id: uuid.UUID,
    ) -> ContestSession:
        """Fetch a contest session and validate ownership."""
        session = await db.get(ContestSession, contest_id)
        if session is None:
            raise NotFoundException(message="Contest session not found")
        if session.user_id != user.id:
            raise ForbiddenException(message="Not your contest session")
        return session

    @staticmethod
    def _calculate_remaining(session: ContestSession) -> float | None:
        """Calculate remaining time in seconds for an active contest."""
        if session.status != "active" or session.started_at is None:
            return None

        now = datetime.now(UTC)
        started_at = ContestService._ensure_utc(session.started_at)
        elapsed = (now - started_at).total_seconds()
        total_limit = session.time_limit * 60
        remaining = total_limit - elapsed
        return max(0.0, remaining)

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        """Ensure a datetime is timezone-aware (UTC). Handles naive datetimes from SQLite."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt

    @staticmethod
    async def _auto_end_expired(
        db: AsyncSession,
        session: ContestSession,
        user: User,
        cf_service: CFApiService | None = None,
    ) -> None:
        """Auto-end an expired contest using PR settlement."""
        # Create cf_service if not provided (for non-API callers)
        if cf_service is None:
            cf_service = CFApiService()

        # Stop the background simulation if running
        await ContestSimulationService.stop_simulation(session.id)

        now = datetime.now(UTC)
        session.ended_at = now
        session.status = "completed"

        # Tiered penalty matching end_contest logic
        if session.submissions == 0:
            session.elo_change = 0
        elif session.submissions <= 2:
            # 1-2 submissions: quit penalty (-5 to -10)
            elo_change = random.randint(-10, -5)
            session.elo_change = elo_change
            user.elo += elo_change

            # Record Elo history
            history = EloHistory(
                user_id=user.id,
                elo_before=user.elo - elo_change,
                elo_after=user.elo,
                elo_change=elo_change,
                reason="quit_early",
                reference_id=session.id,
            )
            db.add(history)
        else:
            # 3+ submissions: PR (Performance Rating) based settlement
            elo_change, _achievements = await ContestService._settle_with_pr(
                db=db,
                user=user,
                session=session,
                contest_id=session.id,
                cf_service=cf_service,
            )
            session.elo_change = elo_change
            # Achievements from auto-end are not returned to user (no active WS),
            # but the settlement logic (medal, Elo, PP) is preserved.

        await db.flush()

    @staticmethod
    async def _select_problems(
        cf_service: CFApiService,
        user_id: uuid.UUID,
        db: AsyncSession,
        rating_range: list[int],
        count: int,
    ) -> list[ContestProblemInfo]:
        """Select problems for a contest, evenly distributed across the rating range.

        Avoids problems the user has already solved.
        """
        rating_min = rating_range[0]
        rating_max = rating_range[1]

        # Fetch problems from CF API
        try:
            data = await cf_service.get_problemset_problems()
            all_problems = data.get("problems", [])
        except Exception:
            logger.warning("CF API unavailable for contest problem selection")
            # Fallback: generate placeholder problems
            return ContestService._generate_placeholder_problems(
                rating_min, rating_max, count
            )

        # Filter by rating range
        valid_problems = [
            p for p in all_problems
            if p.get("rating") is not None
            and rating_min <= p["rating"] <= rating_max
        ]

        # Get user's solved problems to avoid duplicates
        solved_problem_ids: set[str] = set()
        try:
            from app.models.training_problem_record import TrainingProblemRecord
            training_solved_stmt = select(TrainingProblemRecord.problem_id).where(
                TrainingProblemRecord.user_id == user_id,
                TrainingProblemRecord.solved.is_(True),
            )
            training_result = await db.execute(training_solved_stmt)
            for row in training_result.scalars().all():
                solved_problem_ids.add(row)
        except Exception:
            pass

        valid_problems = [
            p for p in valid_problems
            if f"{p.get('contestId', '')}{p.get('index', '')}" not in solved_problem_ids
        ]

        # Divide the rating range into equal segments
        if not valid_problems:
            return ContestService._generate_placeholder_problems(
                rating_min, rating_max, count
            )

        selected: list[ContestProblemInfo] = []
        segment_size = (rating_max - rating_min) / count if count > 0 else 0

        for i in range(count):
            seg_min = rating_min + i * segment_size
            seg_max = rating_min + (i + 1) * segment_size

            # Find problems in this segment
            segment_problems = [
                p for p in valid_problems
                if seg_min <= p.get("rating", 0) < seg_max
                or (i == count - 1 and p.get("rating", 0) == seg_max)
            ]

            if not segment_problems:
                # Expand search to adjacent segments
                segment_problems = [
                    p for p in valid_problems
                    if abs(p.get("rating", 0) - (seg_min + seg_max) / 2) <= segment_size
                ]

            if segment_problems:
                # Pick a random problem from the segment
                chosen = random.choice(segment_problems)
                contest_id = chosen.get("contestId", 0)
                index = chosen.get("index", "")
                pid = f"{contest_id}{index}"
                selected.append(ContestProblemInfo(
                    problem_id=pid,
                    contest_id=contest_id,
                    index=index,
                    name=chosen.get("name", ""),
                    rating=chosen.get("rating", 1000),
                    tags=chosen.get("tags", []),
                    url=f"https://codeforces.com/problemset/problem/{contest_id}/{index}" if contest_id else "",
                ))
                # Remove from pool to avoid duplicates
                valid_problems.remove(chosen)

        # Fill remaining slots if any segments were empty
        while len(selected) < count and valid_problems:
            chosen = random.choice(valid_problems)
            contest_id = chosen.get("contestId", 0)
            index = chosen.get("index", "")
            pid = f"{contest_id}{index}"
            selected.append(ContestProblemInfo(
                problem_id=pid,
                contest_id=contest_id,
                index=index,
                name=chosen.get("name", ""),
                rating=chosen.get("rating", 1000),
                tags=chosen.get("tags", []),
                url=f"https://codeforces.com/problemset/problem/{contest_id}/{index}" if contest_id else "",
            ))
            valid_problems.remove(chosen)

        # If still not enough, add placeholders
        while len(selected) < count:
            target_rating = rating_min + (len(selected) * (rating_max - rating_min) // count)
            selected.append(ContestProblemInfo(
                problem_id=f"placeholder_{len(selected)}",
                contest_id=0,
                index="",
                name=f"Problem {len(selected) + 1}",
                rating=target_rating,
            ))

        return selected

    @staticmethod
    def _generate_placeholder_problems(
        rating_min: int,
        rating_max: int,
        count: int,
    ) -> list[ContestProblemInfo]:
        """Generate placeholder problems when CF API is unavailable."""
        problems: list[ContestProblemInfo] = []
        for i in range(count):
            target_rating = rating_min + (i * (rating_max - rating_min) // max(count - 1, 1))
            problems.append(ContestProblemInfo(
                problem_id=f"placeholder_{i}",
                contest_id=0,
                index="",
                name=f"Problem {i + 1}",
                rating=target_rating,
            ))
        return problems

    @staticmethod
    async def _build_problem_infos(
        db: AsyncSession,
        session: ContestSession,
    ) -> list[ContestProblemInfo]:
        """Build the problem info list from session data and records."""
        stored_problems = session.problems or []

        # Fetch problem records for this contest
        records_stmt = select(ContestProblemRecord).where(
            ContestProblemRecord.contest_id == session.id,
        )
        records_result = await db.execute(records_stmt)
        records = {r.problem_id: r for r in records_result.scalars().all()}

        problem_infos: list[ContestProblemInfo] = []
        for p in stored_problems:
            pid = p.get("problem_id", "")
            record = records.get(pid)
            problem_infos.append(ContestProblemInfo(
                problem_id=pid,
                contest_id=p.get("contest_id", 0),
                index=p.get("index", ""),
                name=p.get("name", ""),
                rating=p.get("rating", 1000),
                tags=p.get("tags", []),
                url=p.get("url", ""),
                solved=record.solved if record else False,
                attempts=record.attempts if record else 0,
                time_spent=record.time_spent if record else None,
            ))

        return problem_infos

    @staticmethod
    async def _calculate_contest_s_values(
        db: AsyncSession,
        contest_id: uuid.UUID,
    ) -> list[float]:
        """Calculate S-values for all solved problems in a contest.

        Returns a list of S-values, one per solved problem, suitable for
        passing to ``EloService.process_contest_result`` via ``s_values``.
        """
        records_stmt = select(ContestProblemRecord).where(
            ContestProblemRecord.contest_id == contest_id,
            ContestProblemRecord.solved.is_(True),
        )
        records_result = await db.execute(records_stmt)
        solved_records = records_result.scalars().all()

        s_values: list[float] = []
        for record in solved_records:
            is_first_ac = record.attempts <= 1
            error_count = max(0, record.attempts - 1)
            s_val = EloService.calculate_s_value(
                is_solved=True,
                is_first_ac=is_first_ac,
                error_count=error_count,
            )
            s_values.append(s_val)

        return s_values

    @staticmethod
    async def _settle_with_pr(
        db: AsyncSession,
        user: User,
        session: ContestSession,
        contest_id: uuid.UUID,
        cf_service: CFApiService | None = None,
    ) -> tuple[int, list[dict]]:
        """Settle contest Elo using PR (Performance Rating) calculation.

        Uses binary search to find the PR that matches the player's actual
        rank, then applies: elo_change = K * (PR - current_elo) / 400.

        Returns
        -------
        tuple[int, list[dict]]
            The Elo change applied and a list of achievement event dicts.
        """
        # Calculate PR via binary search against bot field
        pr = await ContestSimulationService.calculate_performance_rating(
            db=db,
            contest_id=contest_id,
            player_solved=session.problems_solved,
        )

        # Determine K-factor from config
        elo_config = await ConfigService.get_config(db, "elo")
        k_newbie = float(elo_config.get("k_newbie", 40))
        k_veteran = float(elo_config.get("k_veteran", 20))
        newbie_threshold = int(elo_config.get("k_newbie_threshold", 20))
        veteran_threshold = int(elo_config.get("k_veteran_threshold", 100))

        user_sub_count = await EloService.get_submission_count(db, user.id)
        k_factor_config = {
            "k_newbie": k_newbie,
            "k_veteran": k_veteran,
            "k_newbie_threshold": newbie_threshold,
            "k_veteran_threshold": veteran_threshold,
        }
        k = EloService.calculate_k_factor(user_sub_count, k_factor_config)

        # Elo change = K * (PR - current_elo) / 400
        elo_before = user.elo
        elo_change = round(k * (pr - elo_before) / 400)

        # Apply hint attenuation to positive gains (FR-5.3)
        # Check max hint level across all problems attempted in this contest
        if elo_change > 0:
            stored_problems = session.problems or []
            max_hint = 0
            for p in stored_problems:
                pid = p.get("problem_id", "")
                if pid:
                    level = await HintService.get_max_hint_level(db, user.id, pid)
                    max_hint = max(max_hint, level)
            if max_hint > 0:
                elo_change = round(EloService.apply_hint_attenuation(float(elo_change), max_hint))

        # Apply time factor to positive gains (FR-16.4)
        # Compute average time factor across all solved problems
        if elo_change > 0 and cf_service is not None:
            stored_problems = session.problems or []
            time_factors: list[float] = []
            for p in stored_problems:
                pid = p.get("problem_id", "")
                prating = p.get("rating", 0)
                if not pid or prating <= 0:
                    continue
                # Check if this problem was solved
                rec_stmt = select(ContestProblemRecord).where(
                    ContestProblemRecord.contest_id == contest_id,
                    ContestProblemRecord.problem_id == pid,
                    ContestProblemRecord.solved.is_(True),
                )
                rec_result = await db.execute(rec_stmt)
                record = rec_result.scalar_one_or_none()
                if record is None or record.time_spent is None:
                    continue
                wa_count = max(0, record.attempts - 1)
                effective_time = TimeFactorService.compute_effective_time(record.time_spent, wa_count)
                expected_time = await TimeFactorService.calculate_expected_time(
                    cf_service, pid, prating, elo_before,
                )
                # S-value > 0 for solved problems
                is_first_ac = record.attempts <= 1
                s_val = EloService.calculate_s_value(True, is_first_ac, wa_count)
                tf = TimeFactorService.calculate_time_factor(effective_time, expected_time, s_val)
                time_factors.append(tf)
            if time_factors:
                avg_time_factor = sum(time_factors) / len(time_factors)
                elo_change = round(elo_change * avg_time_factor)

        user.elo = elo_before + elo_change

        # Record Elo history with reason "contest_pr"
        history = EloHistory(
            user_id=user.id,
            elo_before=elo_before,
            elo_after=user.elo,
            elo_change=elo_change,
            reason="contest_pr",
            reference_id=contest_id,
        )
        db.add(history)

        # --- Award contest medal based on PR (FR-10.4) ---
        # Medal is determined by PR vs XCPC tier thresholds, independent of
        # contest group (beginner/advanced/master).
        try:
            await MedalService.award_contest_medal(
                db=db,
                user_id=user.id,
                contest_session_id=contest_id,
                pr=pr,
            )
        except Exception:
            # Medal awarding is best-effort and must not break settlement.
            logger.warning(
                "Failed to award contest medal for contest %s", contest_id, exc_info=True
            )

        # --- Achievement event detection (overkill + personal best PP) ---
        achievements: list[dict] = []

        try:
            # Collect solved problem ratings for overkill check
            solved_stmt = select(ContestProblemRecord).where(
                ContestProblemRecord.contest_id == contest_id,
                ContestProblemRecord.solved.is_(True),
            ).order_by(ContestProblemRecord.problem_rating.desc())
            solved_result = await db.execute(solved_stmt)
            solved_records = solved_result.scalars().all()

            # Check overkill achievement for each solved problem
            for record in solved_records:
                overkill_multiplier = PPService.calculate_overkill_multiplier(
                    elo_before, record.problem_rating,
                )
                overkill_event = AchievementService.check_overkill(
                    user_elo=elo_before,
                    problem_rating=record.problem_rating,
                    multiplier=overkill_multiplier,
                )
                if overkill_event is not None:
                    achievements.append(overkill_event.to_dict())
                    break  # Only report the first (highest) overkill

            # Check personal best PP (PP was already updated in submit_problem)
            if solved_records and user.pp > 0:
                # Calculate PP before this contest by subtracting PP gained
                # from contest problems during this session.
                from app.models.pp_record import PPRecord

                contest_problem_ids = [r.problem_id for r in solved_records]
                pp_gained_stmt = select(PPRecord).where(
                    PPRecord.user_id == user.id,
                    PPRecord.cf_problem_id.in_(contest_problem_ids),
                )
                pp_gained_result = await db.execute(pp_gained_stmt)
                pp_gained_total = sum(r.final_pp for r in pp_gained_result.scalars().all())

                pp_before_contest = user.pp - pp_gained_total
                pp_event = AchievementService.check_personal_best_pp(
                    new_pp=user.pp,
                    old_pp=pp_before_contest,
                )
                if pp_event is not None:
                    achievements.append(pp_event.to_dict())
        except Exception:
            # Achievement detection is best-effort and must not break settlement.
            logger.debug(
                "Achievement detection (overkill/PP) skipped for contest %s",
                contest_id, exc_info=True,
            )

        return elo_change, achievements
