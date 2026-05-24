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
import time
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
    CuratedProblemInfo,
    CuratedProblemsResponse,
    MedalInfo,
    RecommendedProblemResponse,
    RecommendedTopicResponse,
    SkipProblemResponse,
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
from app.services.achievement_service import AchievementService
from app.services.cf_api_service import CFApiService
from app.services.hint_service import HintService
from app.services.medal_service import _FLAT_MEDAL_MAP, MedalService
from app.services.melo_service import MEloService
from app.services.pp_service import PPService
from app.services.submission_tracker import SubmissionTracker
from app.services.time_factor_service import TimeFactorService

logger = logging.getLogger("code_arena.training")

# ---------------------------------------------------------------------------
# Pre-defined topics mapped to CF tags
# ---------------------------------------------------------------------------

PREDEFINED_TOPICS: list[dict] = [
    {
        "name": "Dynamic Programming",
        "name_zh": "动态规划",
        "slug": "dp",
        "cf_tags": ["dp"],
        "description": "Dynamic programming problems",
        "display_order": 0,
    },
    {
        "name": "Greedy",
        "name_zh": "贪心",
        "slug": "greedy",
        "cf_tags": ["greedy"],
        "description": "Greedy algorithm problems",
        "display_order": 1,
    },
    {
        "name": "Math",
        "name_zh": "数学",
        "slug": "math",
        "cf_tags": ["math"],
        "description": "Mathematical problems",
        "display_order": 2,
    },
    {
        "name": "Graphs",
        "name_zh": "图论",
        "slug": "graphs",
        "cf_tags": ["graphs"],
        "description": "Graph theory problems",
        "display_order": 3,
    },
    {
        "name": "Strings",
        "name_zh": "字符串",
        "slug": "strings",
        "cf_tags": ["strings"],
        "description": "String manipulation problems",
        "display_order": 4,
    },
    {
        "name": "Data Structures",
        "name_zh": "数据结构",
        "slug": "data_structures",
        "cf_tags": ["data structures"],
        "description": "Data structure problems",
        "display_order": 5,
    },
    {
        "name": "Binary Search",
        "name_zh": "二分搜索",
        "slug": "binary_search",
        "cf_tags": ["binary search"],
        "description": "Binary search problems",
        "display_order": 6,
    },
    {
        "name": "Sorting",
        "name_zh": "排序",
        "slug": "sorting",
        "cf_tags": ["sortings"],
        "description": "Sorting problems",
        "display_order": 7,
    },
    {
        "name": "Constructive",
        "name_zh": "构造",
        "slug": "constructive",
        "cf_tags": ["constructive algorithms"],
        "description": "Constructive algorithm problems",
        "display_order": 8,
    },
    {
        "name": "Number Theory",
        "name_zh": "数论",
        "slug": "number_theory",
        "cf_tags": ["number theory"],
        "description": "Number theory problems",
        "display_order": 9,
    },
    {
        "name": "Trees",
        "name_zh": "树",
        "slug": "trees",
        "cf_tags": ["trees"],
        "description": "Tree problems",
        "display_order": 10,
    },
    {
        "name": "Geometry",
        "name_zh": "几何",
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
    (1200, 10),  # gray (800-1199)
    (1400, 20),  # green (1200-1399)
    (1600, 25),  # cyan (1400-1599)
    (1900, 35),  # blue (1600-1899)
    (2100, 45),  # purple (1900-2099)
    (2400, 55),  # orange (2100-2399)
    (9999, 65),  # red (2400+)
]

_STREAK_BONUS_PER_COUNT = 5
_STREAK_TOKEN_CAP = 50


def _tokens_for_rating(rating: int) -> int:
    """Return the AC token reward for a problem at the given rating."""
    for threshold, reward in _TOKEN_TIERS:
        if rating < threshold:
            return reward
    return 65


def _attempt_tokens_for_rating(rating: int) -> int:
    """Return the attempt token reward for a problem at the given rating."""
    attempt_tiers: list[tuple[int, int]] = [
        (1200, 2),
        (1400, 3),
        (1600, 4),
        (1900, 5),
        (2100, 6),
        (2400, 7),
        (9999, 8),
    ]
    for threshold, reward in attempt_tiers:
        if rating < threshold:
            return reward
    return 8


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


def calculate_stars_from_melo(melo: float | None) -> int:
    """Calculate star rating from M-Elo.

    - 0 stars: no M-Elo (user never touched this tag)
    - 1 star: M-Elo < 1000
    - 2 stars: M-Elo < 1200
    - 3 stars: M-Elo < 1400
    - 4 stars: M-Elo < 1600
    - 5 stars: M-Elo < 1800
    - 6 stars: M-Elo < 2000
    - 7 stars: M-Elo >= 2000
    """
    if melo is None:
        return 0
    if melo < 1000:
        return 1
    if melo < 1200:
        return 2
    if melo < 1400:
        return 3
    if melo < 1600:
        return 4
    if melo < 1800:
        return 5
    if melo < 2000:
        return 6
    return 7


def _compute_medal_info(melo: float | None) -> tuple[MedalInfo, int | None, int | None]:
    """Compute medal info, current threshold, and next threshold from M-Elo.

    Returns:
        (medal_info, current_medal_threshold, next_medal_threshold)
    """
    if melo is None:
        # Unranked: no medal, next threshold is provincial bronze (1200)
        return MedalInfo(level="unranked", type=None), None, 1200

    medal = MedalService._rating_to_medal(int(melo))

    if medal["level"] == "unranked":
        return MedalInfo(level="unranked", type=None), None, 1200

    medal_type = medal["type"]
    medal_level = medal["level"]

    # Find the entry in _FLAT_MEDAL_MAP that matches the current medal
    current_threshold = None
    current_idx = None
    for idx, (threshold, level, mtype) in enumerate(_FLAT_MEDAL_MAP):
        if level == medal_level and mtype == medal_type:
            current_threshold = threshold
            current_idx = idx
            break

    if current_idx is None:
        # Should not happen, but fallback
        return MedalInfo(level=medal_level, type=medal_type), None, None

    # Next threshold: the entry BEFORE it in the list (higher threshold)
    next_threshold = None if current_idx == 0 else _FLAT_MEDAL_MAP[current_idx - 1][0]

    return MedalInfo(level=medal_level, type=medal_type), current_threshold, next_threshold


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

    @staticmethod
    def _get_name_zh(slug: str) -> str:
        """Look up the Chinese name for a topic by its slug."""
        for topic_def in PREDEFINED_TOPICS:
            if topic_def["slug"] == slug:
                return topic_def.get("name_zh", "")
        return ""

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

        # Bulk-fetch all CF problems once (1 API call instead of N)
        all_problems: list[dict] = []
        if user_id is not None and cf_service is not None:
            all_problems = await TrainingService._get_all_problems_cached(cf_service)

        # Bulk-fetch all M-Elo records for this user (1 query instead of N)
        melo_map: dict[str, object] = {}
        if user_id is not None:
            melo_records = await MEloService.get_all_melos(db, user_id)
            melo_map = {m.tag: m for m in melo_records}

        topic_infos: list[TopicInfo] = []
        for topic in topics:
            solved_count = 0
            total_problems = 0
            stars = 0
            melo: float | None = None
            shield_active = False

            cf_tags = topic.cf_tags if isinstance(topic.cf_tags, list) else []
            primary_tag = cf_tags[0] if cf_tags else None

            if user_id is not None:
                # Filter pre-fetched problems by topic tags (in-memory)
                if cf_service is not None:
                    problems = TrainingService._filter_problems_by_tags(all_problems, cf_tags)
                    total_problems = len(problems)

                # Count distinct solved problems for this user and topic
                solved_stmt = select(func.count(TrainingProblemRecord.id)).where(
                    TrainingProblemRecord.user_id == user_id,
                    TrainingProblemRecord.topic_id == topic.id,
                    TrainingProblemRecord.solved.is_(True),
                )
                solved_result = await db.execute(solved_stmt)
                solved_count = solved_result.scalar_one()

                # Look up M-Elo for the topic's primary tag
                if primary_tag:
                    melo_rec = melo_map.get(primary_tag)
                    if melo_rec is None:
                        # User never touched this tag -- shield active, no melo
                        melo = None
                        shield_active = True
                    else:
                        melo = float(melo_rec.elo)
                        shield_active = melo_rec.first_ac_at is None

                # Calculate stars based on M-Elo
                stars = calculate_stars_from_melo(melo)

            # Compute medal info from M-Elo
            medal_info, current_medal_threshold, next_medal_threshold = _compute_medal_info(melo)

            topic_infos.append(
                TopicInfo(
                    id=topic.id,
                    name=topic.name,
                    name_zh=TrainingService._get_name_zh(topic.slug),
                    slug=topic.slug,
                    description=topic.description,
                    cf_tags=cf_tags,
                    display_order=topic.display_order,
                    total_problems=total_problems,
                    solved_count=solved_count,
                    stars=stars,
                    melo=melo,
                    shield_active=shield_active,
                    medal=medal_info,
                    current_medal_threshold=current_medal_threshold,
                    next_medal_threshold=next_medal_threshold,
                )
            )

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

        # Fetch all problems once, then filter by tags in-memory
        all_problems = await TrainingService._get_all_problems_cached(cf_service)
        problems = TrainingService._filter_problems_by_tags(all_problems, cf_tags)

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
            problem_infos.append(
                TopicProblemInfo(
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
                )
            )

        solved_count = sum(1 for pi in problem_infos if pi.solved)
        total_problems = len(problem_infos)

        # Look up M-Elo for the topic's primary tag
        melo: float | None = None
        shield_active = False
        primary_tag = cf_tags[0] if cf_tags else None
        if user_id is not None and primary_tag:
            melo_rec = await MEloService.get_or_create_melo(db, user_id, primary_tag)
            melo = float(melo_rec.elo)
            shield_active = melo_rec.first_ac_at is None

        stars = calculate_stars_from_melo(melo)

        # Compute medal info from M-Elo
        medal_info, current_medal_threshold, next_medal_threshold = _compute_medal_info(melo)

        return TopicDetail(
            id=topic.id,
            name=topic.name,
            name_zh=TrainingService._get_name_zh(topic.slug),
            slug=topic.slug,
            description=topic.description,
            cf_tags=cf_tags,
            display_order=topic.display_order,
            total_problems=total_problems,
            solved_count=solved_count,
            stars=stars,
            melo=melo,
            shield_active=shield_active,
            medal=medal_info,
            current_medal_threshold=current_medal_threshold,
            next_medal_threshold=next_medal_threshold,
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

        # 2. Fetch all problems once, then filter by tags in-memory
        all_problems = await TrainingService._get_all_problems_cached(cf_service)
        problems = TrainingService._filter_problems_by_tags(all_problems, cf_tags)
        if not problems:
            return None

        # 3. Build set of solved problem IDs for this user under this topic
        solved_stmt = select(TrainingProblemRecord.problem_id).where(
            TrainingProblemRecord.user_id == user.id,
            TrainingProblemRecord.topic_id == topic_id,
            TrainingProblemRecord.solved.is_(True),
        )
        solved_result = await db.execute(solved_stmt)
        solved_ids = set(solved_result.scalars().all())

        # 4. Filter to unsolved problems with a valid rating
        candidates = [
            p
            for p in problems
            if p.get("rating") is not None and f"{p.get('contestId', '')}{p.get('index', '')}" not in solved_ids
        ]

        if not candidates:
            return None

        # 5. Progressive range search with fallback
        range_rounds = [
            (100, 200),  # base: [M-Elo - 100, M-Elo + 200]
            (200, 300),  # round 1: [M-Elo - 200, M-Elo + 300]
            (300, 400),  # round 2: [M-Elo - 300, M-Elo + 400]
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
    # 3c. Curated problem list with pagination and difficulty filter
    # ------------------------------------------------------------------

    @staticmethod
    async def get_curated_problems(
        db: AsyncSession,
        topic_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        limit: int = 20,
        offset: int = 0,
        min_rating: int | None = None,
        max_rating: int | None = None,
        cf_service: CFApiService | None = None,
    ) -> CuratedProblemsResponse:
        """Return a curated subset of problems for a topic.

        Curation logic:
        1. Fetch all problems for the topic's CF tags
        2. Filter by rating bounds if provided
        3. Sort by rating and segment into 200-point buckets
        4. From each bucket, pick up to 5 representative problems
           (preferring problems with lower rating first for approachability)
        5. Apply offset/limit for pagination
        6. Mark which ones the user has solved
        """
        topic = await db.get(TopicCategory, topic_id)
        if topic is None:
            raise NotFoundException(message="Topic not found")

        cf_tags = topic.cf_tags if isinstance(topic.cf_tags, list) else []

        # Fetch all problems for this topic
        all_problems: list[dict] = []
        if cf_service is not None:
            all_problems = await TrainingService._get_all_problems_cached(cf_service)
        problems = TrainingService._filter_problems_by_tags(all_problems, cf_tags)

        # Filter to problems with a valid rating
        rated = [p for p in problems if p.get("rating") is not None]

        # Apply rating filters
        if min_rating is not None:
            rated = [p for p in rated if p["rating"] >= min_rating]
        if max_rating is not None:
            rated = [p for p in rated if p["rating"] <= max_rating]

        # Sort by rating ascending
        rated.sort(key=lambda p: p["rating"])

        if not rated:
            return CuratedProblemsResponse(
                problems=[],
                total=0,
                offset=offset,
                limit=limit,
            )

        # Segment into 200-point buckets and pick representatives
        buckets: dict[int, list[dict]] = {}
        for p in rated:
            bucket_key = (p["rating"] // 200) * 200
            buckets.setdefault(bucket_key, []).append(p)

        curated: list[dict] = []
        for key in sorted(buckets.keys()):
            bucket_problems = buckets[key]
            # Pick up to 5 from each bucket, preferring lower rating
            curated.extend(bucket_problems[:5])

        # Total count after curation (before pagination)
        total_curated = len(curated)

        # Apply pagination
        paginated = curated[offset : offset + limit]

        # Fetch user's solved status for this topic
        solved_ids: set[str] = set()
        if user_id is not None:
            solved_stmt = select(TrainingProblemRecord.problem_id).where(
                TrainingProblemRecord.user_id == user_id,
                TrainingProblemRecord.topic_id == topic_id,
                TrainingProblemRecord.solved.is_(True),
            )
            solved_result = await db.execute(solved_stmt)
            solved_ids = set(solved_result.scalars().all())

        # Build response
        problem_infos: list[CuratedProblemInfo] = []
        for p in paginated:
            contest_id = p.get("contestId", 0)
            index = p.get("index", "")
            pid = f"{contest_id}{index}"
            problem_infos.append(
                CuratedProblemInfo(
                    problem_id=pid,
                    contest_id=contest_id,
                    index=index,
                    name=p.get("name", ""),
                    rating=p.get("rating"),
                    tags=p.get("tags", []),
                    url=f"https://codeforces.com/problemset/problem/{contest_id}/{index}" if contest_id else "",
                    solved=pid in solved_ids,
                )
            )

        return CuratedProblemsResponse(
            problems=problem_infos,
            total=total_curated,
            offset=offset,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # 3d. Recommend topics based on user's weakest M-Elo
    # ------------------------------------------------------------------

    @staticmethod
    async def get_recommended_topics(
        db: AsyncSession,
        user_id: uuid.UUID,
        limit: int = 3,
    ) -> list[RecommendedTopicResponse]:
        """Recommend topics the user should prioritize.

        Logic: Sort all predefined topics by the user's M-Elo for each
        topic's primary tag (ascending -- weakest first), then return
        the top *limit* topics with a reason string.
        """
        await TrainingService.ensure_topics(db)

        # Bulk-fetch all M-Elo records for this user
        melo_records = await MEloService.get_all_melos(db, user_id)
        melo_map: dict[str, object] = {m.tag: m for m in melo_records}

        # Build topic M-Elo entries
        topic_melos: list[dict] = []
        for topic_def in PREDEFINED_TOPICS:
            primary_tag = topic_def["cf_tags"][0] if topic_def["cf_tags"] else None
            if primary_tag is None:
                continue

            melo_rec = melo_map.get(primary_tag)
            # No M-Elo record = user never touched this tag
            melo_val = None if melo_rec is None else float(melo_rec.elo)

            topic_melos.append(
                {
                    "slug": topic_def["slug"],
                    "name": topic_def["name"],
                    "name_zh": topic_def.get("name_zh", ""),
                    "melo": melo_val,
                    "primary_tag": primary_tag,
                }
            )

        # Sort: None (never practiced) treated as weakest (sort first),
        # then ascending by M-Elo
        def _sort_key(entry: dict) -> float:
            melo = entry["melo"]
            if melo is None:
                return -1.0  # Never practiced = weakest
            return melo

        topic_melos.sort(key=_sort_key)

        # Take top N
        results: list[RecommendedTopicResponse] = []
        for entry in topic_melos[:limit]:
            name = entry["name"]
            name_zh = entry["name_zh"]
            melo = entry["melo"]
            if melo is None:
                reason = f"Your {name} M-Elo is unestablished -- start practicing!"
            else:
                reason = f"Your {name} M-Elo is {melo:.0f}, the weakest area to improve"
            results.append(
                RecommendedTopicResponse(
                    slug=entry["slug"],
                    name=name,
                    name_zh=name_zh,
                    melo=melo,
                    reason=reason,
                )
            )

        return results

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
        active_stmt = select(TrainingSession).where(
            TrainingSession.user_id == user.id,
            TrainingSession.topic_id == topic_id,
            TrainingSession.status == "active",
        )
        active_result = await db.execute(active_stmt)
        active_session = active_result.scalar_one_or_none()
        if active_session is not None:
            raise BadRequestException(message="Already have an active training session for this topic")

        # Fetch all problems once, then filter by tags in-memory
        cf_tags = topic.cf_tags if isinstance(topic.cf_tags, list) else []
        all_problems = await TrainingService._get_all_problems_cached(cf_service)
        problems = TrainingService._filter_problems_by_tags(all_problems, cf_tags)
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
            started_at=session.started_at,
            last_solved_rating=None,
            streak_tokens_earned=0,
        )

    # ------------------------------------------------------------------
    # 4b. Get active session for a topic (session recovery)
    # ------------------------------------------------------------------

    @staticmethod
    async def get_active_session_for_topic(
        db: AsyncSession,
        user: User,
        topic_id: uuid.UUID,
    ) -> TrainingSessionInfo | None:
        """Return the user's active training session for a given topic, or None.

        Used for session recovery: when the user refreshes the TrainingDetailPage,
        this checks whether there is an active session to resume.
        """
        stmt = select(TrainingSession).where(
            TrainingSession.user_id == user.id,
            TrainingSession.topic_id == topic_id,
            TrainingSession.status == "active",
        )
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        if session is None:
            return None

        topic = await db.get(TopicCategory, session.topic_id)

        # Find last solved rating
        last_rating_stmt = (
            select(TrainingProblemRecord.problem_rating)
            .where(
                TrainingProblemRecord.session_id == session.id,
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
            TokenTransaction.reference_id == session.id,
        )
        streak_tokens_result = await db.execute(streak_tokens_stmt)
        streak_tokens_earned = streak_tokens_result.scalar_one()

        return TrainingSessionInfo(
            id=session.id,
            topic_id=session.topic_id,
            topic_name=topic.name if topic else "",
            problems_solved=session.problems_solved,
            total_problems=session.total_problems,
            streak_count=session.streak_count,
            status=session.status,
            created_at=session.created_at,
            started_at=session.started_at,
            completed_at=session.completed_at,
            last_solved_rating=last_solved_rating,
            streak_tokens_earned=streak_tokens_earned,
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
            started_at=session.started_at,
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
        problem_rating = await TrainingService._get_problem_rating(db, session.topic_id, problem_id, cf_service)

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

            # Register pending submission tracking so the CF API poller can
            # automatically detect when the user submits on Codeforces.
            await SubmissionTracker.register_pending(
                db=db,
                user_id=user.id,
                session_type="training",
                session_id=session_id,
                problem_id=problem_id,
                expected_at=datetime.now(UTC),
            )
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

            # Streak logic: every AC increments streak (consecutive AC count)
            session.streak_count += 1
            streak_count = session.streak_count
            # Calculate new streak bonus
            # Streak bonus = streak_count * 5, but capped at 50 per session
            # We need to check how much streak bonus has already been given
            streak_tokens_stmt = select(func.coalesce(func.sum(TokenTransaction.amount), 0)).where(
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

            # Record PP
            wa_count = max(0, attempts - 1)
            time_spent_minutes = (time_spent or 0.0) / 60.0
            pp_before_record = user.pp
            await PPService.record_pp(
                db=db,
                user_id=user.id,
                cf_problem_id=problem_id,
                problem_rating=problem_rating,
                wa_count=wa_count,
                time_spent=time_spent_minutes,
                user_elo=user.elo,
            )
            pp_change = round(user.pp - pp_before_record, 2)

            # Capture Elo before settlement (used for overkill detection)
            elo_before = user.elo

            # Elo calculation with shield and polarization
            elo_result = await TrainingService._calculate_training_elo(
                db,
                user,
                problem_rating,
                session_id,
                topic_id=session.topic_id,
                solved=True,
                attempts=attempts,
                problem_id=problem_id,
                time_spent=time_spent,
                cf_service=cf_service,
            )
            elo_change = elo_result["global_elo_change"]
        else:
            # Attempt reward (smaller than AC)
            attempt_tokens = _attempt_tokens_for_rating(problem_rating)
            tokens_earned += attempt_tokens

            # Reset streak on non-AC (consecutive AC count broken)
            session.streak_count = 0
            streak_count = 0

            # Check shield for failure -- no Elo deduction if shield is active
            elo_result = await TrainingService._calculate_training_elo(
                db,
                user,
                problem_rating,
                session_id,
                topic_id=session.topic_id,
                solved=False,
                attempts=attempts,
                problem_id=problem_id,
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
                        db,
                        user,
                        ac_tokens_only,
                        tx_type=token_type,
                        reference_type="training",
                        reference_id=session_id,
                    )
                await economy_svc.award_tokens(
                    db,
                    user,
                    streak_tokens,
                    tx_type="streak_bonus",
                    reference_type="training",
                    reference_id=session_id,
                )
            else:
                await economy_svc.award_tokens(
                    db,
                    user,
                    tokens_earned,
                    tx_type=token_type,
                    reference_type="training",
                    reference_id=session_id,
                )

            # Time bonus: if solved and time_spent > 20 min, award extra tokens
            if solved and time_spent > economy_svc.TIME_BONUS_THRESHOLD_SECONDS:
                time_bonus = economy_svc.time_bonus_for_rating(problem_rating)
                if time_bonus > 0:
                    await economy_svc.award_tokens(
                        db,
                        user,
                        time_bonus,
                        tx_type="time_bonus",
                        reference_type="training",
                        reference_id=session_id,
                    )
                    tokens_earned += time_bonus

        await db.flush()

        # --- Achievement event detection ---
        achievements: list[dict] = []

        if solved and problem_rating > 0:
            overkill_multiplier = PPService.calculate_overkill_multiplier(
                elo_before,
                problem_rating,
            )
            overkill_event = AchievementService.check_overkill(
                user_elo=elo_before,
                problem_rating=problem_rating,
                multiplier=overkill_multiplier,
            )
            if overkill_event is not None:
                achievements.append(overkill_event.to_dict())

            # Personal best PP detection
            if pp_change > 0:
                pp_event = AchievementService.check_personal_best_pp(
                    new_pp=user.pp,
                    old_pp=user.pp - pp_change,
                )
                if pp_event is not None:
                    achievements.append(pp_event.to_dict())

        return SubmitTrainingResponse(
            session_id=session_id,
            problem_id=problem_id,
            solved=solved,
            streak_count=streak_count,
            streak_tokens=streak_tokens,
            total_streak_tokens=total_streak_tokens,
            tokens_earned=tokens_earned,
            elo_change=elo_change,
            achievements=achievements,
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

        Applies quit-penalty Elo deduction following the rules:
        - Within protection period (300s from session start): No Elo change
        - Protection period expired AND 0 submissions: Deduct exactly 5 M-Elo
        - Protection period expired AND 1-2 submissions: small penalty (-5 to -10)
        - Protection period expired AND 3+ submissions: normal failure Elo calculation

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

        # Check protection period (300 seconds from session start)
        now = datetime.now(UTC)
        started_at = session.started_at
        if started_at is not None:
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            in_protection = (now - started_at).total_seconds() < 300
        else:
            # No started_at means the session just started -- treat as within protection
            in_protection = True

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

        if in_protection:
            # Within protection period: no Elo change regardless of submissions
            logger.info(
                "Protection period active for session=%s -- skipping Elo deduction on abandon",
                session_id,
            )
        elif submission_count == 0:
            # Protection period expired, 0 submissions: fixed 5 M-Elo deduction
            if primary_tag and not shield_active:
                await MEloService.get_or_create_melo(db, user.id, primary_tag)
                await MEloService.update_melo(db, user.id, primary_tag, -5)
                # Record EloHistory for the M-Elo deduction
                history = EloHistory(
                    user_id=user.id,
                    elo_before=user.elo,
                    elo_after=user.elo,
                    elo_change=0,
                    reason="training_abandon",
                    reference_id=session_id,
                )
                db.add(history)
                elo_change = -5
            elif shield_active:
                logger.info(
                    "Shield active for user=%s tag=%s -- skipping Elo deduction on abandon",
                    user.id,
                    primary_tag,
                )
        elif shield_active:
            # Shield active: no Elo deduction on abandon
            logger.info(
                "Shield active for user=%s tag=%s -- skipping Elo deduction on abandon",
                user.id,
                primary_tag,
            )
        else:
            # Apply quit penalty via _calculate_training_elo with solved=False
            # This uses the standard failure calculation with polarization coefficients
            elo_result = await TrainingService._calculate_training_elo(
                db,
                user,
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
    # 7b. Skip problem (switch problems during session)
    # ------------------------------------------------------------------

    @staticmethod
    async def skip_problem(
        db: AsyncSession,
        user: User,
        session_id: uuid.UUID,
        problem_id: str,
    ) -> SkipProblemResponse:
        """Skip a problem in an active training session.

        Rules:
        - Within protection period (300s from session start): No penalty
        - Protection period expired: Deduct 5 M-Elo from the topic's tag
        - Creates/updates a TrainingProblemRecord with solved=False
        - Records EloHistory for the M-Elo deduction
        """
        session = await db.get(TrainingSession, session_id)
        if session is None:
            raise NotFoundException(message="Training session not found")
        if session.user_id != user.id:
            raise ForbiddenException(message="Not your training session")
        if session.status != "active":
            raise BadRequestException(message="Training session is not active")

        # Check protection period
        now = datetime.now(UTC)
        started_at = session.started_at
        if started_at is not None:
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            in_protection = (now - started_at).total_seconds() < 300
        else:
            # No started_at means the session just started -- treat as within protection
            in_protection = True

        # Get problem rating
        problem_rating = await TrainingService._get_problem_rating(db, session.topic_id, problem_id, None)

        # Create or update problem record as skipped (solved=False)
        existing_stmt = select(TrainingProblemRecord).where(
            TrainingProblemRecord.session_id == session_id,
            TrainingProblemRecord.problem_id == problem_id,
        )
        existing_result = await db.execute(existing_stmt)
        existing_record = existing_result.scalar_one_or_none()

        if existing_record is not None:
            # Update existing record -- mark as not solved (skip)
            existing_record.solved = False
            existing_record.time_spent = existing_record.time_spent or 0.0
        else:
            record = TrainingProblemRecord(
                session_id=session_id,
                user_id=user.id,
                topic_id=session.topic_id,
                problem_id=problem_id,
                problem_rating=problem_rating,
                solved=False,
                attempts=0,
                time_spent=0.0,
                solved_at=None,
            )
            db.add(record)

        elo_change: int | None = None
        new_melo: int | None = None

        if not in_protection:
            # Deduct 5 M-Elo from the topic's primary tag
            primary_tag = await TrainingService._get_primary_tag_for_topic(db, session.topic_id)
            if primary_tag:
                # Check shield -- if active, skip deduction
                shield_active = await MEloService.is_shield_active(db, user.id, primary_tag)
                if shield_active:
                    logger.info(
                        "Shield active for user=%s tag=%s -- skipping M-Elo deduction on skip",
                        user.id,
                        primary_tag,
                    )
                else:
                    melo_record = await MEloService.get_or_create_melo(db, user.id, primary_tag)
                    await MEloService.update_melo(db, user.id, primary_tag, -5)
                    await db.flush()
                    await db.refresh(melo_record)
                    new_melo = melo_record.elo
                    elo_change = -5

                    # Record EloHistory for the deduction
                    history = EloHistory(
                        user_id=user.id,
                        elo_before=user.elo,
                        elo_after=user.elo,
                        elo_change=0,
                        reason="training_skip",
                        reference_id=session_id,
                    )
                    db.add(history)
        else:
            logger.info(
                "Protection period active for session=%s -- no penalty on skip",
                session_id,
            )

        await db.flush()

        # Get current melo after potential deduction
        if new_melo is None:
            primary_tag = await TrainingService._get_primary_tag_for_topic(db, session.topic_id)
            if primary_tag:
                melo_record = await MEloService.get_or_create_melo(db, user.id, primary_tag)
                new_melo = melo_record.elo

        return SkipProblemResponse(
            session_id=session_id,
            problem_id=problem_id,
            elo_change=elo_change,
            new_melo=new_melo,
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

        # Bulk-fetch all CF problems once (1 API call instead of N)
        all_problems = await TrainingService._get_all_problems_cached(cf_service)

        # Bulk-fetch all M-Elo records for this user (1 query instead of N)
        melo_records = await MEloService.get_all_melos(db, user_id)
        melo_map = {m.tag: m for m in melo_records}

        topic_progress_list: list[TopicProgress] = []
        total_solved = 0
        total_problems = 0

        for topic in topics:
            cf_tags = topic.cf_tags if isinstance(topic.cf_tags, list) else []
            primary_tag = cf_tags[0] if cf_tags else None

            # Filter pre-fetched problems by topic tags (in-memory)
            problems = TrainingService._filter_problems_by_tags(all_problems, cf_tags)
            topic_total = len(problems)

            # Get solved count
            solved_stmt = select(func.count(TrainingProblemRecord.id)).where(
                TrainingProblemRecord.user_id == user_id,
                TrainingProblemRecord.topic_id == topic.id,
                TrainingProblemRecord.solved.is_(True),
            )
            solved_result = await db.execute(solved_stmt)
            solved_count = solved_result.scalar_one()

            # Get total attempts and time
            agg_stmt = select(
                func.coalesce(func.sum(TrainingProblemRecord.attempts), 0),
                func.coalesce(func.sum(TrainingProblemRecord.time_spent), 0),
            ).where(
                TrainingProblemRecord.user_id == user_id,
                TrainingProblemRecord.topic_id == topic.id,
            )
            agg_result = await db.execute(agg_stmt)
            agg_row = agg_result.one()
            total_attempts = agg_row[0]
            total_time_spent = agg_row[1]

            completion_rate = (solved_count / topic_total * 100) if topic_total > 0 else 0.0

            # Look up M-Elo for the topic's primary tag
            melo: float | None = None
            shield_active = False
            if primary_tag:
                melo_rec = melo_map.get(primary_tag)
                if melo_rec is None:
                    melo = None
                    shield_active = True
                else:
                    melo = float(melo_rec.elo)
                    shield_active = melo_rec.first_ac_at is None

            topic_progress_list.append(
                TopicProgress(
                    topic_id=topic.id,
                    topic_name=topic.name,
                    slug=topic.slug,
                    total_problems=topic_total,
                    solved_count=solved_count,
                    completion_rate=round(completion_rate, 2),
                    stars=calculate_stars_from_melo(melo),
                    total_attempts=total_attempts,
                    total_time_spent=total_time_spent or 0.0,
                    melo=melo,
                    shield_active=shield_active,
                )
            )

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

        # Fetch all problems once, then filter by tags in-memory
        all_problems = await TrainingService._get_all_problems_cached(cf_service)
        problems = TrainingService._filter_problems_by_tags(all_problems, cf_tags)
        topic_total = len(problems)

        # Get solved count
        solved_stmt = select(func.count(TrainingProblemRecord.id)).where(
            TrainingProblemRecord.user_id == user_id,
            TrainingProblemRecord.topic_id == topic_id,
            TrainingProblemRecord.solved.is_(True),
        )
        solved_result = await db.execute(solved_stmt)
        solved_count = solved_result.scalar_one()

        # Get total attempts and time
        agg_stmt = select(
            func.coalesce(func.sum(TrainingProblemRecord.attempts), 0),
            func.coalesce(func.sum(TrainingProblemRecord.time_spent), 0),
        ).where(
            TrainingProblemRecord.user_id == user_id,
            TrainingProblemRecord.topic_id == topic_id,
        )
        agg_result = await db.execute(agg_stmt)
        agg_row = agg_result.one()
        total_attempts = agg_row[0]
        total_time_spent = agg_row[1]

        completion_rate = (solved_count / topic_total * 100) if topic_total > 0 else 0.0

        # Look up M-Elo for the topic's primary tag
        melo: float | None = None
        shield_active = False
        primary_tag = cf_tags[0] if cf_tags else None
        if primary_tag:
            melo_rec = await MEloService.get_or_create_melo(db, user_id, primary_tag)
            melo = float(melo_rec.elo)
            shield_active = melo_rec.first_ac_at is None

        return TopicProgress(
            topic_id=topic.id,
            topic_name=topic.name,
            slug=topic.slug,
            total_problems=topic_total,
            solved_count=solved_count,
            completion_rate=round(completion_rate, 2),
            stars=calculate_stars_from_melo(melo),
            total_attempts=total_attempts,
            total_time_spent=total_time_spent or 0.0,
            melo=melo,
            shield_active=shield_active,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # CF API optimisation: bulk fetch + in-memory filtering
    # ------------------------------------------------------------------

    # Module-level cache for the full problemset.  Shared across all
    # instances of TrainingService (which is stateless).  Keyed by a
    # fixed sentinel string so there is only ever one entry.
    _problems_cache: dict[str, tuple[float, list[dict]]] = {}
    _CACHE_TTL = 30 * 60  # 30 minutes

    @staticmethod
    async def _get_all_problems_cached(cf_service: CFApiService) -> list[dict]:
        """Fetch the *entire* CF problemset (no tag filter) and cache it.

        Returns a list of problem dicts.  The result is cached in-memory
        for ``_CACHE_TTL`` seconds so that repeated calls within the same
        process (e.g. ``list_topics`` + ``get_progress`` in quick
        succession) hit the cache instead of calling the CF API again.
        """
        cache_key = "__all__"
        entry = TrainingService._problems_cache.get(cache_key)
        if entry is not None:
            cached_at, problems = entry
            if time.monotonic() - cached_at < TrainingService._CACHE_TTL:
                return problems

        try:
            data = await cf_service.get_problemset_problems(tags=None)
            problems = data.get("problems", [])
        except Exception:
            logger.warning("CF API bulk fetch failed, returning cached or empty list")
            # Return stale cache if available, otherwise empty
            if entry is not None:
                return entry[1]
            return []

        TrainingService._problems_cache[cache_key] = (time.monotonic(), problems)
        return problems

    @staticmethod
    def _filter_problems_by_tags(
        all_problems: list[dict],
        cf_tags: list[str],
    ) -> list[dict]:
        """Filter a list of problem dicts to those matching **all** given tags.

        This is the in-memory equivalent of calling the CF API with a
        ``tags`` parameter.  A problem matches if every tag in *cf_tags*
        appears in the problem's ``tags`` list.
        """
        if not cf_tags:
            return all_problems
        result = []
        for p in all_problems:
            p_tags = p.get("tags", [])
            if all(tag in p_tags for tag in cf_tags):
                result.append(p)
        return result

    @staticmethod
    async def _fetch_topic_problems(
        cf_service: CFApiService,
        cf_tags: list[str],
    ) -> list[dict]:
        """Fetch problems for a topic from CF API.

        .. deprecated::
            Retained as a fallback.  The main code paths now use
            ``_get_all_problems_cached`` + ``_filter_problems_by_tags``
            instead, which reduces CF API calls from 12 to 1.

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
            select(TrainingProblemRecord.problem_rating).where(TrainingProblemRecord.problem_id == problem_id).limit(1)
        )
        result = await db.execute(stmt)
        existing_rating = result.scalar_one_or_none()
        if existing_rating is not None:
            return existing_rating

        # Try CF API via bulk-cached fetch
        if cf_service is not None:
            try:
                all_problems = await TrainingService._get_all_problems_cached(cf_service)
                for p in all_problems:
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
        problem_id: str | None = None,
        time_spent: float | None = None,
        cf_service: CFApiService | None = None,
    ) -> dict:
        """Calculate and apply Elo changes for a training problem result.

        Implements two features:
        - **Learning Shield (Task 16.2)**: If the shield is active for the
          topic's primary tag and the user failed/abandoned, no Elo changes
          are applied (neither Global nor M-Elo).
        - **Weight Polarization (Task 16.3)**: On AC, Global Elo changes are
          multiplied by ``training_global_coefficient`` (default 0.5) and
          M-Elo changes by ``training_melo_coefficient`` (default 2.0).
        - **Hint Attenuation (FR-5.3)**: Positive Elo gains are attenuated
          based on the highest hint level purchased for the problem.
        - **Time Factor (FR-16.4)**: Positive Elo gains are multiplied by
          the time factor when the user solved the problem.

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
                user.id,
                primary_tag,
            )
            return {
                "global_elo_change": None,
                "melo_change": None,
                "shield_active": True,
            }

        # --- Load configurable coefficients ---
        try:
            global_coeff = await config_svc.ConfigService.get_config(db, "melo.training_global_coefficient")
        except (KeyError, Exception):
            global_coeff = 0.5
        try:
            melo_coeff = await config_svc.ConfigService.get_config(db, "melo.training_melo_coefficient")
        except (KeyError, Exception):
            melo_coeff = 2.0

        # --- Configurable segmented K factor (same as other modes) ---
        elo_config = await config_svc.ConfigService.get_config(db, "elo")
        k_config = {
            "k_newbie": elo_config.get("k_newbie", 40),
            "k_veteran": elo_config.get("k_veteran", 20),
            "k_newbie_threshold": elo_config.get("k_newbie_threshold", 20),
            "k_veteran_threshold": elo_config.get("k_veteran_threshold", 100),
        }
        user_sub_count = await EloService.get_submission_count(db, user.id)
        k = EloService.calculate_k_factor(user_sub_count, k_config)

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
        global_elo_change = round(k * (s_value - global_expected) * global_coeff)

        # --- Hint attenuation on positive gains (FR-5.3) ---
        hint_attenuation: float | None = None
        if problem_id is not None:
            hint_level = await HintService.get_max_hint_level(db, user.id, problem_id)
            if hint_level > 0:
                hint_attenuation = EloService.apply_hint_attenuation(1.0, hint_level)
                if global_elo_change > 0:
                    global_elo_change = round(EloService.apply_hint_attenuation(float(global_elo_change), hint_level))

        # --- Time factor on positive gains (FR-16.4) ---
        time_factor: float | None = None
        if (
            solved
            and cf_service is not None
            and problem_id is not None
            and problem_rating > 0
            and time_spent is not None
        ):
            wa_count = max(0, attempts - 1)
            effective_time = TimeFactorService.compute_effective_time(time_spent, wa_count)
            expected_time = await TimeFactorService.calculate_expected_time(
                cf_service,
                problem_id,
                problem_rating,
                user.elo,
            )
            time_factor = TimeFactorService.calculate_time_factor(
                effective_time,
                expected_time,
                s_value,
            )
            if global_elo_change > 0:
                global_elo_change = round(global_elo_change * time_factor)

        # --- Apply Global Elo change ---
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
                time_factor=time_factor,
            )
            db.add(history)

        # --- M-Elo update for all problem tags (FR-9.1) ---
        topic = await db.get(TopicCategory, topic_id)
        problem_tags = topic.cf_tags if (topic and isinstance(topic.cf_tags, list)) else []
        melo_change: int | None = None
        if problem_tags:
            melo_result = await MEloService.batch_update_melo_for_problem(
                db=db,
                user_id=user.id,
                problem_tags=problem_tags,
                problem_rating=problem_rating,
                s_value=s_value,
                k_factor=k,
                time_factor=time_factor,
                hint_attenuation=hint_attenuation,
                coefficient=melo_coeff,
                solved=solved,
            )
            melo_change = sum(melo_result.values())

        return {
            "global_elo_change": global_elo_change,
            "melo_change": melo_change,
            "shield_active": shield_active,
        }
