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
from datetime import UTC, datetime

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
from app.services.cf_api_service import CFApiService
from app.services.config_service import ConfigService
from app.services.contest_simulation_service import ContestSimulationService
from app.services.elo_service import EloService
from app.services.pp_service import PPService

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
    (1100, 10),   # gray (800-1099)
    (1400, 20),   # green (1100-1399)
    (1700, 30),   # blue (1400-1699)
    (2000, 40),   # purple (1700-1999)
    (9999, 50),   # yellow/red (2000+)
]


def _tokens_for_rating(rating: int) -> int:
    """Return the AC token reward for a problem at the given rating."""
    for threshold, reward in _TOKEN_TIERS:
        if rating < threshold:
            return reward
    return 50


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

        # Calculate time used
        time_used = 0.0
        if session.started_at is not None:
            delta = now - ContestService._ensure_utc(session.started_at)
            time_used = delta.total_seconds()

        time_limit_seconds = session.time_limit * 60

        # Determine Elo change based on submission count
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
            # 3+ submissions: M-Elo formula with K-factor segmentation and S-value grading
            elo_config = await ConfigService.get_config(db, "elo")
            k_factor_config = {
                "k_newbie": elo_config.get("k_newbie", 40),
                "k_veteran": elo_config.get("k_veteran", 20),
                "k_newbie_threshold": elo_config.get("k_newbie_threshold", 20),
                "k_veteran_threshold": elo_config.get("k_veteran_threshold", 100),
            }
            user_sub_count = await EloService.get_submission_count(db, user.id)

            # Calculate S-values from problem records
            s_values = await ContestService._calculate_contest_s_values(db, contest_id)

            new_rating, elo_change = await EloService.process_contest_result(
                db=db,
                user_id=user.id,
                current_rating=user.elo,
                solved_problems=session.problems_solved,
                total_problems=session.total_problems,
                time_used_seconds=time_used,
                time_limit_seconds=time_limit_seconds,
                contest_session_id=contest_id,
                user_submission_count=user_sub_count,
                k_factor_config=k_factor_config,
                s_values=s_values,
            )
            user.elo = new_rating
            session.elo_change = elo_change

        await db.flush()

        # Build result
        problem_infos = await ContestService._build_problem_infos(db, session)

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
            problems=problem_infos,
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
            problems=problem_infos,
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
        session = await ContestService._get_and_validate_session(
            db, user, contest_id
        )
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
    ) -> None:
        """Auto-end an expired contest using M-Elo settlement."""
        # Stop the background simulation if running
        await ContestSimulationService.stop_simulation(session.id)

        now = datetime.now(UTC)
        session.ended_at = now
        session.status = "completed"

        time_used = 0.0
        if session.started_at is not None:
            delta = now - ContestService._ensure_utc(session.started_at)
            time_used = delta.total_seconds()

        time_limit_seconds = session.time_limit * 60

        # Use M-Elo for auto-ended contests (time ran out, treat as normal completion)
        if session.submissions == 0:
            session.elo_change = 0
        else:
            elo_config = await ConfigService.get_config(db, "elo")
            k_factor_config = {
                "k_newbie": elo_config.get("k_newbie", 40),
                "k_veteran": elo_config.get("k_veteran", 20),
                "k_newbie_threshold": elo_config.get("k_newbie_threshold", 20),
                "k_veteran_threshold": elo_config.get("k_veteran_threshold", 100),
            }
            user_sub_count = await EloService.get_submission_count(db, user.id)

            # Calculate S-values from problem records
            s_values = await ContestService._calculate_contest_s_values(db, session.id)

            new_rating, elo_change = await EloService.process_contest_result(
                db=db,
                user_id=user.id,
                current_rating=user.elo,
                solved_problems=session.problems_solved,
                total_problems=session.total_problems,
                time_used_seconds=time_used,
                time_limit_seconds=time_limit_seconds,
                contest_session_id=session.id,
                user_submission_count=user_sub_count,
                k_factor_config=k_factor_config,
                s_values=s_values,
            )
            user.elo = new_rating
            session.elo_change = elo_change

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
