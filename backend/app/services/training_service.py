"""Training system business logic service.

Handles the training lifecycle:
- Topic listing and problem retrieval from CF API
- Adaptive problem recommendation based on M-Elo
- Training session management (start, submit, abandon)
- Streak tracking and bonus calculation
- Star rating computation
- Cross-session progress tracking
- Token/PP/Elo rewards
"""

import logging
import random
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.elo_history import EloHistory
from app.models.token_transaction import TokenTransaction
from app.models.topic_category import TopicCategory
from app.models.training_problem_record import TrainingProblemRecord
from app.models.training_session import TrainingSession
from app.models.user import User
from app.schemas.training import (
    AbandonTrainingResponse,
    RecommendedProblemResponse,
    SubmitTrainingResponse,
    TopicDetail,
    TopicInfo,
    TopicProblemInfo,
    TopicProgress,
    TrainingProgress,
    TrainingSessionInfo,
)
from app.services import config_service as config_svc
from app.services import economy_service as economy_svc
from app.services.cf_api_service import CFApiService
from app.services.melo_service import MEloService
from app.services.pp_service import PPService

logger = logging.getLogger("code_arena.training")

# ---------------------------------------------------------------------------
# Pre-defined topics mapped to CF tags
# ---------------------------------------------------------------------------

PREDEFINED_TOPICS: list[dict] = [
    {
        "name": "Dynamic Programming",
        "slug": "dp",
        "cf_tags": ["dp"],
        "description": "Dynamic programming problems",
        "display_order": 0,
    },
    {
        "name": "Greedy",
        "slug": "greedy",
        "cf_tags": ["greedy"],
        "description": "Greedy algorithm problems",
        "display_order": 1,
    },
    {
        "name": "Math",
        "slug": "math",
        "cf_tags": ["math"],
        "description": "Mathematical problems",
        "display_order": 2,
    },
    {
        "name": "Graphs",
        "slug": "graphs",
        "cf_tags": ["graphs"],
        "description": "Graph theory problems",
        "display_order": 3,
    },
    {
        "name": "Strings",
        "slug": "strings",
        "cf_tags": ["strings"],
        "description": "String manipulation problems",
        "display_order": 4,
    },
    {
        "name": "Data Structures",
        "slug": "data_structures",
        "cf_tags": ["data structures"],
        "description": "Data structure problems",
        "display_order": 5,
    },
    {
        "name": "Binary Search",
        "slug": "binary_search",
        "cf_tags": ["binary search"],
        "description": "Binary search problems",
        "display_order": 6,
    },
    {
        "name": "Sorting",
        "slug": "sorting",
        "cf_tags": ["sortings"],
        "description": "Sorting problems",
        "display_order": 7,
    },
    {
        "name": "Constructive",
        "slug": "constructive",
        "cf_tags": ["constructive algorithms"],
        "description": "Constructive algorithm problems",
        "display_order": 8,
    },
    {
        "name": "Number Theory",
        "slug": "number_theory",
        "cf_tags": ["number theory"],
        "description": "Number theory problems",
        "display_order": 9,
    },
    {
        "name": "Trees",
        "slug": "trees",
        "cf_tags": ["trees"],
        "description": "Tree problems",
        "display_order": 10,
    },
    {
        "name": "Geometry",
        "slug": "geometry",
        "cf_tags": ["geometry"],
        "description": "Computational geometry problems",
        "display_order": 11,
    },
]

# ---------------------------------------------------------------------------
# Token reward tiers (same as challenge system)
# ---------------------------------------------------------------------------

_TOKEN_TIERS: list[tuple[int, int]] = [
    (1100, 10),   # gray (800-1099)
    (1400, 20),   # green (1100-1399)
    (1700, 30),   # blue (1400-1699)
    (2000, 40),   # purple (1700-1999)
    (9999, 50),   # yellow/red (2000+)
]

_STREAK_BONUS_PER_COUNT = 5
_STREAK_TOKEN_CAP = 50


def _tokens_for_rating(rating: int) -> int:
    """Return the AC token reward for a problem at the given rating."""
    for threshold, reward in _TOKEN_TIERS:
        if rating < threshold:
            return reward
    return 50


def _attempt_tokens_for_rating(rating: int) -> int:
    """Return the attempt token reward for a problem at the given rating."""
    attempt_tiers: list[tuple[int, int]] = [
        (1100, 2),
        (1400, 3),
        (1700, 4),
        (2000, 5),
        (9999, 6),
    ]
    for threshold, reward in attempt_tiers:
        if rating < threshold:
            return reward
    return 6


def calculate_stars(completion_rate: float) -> int:
    """Calculate star rating from completion percentage.

    - 0 stars: 0%
    - 1 star: > 0% and <= 20%
    - 2 stars: > 20% and <= 40%
    - 3 stars: > 40% and <= 60%
    - 4 stars: > 60% and <= 80%
    - 5 stars: > 80%
    """
    if completion_rate <= 0:
        return 0
    if completion_rate <= 20:
        return 1
    if completion_rate <= 40:
        return 2
    if completion_rate <= 60:
        return 3
    if completion_rate <= 80:
        return 4
    return 5


# ---------------------------------------------------------------------------
# Training Service
# ---------------------------------------------------------------------------


class TrainingService:
    """Orchestrates training sessions.

    Stateless service class -- each method receives the resources
    it needs (db session, external services) as parameters.
    """

    # ------------------------------------------------------------------
    # 1. Ensure predefined topics exist in DB
    # ------------------------------------------------------------------

    @staticmethod
    async def ensure_topics(db: AsyncSession) -> None:
        """Create predefined topics in the database if they don't exist."""
        for topic_def in PREDEFINED_TOPICS:
            stmt = select(TopicCategory).where(TopicCategory.slug == topic_def["slug"])
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing is None:
                topic = TopicCategory(
                    name=topic_def["name"],
                    slug=topic_def["slug"],
                    description=topic_def["description"],
                    cf_tags=topic_def["cf_tags"],
                    display_order=topic_def["display_order"],
                )
                db.add(topic)
        await db.flush()

    # ------------------------------------------------------------------
    # 2. List all topics
    # ------------------------------------------------------------------

    @staticmethod
    async def list_topics(
        db: AsyncSession,
        user_id: uuid.UUID | None = None,
        cf_service: CFApiService | None = None,
    ) -> list[TopicInfo]:
        """Return all topics with optional solved-count and stars for a user."""
        await TrainingService.ensure_topics(db)

        stmt = select(TopicCategory).order_by(TopicCategory.display_order)
        result = await db.execute(stmt)
        topics = result.scalars().all()

        topic_infos: list[TopicInfo] = []
        for topic in topics:
            solved_count = 0
            total_problems = 0
            stars = 0

            cf_tags = topic.cf_tags if isinstance(topic.cf_tags, list) else []

            if user_id is not None:
                # Fetch total problems from CF API (same as get_progress)
                if cf_service is not None:
                    problems = await TrainingService._fetch_topic_problems(cf_service, cf_tags)
                    total_problems = len(problems)

                # Count distinct solved problems for this user and topic
                solved_stmt = (
                    select(func.count(TrainingProblemRecord.id))
                    .where(
                        TrainingProblemRecord.user_id == user_id,
                        TrainingProblemRecord.topic_id == topic.id,
                        TrainingProblemRecord.solved.is_(True),
                    )
                )
                solved_result = await db.execute(solved_stmt)
                solved_count = solved_result.scalar_one()

                # Calculate completion rate and stars
                completion_rate = (solved_count / total_problems * 100) if total_problems > 0 else 0.0
                stars = calculate_stars(completion_rate)

            topic_infos.append(TopicInfo(
                id=topic.id,
                name=topic.name,
                slug=topic.slug,
                description=topic.description,
                cf_tags=cf_tags,
                display_order=topic.display_order,
                total_problems=total_problems,
                solved_count=solved_count,
                stars=stars,
            ))

        return topic_infos

    # ------------------------------------------------------------------
    # 3. Get topic detail with problems
    # ------------------------------------------------------------------

    @staticmethod
    async def get_topic_detail(
        db: AsyncSession,
        topic_id: uuid.UUID,
        user_id: uuid.UUID | None,
        cf_service: CFApiService,
    ) -> TopicDetail:
        """Get topic detail including problem list from CF API."""
        topic = await db.get(TopicCategory, topic_id)
        if topic is None:
            raise NotFoundException(message="Topic not found")

        cf_tags = topic.cf_tags if isinstance(topic.cf_tags, list) else []

        # Fetch problems from CF API
        problems = await TrainingService._fetch_topic_problems(cf_service, cf_tags)

        # Sort by rating
        problems.sort(key=lambda p: p.get("rating") or 0)

        # Fetch user's solved status for this topic
        solved_map: dict[str, dict] = {}
        if user_id is not None:
            stmt = (
                select(TrainingProblemRecord)
                .where(
                    TrainingProblemRecord.user_id == user_id,
                    TrainingProblemRecord.topic_id == topic_id,
                )
                .order_by(TrainingProblemRecord.solved_at.desc())
            )
            result = await db.execute(stmt)
            records = result.scalars().all()
            for rec in records:
                # Keep the latest record per problem (solved takes priority)
                if rec.problem_id not in solved_map or rec.solved:
                    solved_map[rec.problem_id] = {
                        "solved": rec.solved,
                        "attempts": rec.attempts,
                        "time_spent": rec.time_spent,
                    }

        # Build problem info list
        problem_infos: list[TopicProblemInfo] = []
        for p in problems:
            pid = f"{p.get('contestId', '')}{p.get('index', '')}"
            solved_info = solved_map.get(pid, {})
            contest_id = p.get("contestId", 0)
            index = p.get("index", "")
            problem_infos.append(TopicProblemInfo(
                problem_id=pid,
                contest_id=contest_id,
                index=index,
                name=p.get("name", ""),
                rating=p.get("rating"),
                tags=p.get("tags", []),
                url=f"https://codeforces.com/problemset/problem/{contest_id}/{index}" if contest_id else "",
                solved=solved_info.get("solved", False),
                attempts=solved_info.get("attempts", 0),
                time_spent=solved_info.get("time_spent"),
            ))

        solved_count = sum(1 for pi in problem_infos if pi.solved)
        total_problems = len(problem_infos)
        completion_rate = (solved_count / total_problems * 100) if total_problems > 0 else 0.0
        stars = calculate_stars(completion_rate)

        return TopicDetail(
            id=topic.id,
            name=topic.name,
            slug=topic.slug,
            description=topic.description,
            cf_tags=cf_tags,
            display_order=topic.display_order,
            total_problems=total_problems,
            solved_count=solved_count,
            stars=stars,
            problems=problem_infos,
        )

    # ------------------------------------------------------------------
    # 3b. Adaptive problem recommendation (M-Elo based)
    # ------------------------------------------------------------------

    @staticmethod
    async def get_adaptive_problem(
        db: AsyncSession,
        user: User,
        topic_id: uuid.UUID,
        cf_service: CFApiService,
    ) -> RecommendedProblemResponse | None:
        """Recommend a problem based on the user's M-Elo for the topic's tag.

        Selection rules (from FR-3.2):
        - Base range: [M-Elo - 100, M-Elo + 200]
        - Fallback round 1: [M-Elo - 200, M-Elo + 300]
        - Fallback round 2: [M-Elo - 300, M-Elo + 400]
        - Round 3 still empty: return None
        - Unsolved filter: exclude problems the user already solved (AC)

        Args:
            db: Async database session.
            user: The current user.
            topic_id: The topic category ID.
            cf_service: CF API service instance.

        Returns:
            A RecommendedProblemResponse with the selected problem, or None
            if no suitable problem is found.
        """
        topic = await db.get(TopicCategory, topic_id)
        if topic is None:
            raise NotFoundException(message="Topic not found")

        cf_tags = topic.cf_tags if isinstance(topic.cf_tags, list) else []
        if not cf_tags:
            return None

        # 1. Get user's M-Elo for the primary tag
        primary_tag = cf_tags[0]
        melo_record = await MEloService.get_or_create_melo(db, user.id, primary_tag)
        melo = melo_record.elo

        # 2. Fetch problems from CF API for this topic
        problems = await TrainingService._fetch_topic_problems(cf_service, cf_tags)
        if not problems:
            return None

        # 3. Build set of solved problem IDs for this user under this topic
        solved_stmt = (
            select(TrainingProblemRecord.problem_id)
            .where(
                TrainingProblemRecord.user_id == user.id,
                TrainingProblemRecord.topic_id == topic_id,
                TrainingProblemRecord.solved.is_(True),
            )
        )
        solved_result = await db.execute(solved_stmt)
        solved_ids = set(solved_result.scalars().all())

        # 4. Filter to unsolved problems with a valid rating
        candidates = [
            p for p in problems
            if p.get("rating") is not None
            and f"{p.get('contestId', '')}{p.get('index', '')}" not in solved_ids
        ]

        if not candidates:
            return None

        # 5. Progressive range search with fallback
        range_rounds = [
            (100, 200),   # base: [M-Elo - 100, M-Elo + 200]
            (200, 300),   # round 1: [M-Elo - 200, M-Elo + 300]
            (300, 400),   # round 2: [M-Elo - 300, M-Elo + 400]
        ]

        for low_offset, high_offset in range_rounds:
            lo = melo - low_offset
            hi = melo + high_offset
            in_range = [p for p in candidates if lo <= p.get("rating", 0) <= hi]
            if in_range:
                chosen = random.choice(in_range)
                contest_id = chosen.get("contestId", 0)
                index = chosen.get("index", "")
                problem_id = f"{contest_id}{index}"
                return RecommendedProblemResponse(
                    problem_id=problem_id,
                    contest_id=contest_id,
                    index=index,
                    name=chosen.get("name", ""),
                    rating=chosen.get("rating"),
                    tags=chosen.get("tags", []),
                    url=f"https://codeforces.com/problemset/problem/{contest_id}/{index}" if contest_id else "",
                    melo=melo,
                    search_range=[lo, hi],
                )

        # 6. No suitable problem found after all rounds
        return None

    # ------------------------------------------------------------------
    # 4. Start training session
    # ------------------------------------------------------------------

    @staticmethod
    async def start_training(
        db: AsyncSession,
        user: User,
        topic_id: uuid.UUID,
        cf_service: CFApiService,
    ) -> TrainingSessionInfo:
        """Start a new training session for a topic."""
        topic = await db.get(TopicCategory, topic_id)
        if topic is None:
            raise NotFoundException(message="Topic not found")

        # Check for existing active session
        active_stmt = (
            select(TrainingSession)
            .where(
                TrainingSession.user_id == user.id,
                TrainingSession.topic_id == topic_id,
                TrainingSession.status == "active",
            )
        )
        active_result = await db.execute(active_stmt)
        active_session = active_result.scalar_one_or_none()
        if active_session is not None:
            raise BadRequestException(message="Already have an active training session for this topic")

        # Fetch problems from CF API to get total count
        cf_tags = topic.cf_tags if isinstance(topic.cf_tags, list) else []
        problems = await TrainingService._fetch_topic_problems(cf_service, cf_tags)
        total_problems = len(problems)

        session = TrainingSession(
            user_id=user.id,
            topic_id=topic_id,
            total_problems=total_problems,
            streak_count=0,
            status="active",
        )
        db.add(session)
        await db.flush()

        return TrainingSessionInfo(
            id=session.id,
            topic_id=topic_id,
            topic_name=topic.name,
            problems_solved=0,
            total_problems=total_problems,
            streak_count=0,
            status="active",
            created_at=session.created_at,
            last_solved_rating=None,
            streak_tokens_earned=0,
        )

    # ------------------------------------------------------------------
    # 5. Get session status
    # ------------------------------------------------------------------

    @staticmethod
    async def get_session_status(
        db: AsyncSession,
        user: User,
        session_id: uuid.UUID,
    ) -> TrainingSessionInfo:
        """Get the current state of a training session."""
        session = await db.get(TrainingSession, session_id)
        if session is None:
            raise NotFoundException(message="Training session not found")
        if session.user_id != user.id:
            raise ForbiddenException(message="Not your training session")

        # Find last solved rating for streak tracking
        last_rating_stmt = (
            select(TrainingProblemRecord.problem_rating)
            .where(
                TrainingProblemRecord.session_id == session_id,
                TrainingProblemRecord.solved.is_(True),
            )
            .order_by(TrainingProblemRecord.solved_at.desc())
            .limit(1)
        )
        last_rating_result = await db.execute(last_rating_stmt)
        last_solved_rating = last_rating_result.scalar_one_or_none()

        # Calculate total streak tokens earned in this session
        streak_tokens_stmt = select(func.coalesce(func.sum(TokenTransaction.amount), 0)).where(
            TokenTransaction.user_id == user.id,
            TokenTransaction.type == "streak_bonus",
            TokenTransaction.reference_id == session_id,
        )
        streak_tokens_result = await db.execute(streak_tokens_stmt)
        streak_tokens_earned = streak_tokens_result.scalar_one()

        topic = await db.get(TopicCategory, session.topic_id)

        return TrainingSessionInfo(
            id=session.id,
            topic_id=session.topic_id,
            topic_name=topic.name if topic else "",
            problems_solved=session.problems_solved,
            total_problems=session.total_problems,
            streak_count=session.streak_count,
            status=session.status,
            created_at=session.created_at,
            completed_at=session.completed_at,
            last_solved_rating=last_solved_rating,
            streak_tokens_earned=streak_tokens_earned,
        )

    # ------------------------------------------------------------------
    # 6. Submit problem result
    # ------------------------------------------------------------------

    @staticmethod
    async def submit_problem(
        db: AsyncSession,
        user: User,
        session_id: uuid.UUID,
        problem_id: str,
        solved: bool,
        attempts: int,
        time_spent: float,
        cf_service: CFApiService | None = None,
    ) -> SubmitTrainingResponse:
        """Submit a problem result in a training session.

        Handles:
        - Recording the attempt
        - Streak tracking (if solved and increasing difficulty)
        - Token rewards (AC reward, attempt reward, streak bonus)
        - PP recording
        - Elo update (small gain for training)
        """
        session = await db.get(TrainingSession, session_id)
        if session is None:
            raise NotFoundException(message="Training session not found")
        if session.user_id != user.id:
            raise ForbiddenException(message="Not your training session")
        if session.status != "active":
            raise BadRequestException(message="Training session is not active")

        # Get problem rating -- try from CF API or fallback
        problem_rating = await TrainingService._get_problem_rating(
            db, session.topic_id, problem_id, cf_service
        )

        # Check for existing record of this problem in this session
        existing_stmt = select(TrainingProblemRecord).where(
            TrainingProblemRecord.session_id == session_id,
            TrainingProblemRecord.problem_id == problem_id,
        )
        existing_result = await db.execute(existing_stmt)
        existing_record = existing_result.scalar_one_or_none()

        if existing_record is not None and existing_record.solved:
            raise BadRequestException(message="Problem already solved in this session")

        # Create or update the problem record
        now = datetime.now(UTC)
        if existing_record is not None:
            # Update existing attempt record
            existing_record.solved = solved
            existing_record.attempts = attempts
            existing_record.time_spent = time_spent
            if solved:
                existing_record.solved_at = now
            record = existing_record
        else:
            record = TrainingProblemRecord(
                session_id=session_id,
                user_id=user.id,
                topic_id=session.topic_id,
                problem_id=problem_id,
                problem_rating=problem_rating,
                solved=solved,
                attempts=attempts,
                time_spent=time_spent,
                solved_at=now if solved else None,
            )
            db.add(record)
        await db.flush()

        # Calculate token rewards
        tokens_earned = 0
        streak_count = session.streak_count
        streak_tokens = 0
        total_streak_tokens = 0

        if solved:
            # AC reward
            ac_tokens = _tokens_for_rating(problem_rating)
            tokens_earned += ac_tokens

            # Update session solved count
            session.problems_solved += 1

            # Streak logic: check if this problem's rating > last solved rating
            last_rating_stmt = (
                select(TrainingProblemRecord.problem_rating)
                .where(
                    TrainingProblemRecord.session_id == session_id,
                    TrainingProblemRecord.solved.is_(True),
                    TrainingProblemRecord.problem_id != problem_id,
                )
                .order_by(TrainingProblemRecord.solved_at.desc())
                .limit(1)
            )
            last_rating_result = await db.execute(last_rating_stmt)
            last_solved_rating = last_rating_result.scalar_one_or_none()

            if last_solved_rating is not None and problem_rating > last_solved_rating:
                # Streak continues
                session.streak_count += 1
                streak_count = session.streak_count
                # Calculate new streak bonus
                # Streak bonus = streak_count * 5, but capped at 50 per session
                # We need to check how much streak bonus has already been given
                streak_tokens_stmt = select(
                    func.coalesce(func.sum(TokenTransaction.amount), 0)
                ).where(
                    TokenTransaction.user_id == user.id,
                    TokenTransaction.type == "streak_bonus",
                    TokenTransaction.reference_id == session_id,
                )
                prev_streak_result = await db.execute(streak_tokens_stmt)
                prev_streak_tokens = prev_streak_result.scalar_one()

                potential_bonus = streak_count * _STREAK_BONUS_PER_COUNT
                remaining_cap = max(0, _STREAK_TOKEN_CAP - prev_streak_tokens)
                streak_tokens = min(potential_bonus, remaining_cap)

                if streak_tokens > 0:
                    tokens_earned += streak_tokens
                    total_streak_tokens = prev_streak_tokens + streak_tokens
                else:
                    total_streak_tokens = prev_streak_tokens
            else:
                # Streak broken
                session.streak_count = 0
                streak_count = 0

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
            )

            # Elo calculation with shield and polarization
            elo_result = await TrainingService._calculate_training_elo(
                db, user, problem_rating, session_id,
                topic_id=session.topic_id, solved=True, attempts=attempts,
            )
            elo_change = elo_result["global_elo_change"]
        else:
            # Attempt reward (smaller than AC)
            attempt_tokens = _attempt_tokens_for_rating(problem_rating)
            tokens_earned += attempt_tokens

            # Check shield for failure -- no Elo deduction if shield is active
            elo_result = await TrainingService._calculate_training_elo(
                db, user, problem_rating, session_id,
                topic_id=session.topic_id, solved=False, attempts=attempts,
            )
            elo_change = elo_result["global_elo_change"]

        # Award tokens via economy_service (enforces daily cap, updates daily_tokens_earned)
        if tokens_earned > 0:
            token_type = "reward_ac" if solved else "reward_attempt"
            if streak_tokens > 0:
                # Record AC and streak separately
                ac_tokens_only = tokens_earned - streak_tokens
                if ac_tokens_only > 0:
                    await economy_svc.award_tokens(
                        db, user, ac_tokens_only,
                        tx_type=token_type,
                        reference_type="training",
                        reference_id=session_id,
                    )
                await economy_svc.award_tokens(
                    db, user, streak_tokens,
                    tx_type="streak_bonus",
                    reference_type="training",
                    reference_id=session_id,
                )
            else:
                await economy_svc.award_tokens(
                    db, user, tokens_earned,
                    tx_type=token_type,
                    reference_type="training",
                    reference_id=session_id,
                )

            # Time bonus: if solved and time_spent > 20 min, award extra tokens
            if solved and time_spent > economy_svc.TIME_BONUS_THRESHOLD_SECONDS:
                time_bonus = economy_svc.time_bonus_for_rating(problem_rating)
                if time_bonus > 0:
                    await economy_svc.award_tokens(
                        db, user, time_bonus,
                        tx_type="time_bonus",
                        reference_type="training",
                        reference_id=session_id,
                    )
                    tokens_earned += time_bonus

        await db.flush()

        return SubmitTrainingResponse(
            session_id=session_id,
            problem_id=problem_id,
            solved=solved,
            streak_count=streak_count,
            streak_tokens=streak_tokens,
            total_streak_tokens=total_streak_tokens,
            tokens_earned=tokens_earned,
            elo_change=elo_change,
        )

    # ------------------------------------------------------------------
    # 7. Abandon training
    # ------------------------------------------------------------------

    @staticmethod
    async def abandon_training(
        db: AsyncSession,
        user: User,
        session_id: uuid.UUID,
    ) -> AbandonTrainingResponse:
        """Abandon an active training session.

        Applies quit-penalty Elo deduction following the rules in section 4.6:
        - 0 submissions (no problems attempted): Elo unchanged
        - 1-2 submissions: small penalty (-5 to -10)
        - 3+ submissions: normal failure Elo calculation

        The learning shield (Task 16.2) protects against Elo deductions
        when the user has never AC'd a problem with the topic's primary tag.
        """
        session = await db.get(TrainingSession, session_id)
        if session is None:
            raise NotFoundException(message="Training session not found")
        if session.user_id != user.id:
            raise ForbiddenException(message="Not your training session")
        if session.status != "active":
            raise BadRequestException(message="Training session is not active")

        session.status = "abandoned"
        session.completed_at = datetime.now(UTC)

        # Count total submissions in this session
        count_stmt = select(func.count(TrainingProblemRecord.id)).where(
            TrainingProblemRecord.session_id == session_id,
        )
        count_result = await db.execute(count_stmt)
        submission_count = count_result.scalar_one()

        # Check shield status for the topic's primary tag
        primary_tag = await TrainingService._get_primary_tag_for_topic(db, session.topic_id)
        shield_active = False
        if primary_tag:
            shield_active = await MEloService.is_shield_active(db, user.id, primary_tag)

        elo_change: int | None = None

        if submission_count == 0:
            # No submissions: Elo unchanged
            pass
        elif shield_active:
            # Shield active: no Elo deduction on abandon
            logger.info(
                "Shield active for user=%s tag=%s -- skipping Elo deduction on abandon",
                user.id, primary_tag,
            )
        else:
            # Apply quit penalty via _calculate_training_elo with solved=False
            # This uses the standard failure calculation with polarization coefficients
            elo_result = await TrainingService._calculate_training_elo(
                db, user,
                problem_rating=user.elo,  # Use user's Elo as baseline for quit penalty
                session_id=session_id,
                topic_id=session.topic_id,
                solved=False,
                attempts=submission_count,
            )
            elo_change = elo_result["global_elo_change"]

        await db.flush()

        return AbandonTrainingResponse(
            session_id=session.id,
            status="abandoned",
            problems_solved=session.problems_solved,
            total_problems=session.total_problems,
            elo_change=elo_change,
            shield_active=shield_active,
        )

    # ------------------------------------------------------------------
    # 8. Get user progress across all topics
    # ------------------------------------------------------------------

    @staticmethod
    async def get_progress(
        db: AsyncSession,
        user_id: uuid.UUID,
        cf_service: CFApiService,
    ) -> TrainingProgress:
        """Get the user's progress across all topics."""
        await TrainingService.ensure_topics(db)

        stmt = select(TopicCategory).order_by(TopicCategory.display_order)
        result = await db.execute(stmt)
        topics = result.scalars().all()

        topic_progress_list: list[TopicProgress] = []
        total_solved = 0
        total_problems = 0

        for topic in topics:
            cf_tags = topic.cf_tags if isinstance(topic.cf_tags, list) else []

            # Get total problems from CF API
            problems = await TrainingService._fetch_topic_problems(cf_service, cf_tags)
            topic_total = len(problems)

            # Get solved count
            solved_stmt = (
                select(func.count(TrainingProblemRecord.id))
                .where(
                    TrainingProblemRecord.user_id == user_id,
                    TrainingProblemRecord.topic_id == topic.id,
                    TrainingProblemRecord.solved.is_(True),
                )
            )
            solved_result = await db.execute(solved_stmt)
            solved_count = solved_result.scalar_one()

            # Get total attempts and time
            agg_stmt = (
                select(
                    func.coalesce(func.sum(TrainingProblemRecord.attempts), 0),
                    func.coalesce(func.sum(TrainingProblemRecord.time_spent), 0),
                )
                .where(
                    TrainingProblemRecord.user_id == user_id,
                    TrainingProblemRecord.topic_id == topic.id,
                )
            )
            agg_result = await db.execute(agg_stmt)
            agg_row = agg_result.one()
            total_attempts = agg_row[0]
            total_time_spent = agg_row[1]

            completion_rate = (solved_count / topic_total * 100) if topic_total > 0 else 0.0

            topic_progress_list.append(TopicProgress(
                topic_id=topic.id,
                topic_name=topic.name,
                slug=topic.slug,
                total_problems=topic_total,
                solved_count=solved_count,
                completion_rate=round(completion_rate, 2),
                stars=calculate_stars(completion_rate),
                total_attempts=total_attempts,
                total_time_spent=total_time_spent or 0.0,
            ))

            total_solved += solved_count
            total_problems += topic_total

        return TrainingProgress(
            topics=topic_progress_list,
            total_solved=total_solved,
            total_problems=total_problems,
        )

    # ------------------------------------------------------------------
    # 9. Get user progress for a single topic
    # ------------------------------------------------------------------

    @staticmethod
    async def get_topic_progress(
        db: AsyncSession,
        user_id: uuid.UUID,
        topic_id: uuid.UUID,
        cf_service: CFApiService,
    ) -> TopicProgress:
        """Get the user's detailed progress for a specific topic."""
        topic = await db.get(TopicCategory, topic_id)
        if topic is None:
            raise NotFoundException(message="Topic not found")

        cf_tags = topic.cf_tags if isinstance(topic.cf_tags, list) else []

        # Get total problems from CF API
        problems = await TrainingService._fetch_topic_problems(cf_service, cf_tags)
        topic_total = len(problems)

        # Get solved count
        solved_stmt = (
            select(func.count(TrainingProblemRecord.id))
            .where(
                TrainingProblemRecord.user_id == user_id,
                TrainingProblemRecord.topic_id == topic_id,
                TrainingProblemRecord.solved.is_(True),
            )
        )
        solved_result = await db.execute(solved_stmt)
        solved_count = solved_result.scalar_one()

        # Get total attempts and time
        agg_stmt = (
            select(
                func.coalesce(func.sum(TrainingProblemRecord.attempts), 0),
                func.coalesce(func.sum(TrainingProblemRecord.time_spent), 0),
            )
            .where(
                TrainingProblemRecord.user_id == user_id,
                TrainingProblemRecord.topic_id == topic_id,
            )
        )
        agg_result = await db.execute(agg_stmt)
        agg_row = agg_result.one()
        total_attempts = agg_row[0]
        total_time_spent = agg_row[1]

        completion_rate = (solved_count / topic_total * 100) if topic_total > 0 else 0.0

        return TopicProgress(
            topic_id=topic.id,
            topic_name=topic.name,
            slug=topic.slug,
            total_problems=topic_total,
            solved_count=solved_count,
            completion_rate=round(completion_rate, 2),
            stars=calculate_stars(completion_rate),
            total_attempts=total_attempts,
            total_time_spent=total_time_spent or 0.0,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _fetch_topic_problems(
        cf_service: CFApiService,
        cf_tags: list[str],
    ) -> list[dict]:
        """Fetch problems for a topic from CF API.

        Returns a list of problem dicts with keys:
        contestId, index, name, rating, tags
        """
        try:
            data = await cf_service.get_problemset_problems(tags=cf_tags)
            return data.get("problems", [])
        except Exception:
            logger.warning("CF API unavailable for tags %s, returning empty list", cf_tags)
            return []

    @staticmethod
    async def _get_problem_rating(
        db: AsyncSession,
        topic_id: uuid.UUID,
        problem_id: str,
        cf_service: CFApiService | None,
    ) -> int:
        """Get the rating for a problem.

        First checks existing records, then falls back to CF API.
        """
        # Check existing records
        stmt = (
            select(TrainingProblemRecord.problem_rating)
            .where(TrainingProblemRecord.problem_id == problem_id)
            .limit(1)
        )
        result = await db.execute(stmt)
        existing_rating = result.scalar_one_or_none()
        if existing_rating is not None:
            return existing_rating

        # Try CF API
        if cf_service is not None:
            try:
                data = await cf_service.get_problemset_problems()
                for p in data.get("problems", []):
                    pid = f"{p.get('contestId', '')}{p.get('index', '')}"
                    if pid == problem_id:
                        return p.get("rating", 1000)
            except Exception:
                pass

        # Default rating
        return 1000

    @staticmethod
    async def _get_primary_tag_for_topic(
        db: AsyncSession,
        topic_id: uuid.UUID,
    ) -> str | None:
        """Get the primary CF tag for a topic.

        Returns the first tag in the topic's cf_tags list, or None if
        the topic has no tags.
        """
        topic = await db.get(TopicCategory, topic_id)
        if topic is None:
            return None
        cf_tags = topic.cf_tags if isinstance(topic.cf_tags, list) else []
        return cf_tags[0] if cf_tags else None

    @staticmethod
    async def _calculate_training_elo(
        db: AsyncSession,
        user: User,
        problem_rating: int,
        session_id: uuid.UUID,
        topic_id: uuid.UUID,
        solved: bool,
        attempts: int = 1,
    ) -> dict:
        """Calculate and apply Elo changes for a training problem result.

        Implements two features:
        - **Learning Shield (Task 16.2)**: If the shield is active for the
          topic's primary tag and the user failed/abandoned, no Elo changes
          are applied (neither Global nor M-Elo).
        - **Weight Polarization (Task 16.3)**: On AC, Global Elo changes are
          multiplied by ``training_global_coefficient`` (default 0.5) and
          M-Elo changes by ``training_melo_coefficient`` (default 2.0).

        Returns a dict with keys:
            global_elo_change: int | None  -- change applied to Global Elo
            melo_change: int | None        -- change applied to M-Elo
            shield_active: bool            -- whether shield was active
        """
        from app.services.elo_service import EloService

        # Resolve the primary CF tag for the topic
        primary_tag = await TrainingService._get_primary_tag_for_topic(db, topic_id)

        # Check learning shield status
        shield_active = False
        if primary_tag:
            shield_active = await MEloService.is_shield_active(db, user.id, primary_tag)

        # --- Shield protection for failures ---
        if not solved and shield_active:
            logger.info(
                "Shield active for user=%s tag=%s -- skipping Elo deduction on failure",
                user.id, primary_tag,
            )
            return {
                "global_elo_change": None,
                "melo_change": None,
                "shield_active": True,
            }

        # --- Shield deactivation on first AC ---
        if solved and shield_active and primary_tag:
            await MEloService.deactivate_shield(db, user.id, primary_tag)
            logger.info(
                "Shield deactivated for user=%s tag=%s on first AC",
                user.id, primary_tag,
            )

        # --- Load configurable coefficients ---
        try:
            global_coeff = await config_svc.ConfigService.get_config(db, "melo.training_global_coefficient")
        except (KeyError, Exception):
            global_coeff = 0.5
        try:
            melo_coeff = await config_svc.ConfigService.get_config(db, "melo.training_melo_coefficient")
        except (KeyError, Exception):
            melo_coeff = 2.0

        k_train = 8

        # Calculate S-value based on attempts
        if solved:
            is_first_ac = attempts <= 1
            error_count = max(0, attempts - 1)
            s_value = EloService.calculate_s_value(
                is_solved=True,
                is_first_ac=is_first_ac,
                error_count=error_count,
            )
        else:
            s_value = 0.0

        # --- Global Elo calculation ---
        global_expected = 1.0 / (1.0 + 10.0 ** ((problem_rating - user.elo) / 400.0))
        global_elo_change = round(k_train * (s_value - global_expected) * global_coeff)

        if global_elo_change != 0:
            elo_before = user.elo
            user.elo += global_elo_change

            history = EloHistory(
                user_id=user.id,
                elo_before=elo_before,
                elo_after=user.elo,
                elo_change=global_elo_change,
                reason="training",
                reference_id=session_id,
            )
            db.add(history)

        # --- M-Elo calculation ---
        melo_change: int | None = None
        if primary_tag:
            melo_record = await MEloService.get_or_create_melo(db, user.id, primary_tag)
            melo_expected = 1.0 / (1.0 + 10.0 ** ((problem_rating - melo_record.elo) / 400.0))
            melo_change = round(k_train * (s_value - melo_expected) * melo_coeff)

            if melo_change != 0:
                await MEloService.update_melo(db, user.id, primary_tag, melo_change)

        return {
            "global_elo_change": global_elo_change,
            "melo_change": melo_change,
            "shield_active": shield_active,
        }
