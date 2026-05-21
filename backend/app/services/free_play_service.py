"""Free Play (self-selected problems) business logic service.

Handles the full Free Play lifecycle:
- Searching problems by rating range and tags
- Adaptive recommendation based on M-Elo weakness
- Starting a session with a user-selected problem
- Submitting results and settlement (Elo, M-Elo, PP, tokens)
- Quitting a session
"""

import logging
import random
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.free_play_session import FreePlaySession
from app.models.pp_record import PPRecord
from app.models.user import User
from app.schemas.free_play import (
    AchievementEventSchema,
    FreePlayProblemInfo,
    FreePlayQuitResponse,
    FreePlayRecommendResponse,
    FreePlaySearchResponse,
    FreePlayStartResponse,
    FreePlaySubmitResponse,
)
from app.services import economy_service as economy_svc
from app.services.achievement_service import AchievementService
from app.services.cf_api_service import CFApiService
from app.services.config_service import ConfigService
from app.services.elo_service import EloReason, EloService
from app.services.hint_service import HintService
from app.services.melo_service import MEloService
from app.services.pp_service import PPService
from app.services.submission_tracker import SubmissionTracker
from app.services.time_factor_service import TimeFactorService

logger = logging.getLogger("code_arena.free_play")

# ---------------------------------------------------------------------------
# M-Elo recommendation weight calculation
# ---------------------------------------------------------------------------

_MELO_WEIGHT_OFFSET = 100  # offset added so weaker tags always have some weight
_MAX_RECOMMEND_ROUNDS = 3  # max rounds for recommendation fallback
_RECOMMEND_RATING_OFFSET_LOW = -100  # [M-Elo - 100, M-Elo + 200]
_RECOMMEND_RATING_OFFSET_HIGH = 200


# ---------------------------------------------------------------------------
# Free Play Service
# ---------------------------------------------------------------------------


class FreePlayService:
    """Orchestrates Free Play sessions.

    Stateless service class -- each method receives the resources it needs
    (db session, external services) as parameters.
    """

    # ------------------------------------------------------------------
    # 1. Search problems (manual filter by rating range + tags)
    # ------------------------------------------------------------------

    @staticmethod
    async def search_problems(
        db: AsyncSession,
        user: User,
        min_rating: int,
        max_rating: int,
        tags: list[str],
        cf_service: CFApiService,
    ) -> FreePlaySearchResponse:
        """Search for problems by rating range and optional tags.

        Fetches problems from CF API, filters by rating range and tags,
        excludes already-solved problems, and returns a random match.
        """
        # Get solved problem IDs
        solved_ids = await FreePlayService._get_solved_problem_ids(db, user.id)

        # Fetch problems from CF API
        try:
            data = await cf_service.get_problemset_problems(tags=tags if tags else None)
        except Exception:
            logger.warning("CF API unavailable for free play search")
            return FreePlaySearchResponse(
                problem=None,
                found=False,
                message="Codeforces API unavailable. Please try again later.",
            )

        problems = data.get("problems", [])
        if not problems:
            return FreePlaySearchResponse(
                problem=None,
                found=False,
                message="No problems found matching the given tags.",
            )

        # Filter by rating range and exclude solved
        candidates = []
        for p in problems:
            rating = p.get("rating")
            if rating is None:
                continue
            if not (min_rating <= rating <= max_rating):
                continue
            problem_id = f"{p.get('contestId', 0)}{p.get('index', '')}"
            if problem_id in solved_ids:
                continue
            candidates.append(p)

        if not candidates:
            return FreePlaySearchResponse(
                problem=None,
                found=False,
                message="No unsolved problems found in the specified rating range.",
            )

        # Return a random candidate
        chosen = random.choice(candidates)
        problem_info = FreePlayService._build_problem_info(chosen)

        return FreePlaySearchResponse(
            problem=problem_info,
            found=True,
            message="Problem found.",
        )

    # ------------------------------------------------------------------
    # 2. Adaptive recommendation
    # ------------------------------------------------------------------

    @staticmethod
    async def recommend_problem(
        db: AsyncSession,
        user: User,
        cf_service: CFApiService,
    ) -> FreePlayRecommendResponse:
        """Recommend a problem based on the user's weakest tags (M-Elo).

        Algorithm:
        1. Get all user M-Elo records
        2. Calculate weights: w(tag) = max_melo - melo(tag) + offset
        3. Weighted random select a tag
        4. In that tag's [M-Elo-100, M-Elo+200] range, find an unsolved problem
        5. Up to 3 rounds; fallback message if none found
        """
        # Get user M-Elo records
        melos = await MEloService.get_all_melos(db, user.id)

        if not melos:
            # No M-Elo data yet -- fall back to a simple range search
            return await FreePlayService._fallback_recommend(
                db,
                user,
                cf_service,
            )

        # Calculate weights
        max_melo = max(m.elo for m in melos)
        tag_weights: list[tuple[str, int, float]] = []  # (tag, melo, weight)
        for m in melos:
            weight = max(0.0, max_melo - m.elo + _MELO_WEIGHT_OFFSET)
            tag_weights.append((m.tag, m.elo, weight))

        # Get solved problems
        solved_ids = await FreePlayService._get_solved_problem_ids(db, user.id)

        # Fetch all problems from CF API once
        try:
            data = await cf_service.get_problemset_problems()
        except Exception:
            logger.warning("CF API unavailable for free play recommendation")
            return FreePlayRecommendResponse(
                problem=None,
                found=False,
                message="Codeforces API unavailable. Please try again later.",
            )

        all_problems = data.get("problems", [])
        if not all_problems:
            return FreePlayRecommendResponse(
                problem=None,
                found=False,
                message="No problems available from Codeforces.",
            )

        # Try up to 3 rounds
        for _ in range(_MAX_RECOMMEND_ROUNDS):
            # Weighted random tag selection
            total_weight = sum(w for _, _, w in tag_weights)
            if total_weight <= 0:
                break

            r = random.uniform(0, total_weight)
            cumulative = 0.0
            selected_tag = tag_weights[0][0]
            selected_melo = tag_weights[0][1]
            for tag, melo, weight in tag_weights:
                cumulative += weight
                if r <= cumulative:
                    selected_tag = tag
                    selected_melo = melo
                    break

            # Find unsolved problems in [M-Elo-100, M-Elo+200] with this tag
            min_r = int(selected_melo + _RECOMMEND_RATING_OFFSET_LOW)
            max_r = int(selected_melo + _RECOMMEND_RATING_OFFSET_HIGH)

            candidates = []
            for p in all_problems:
                rating = p.get("rating")
                if rating is None:
                    continue
                if not (min_r <= rating <= max_r):
                    continue
                tags = p.get("tags", [])
                if selected_tag not in tags:
                    continue
                problem_id = f"{p.get('contestId', 0)}{p.get('index', '')}"
                if problem_id in solved_ids:
                    continue
                candidates.append(p)

            if candidates:
                chosen = random.choice(candidates)
                problem_info = FreePlayService._build_problem_info(chosen)
                return FreePlayRecommendResponse(
                    problem=problem_info,
                    found=True,
                    message="Recommended problem found.",
                    recommended_tag=selected_tag,
                )

            # Remove this tag from further rounds and try again
            tag_weights = [(t, m, w) for t, m, w in tag_weights if t != selected_tag]
            if not tag_weights:
                break

        return FreePlayRecommendResponse(
            problem=None,
            found=False,
            message="No suitable problem found for recommendation. Try searching manually.",
        )

    # ------------------------------------------------------------------
    # 3. Start session
    # ------------------------------------------------------------------

    @staticmethod
    async def start_session(
        db: AsyncSession,
        user: User,
        problem_contest_id: int,
        problem_index: str,
        problem_rating: int,
        problem_tags: list[str],
        problem_name: str = "",
    ) -> FreePlayStartResponse:
        """Create a new Free Play session for a user-selected problem.

        Validates that the user does not already have an active session.
        """
        await FreePlayService._assert_no_active_session(db, user.id)

        problem_id = f"{problem_contest_id}{problem_index}"

        session = FreePlaySession(
            user_id=user.id,
            problem_id=problem_id,
            problem_contest_id=problem_contest_id,
            problem_index=problem_index,
            problem_rating=problem_rating,
            problem_tags=problem_tags,
            status="active",
        )
        db.add(session)
        await db.flush()

        # Register pending submission tracking
        await SubmissionTracker.register_pending(
            db=db,
            user_id=user.id,
            session_type="free_play",
            session_id=session.id,
            problem_id=problem_id,
            expected_at=datetime.now(UTC),
        )

        url = (
            f"https://codeforces.com/problemset/problem/{problem_contest_id}/{problem_index}"
            if problem_contest_id
            else ""
        )
        problem_info = FreePlayProblemInfo(
            contest_id=problem_contest_id,
            index=problem_index,
            name=problem_name or problem_id,
            rating=problem_rating,
            tags=problem_tags,
            url=url,
        )

        return FreePlayStartResponse(
            session_id=session.id,
            problem=problem_info,
            status="active",
        )

    # ------------------------------------------------------------------
    # 4. Submit result
    # ------------------------------------------------------------------

    @staticmethod
    async def submit_result(
        db: AsyncSession,
        user: User,
        session_id: uuid.UUID,
        solved: bool,
        time_spent: float,
        attempts: int,
        error_count: int = 0,
        cf_service: CFApiService | None = None,
    ) -> FreePlaySubmitResponse:
        """Submit the result of a Free Play session.

        Settlement mirrors PvE logic (S-value, Elo, PP, tokens, M-Elo)
        but uses normal coefficients (no training polarization) and no blind box.
        """
        session = await FreePlayService._get_session_or_raise(
            db,
            session_id,
            user.id,
            required_status="active",
        )

        # Calculate S-value
        is_first_ac = solved and attempts <= 1
        s_value = EloService.calculate_s_value(
            is_solved=solved,
            is_first_ac=is_first_ac,
            error_count=error_count if solved else 0,
        )

        # Elo calculation: player rating vs problem rating
        elo_config = await ConfigService.get_config(db, "elo")
        k_factor_config = {
            "k_newbie": elo_config.get("k_newbie", 40),
            "k_veteran": elo_config.get("k_veteran", 20),
            "k_newbie_threshold": elo_config.get("k_newbie_threshold", 20),
            "k_veteran_threshold": elo_config.get("k_veteran_threshold", 100),
        }
        user_sub_count = await EloService.get_submission_count(db, user.id)
        k_factor = EloService.calculate_k_factor(user_sub_count, k_factor_config)

        # Expected score: player vs problem
        expected_score = EloService.calculate_expected_score(user.elo, session.problem_rating)

        # Elo change: R_new = R_old + K * (S - E)
        elo_before = user.elo
        raw_elo_change = k_factor * (s_value - expected_score)

        # Apply hint attenuation to positive gains
        hint_level = await HintService.get_max_hint_level(db, user.id, session.problem_id)
        raw_elo_change = EloService.apply_hint_attenuation(raw_elo_change, hint_level)

        # Apply time factor: only when solved and cf_service available
        time_factor: float | None = None
        if cf_service is not None and solved:
            wa_count = max(0, error_count)
            effective_time = TimeFactorService.compute_effective_time(time_spent, wa_count)
            expected_time = await TimeFactorService.calculate_expected_time(
                cf_service,
                session.problem_id,
                session.problem_rating,
                user.elo,
            )
            time_factor = TimeFactorService.calculate_time_factor(
                effective_time,
                expected_time,
                s_value,
            )
            if raw_elo_change > 0 and time_factor is not None:
                raw_elo_change *= time_factor

        new_elo = round(elo_before + raw_elo_change)
        elo_change = new_elo - elo_before

        # PP calculation and recording (only on solve)
        pp_change = None
        overkill_multiplier = 1.0
        if solved and session.problem_rating > 0:
            wa_count = max(0, attempts - 1)
            time_minutes = time_spent / 60.0
            pp_before = user.pp
            await PPService.record_pp(
                db=db,
                user_id=user.id,
                cf_problem_id=session.problem_id,
                problem_rating=session.problem_rating,
                wa_count=wa_count,
                time_spent=time_minutes,
                user_elo=user.elo,
            )
            pp_change = round(user.pp - pp_before, 2)
            overkill_multiplier = PPService.calculate_overkill_multiplier(
                user.elo,
                session.problem_rating,
            )

        # Token rewards
        tokens_earned = 0
        if session.problem_rating > 0:
            if solved:
                # AC reward
                base_tokens = economy_svc.tokens_for_rating(session.problem_rating)
                tokens_earned = await economy_svc.award_tokens(
                    db,
                    user,
                    base_tokens,
                    tx_type="free_play_reward",
                    reference_type="free_play_session",
                    reference_id=session.id,
                )

                # Time bonus: solved in > 20 min
                if time_spent > economy_svc.TIME_BONUS_THRESHOLD_SECONDS:
                    time_bonus = economy_svc.time_bonus_for_rating(session.problem_rating)
                    if time_bonus > 0:
                        bonus = await economy_svc.award_tokens(
                            db,
                            user,
                            time_bonus,
                            tx_type="time_bonus",
                            reference_type="free_play_session",
                            reference_id=session.id,
                        )
                        tokens_earned += bonus
            else:
                # Attempt reward for non-AC submissions
                attempt_tokens = economy_svc.attempt_tokens_for_rating(session.problem_rating)
                if attempt_tokens > 0:
                    tokens_earned = await economy_svc.award_tokens(
                        db,
                        user,
                        attempt_tokens,
                        tx_type="free_play_attempt_reward",
                        reference_type="free_play_session",
                        reference_id=session.id,
                    )

        # Record Elo history
        reason = EloReason.CHALLENGE_WIN if solved else EloReason.CHALLENGE_LOSS
        await EloService.record_elo_history(
            db,
            user.id,
            user.elo,
            new_elo,
            reason,
            session.id,
            time_factor=time_factor,
        )

        # Update user Elo
        user.elo = new_elo

        # Update session
        session.status = "completed"
        session.error_count = error_count
        session.time_spent = time_spent
        session.elo_change = elo_change
        session.pp_change = pp_change
        session.s_value = s_value
        session.tokens_earned = tokens_earned
        session.completed_at = datetime.now(UTC)
        await db.flush()

        # M-Elo update (coefficient 1.0 -- no training polarization)
        problem_tags = session.problem_tags or []
        if problem_tags and session.problem_rating > 0:
            hint_attenuation = None
            if hint_level > 0:
                from app.services.elo_service import EloConfig

                _hint_cfg = EloConfig()
                hint_attenuation = _hint_cfg.hint_attenuation.get(hint_level)

            await MEloService.batch_update_melo_for_problem(
                db=db,
                user_id=user.id,
                problem_tags=problem_tags,
                problem_rating=session.problem_rating,
                s_value=s_value,
                k_factor=k_factor,
                time_factor=time_factor,
                hint_attenuation=hint_attenuation,
                coefficient=1.0,
                solved=solved,
            )

        logger.info(
            "Free play completed: session=%s solved=%s elo_change=%d tokens=%d s_value=%.2f",
            session.id,
            solved,
            elo_change,
            tokens_earned,
            s_value,
        )

        # Achievement event detection
        achievements: list[AchievementEventSchema] = []

        # Check overkill achievement
        overkill_event = AchievementService.check_overkill(
            user_elo=elo_before,
            problem_rating=session.problem_rating,
            multiplier=overkill_multiplier,
        )
        if overkill_event is not None:
            achievements.append(AchievementEventSchema(**overkill_event.to_dict()))

        # Check personal best PP
        if solved and pp_change is not None and pp_change > 0:
            pp_before_settlement = user.pp - pp_change
            pp_event = AchievementService.check_personal_best_pp(
                new_pp=user.pp,
                old_pp=pp_before_settlement,
            )
            if pp_event is not None:
                achievements.append(AchievementEventSchema(**pp_event.to_dict()))

        return FreePlaySubmitResponse(
            session_id=session.id,
            solved=solved,
            status="completed",
            elo_change=elo_change,
            pp_change=pp_change,
            s_value=s_value,
            tokens_earned=tokens_earned,
            overkill_multiplier=overkill_multiplier,
            achievements=achievements,
        )

    # ------------------------------------------------------------------
    # 5. Quit session
    # ------------------------------------------------------------------

    @staticmethod
    async def quit_session(
        db: AsyncSession,
        user: User,
        session_id: uuid.UUID,
    ) -> FreePlayQuitResponse:
        """Quit an active Free Play session with graduated penalty (FR-4.6).

        Penalty rules (applies to all modes):
          - 0 submissions: no Elo change
          - 1-2 submissions: Elo drops 5-10 (random)
          - 3+ submissions: normal failure (S=0, full Elo calculation)
        """
        session = await FreePlayService._get_session_or_raise(
            db,
            session_id,
            user.id,
            required_status="active",
        )

        # Determine submission count from tracking record
        tracking = await SubmissionTracker.get_tracking_for_session(
            db,
            user.id,
            "free_play",
            session_id,
        )
        # If tracking was matched/settled, user submitted at least once.
        # Use error_count as proxy for non-AC attempts; +1 if tracking was matched.
        submissions = max(1, session.error_count + 1) if tracking and tracking.status in ("matched", "settled") else 0

        current_elo = user.elo

        if submissions == 0:
            elo_change = 0
            new_elo = current_elo
        elif submissions <= 2:
            elo_change = random.randint(-10, -5)
            new_elo = current_elo + elo_change
        else:
            elo_config = await ConfigService.get_config(db, "elo")
            k_factor_config = {
                "k_newbie": elo_config.get("k_newbie", 40),
                "k_veteran": elo_config.get("k_veteran", 20),
                "k_newbie_threshold": elo_config.get("k_newbie_threshold", 20),
                "k_veteran_threshold": elo_config.get("k_veteran_threshold", 100),
            }
            user_sub_count = await EloService.get_submission_count(db, user.id)
            k_factor = EloService.calculate_k_factor(user_sub_count, k_factor_config)

            expected_score = EloService.calculate_expected_score(current_elo, session.problem_rating)
            s_value = 0.0
            new_elo = round(current_elo + k_factor * (s_value - expected_score))
            elo_change = new_elo - current_elo

        penalty = abs(elo_change)

        # Record Elo history
        await EloService.record_elo_history(
            db,
            user.id,
            current_elo,
            new_elo,
            EloReason.QUIT_PENALTY,
            session.id,
            time_factor=1.0,
        )

        # Update user Elo
        user.elo = new_elo

        session.status = "quit"
        session.elo_change = elo_change
        session.completed_at = datetime.now(UTC)
        await db.flush()

        logger.info(
            "Free play quit: session=%s submissions=%d elo_change=%d",
            session.id,
            submissions,
            elo_change,
        )

        return FreePlayQuitResponse(
            session_id=session.id,
            status="quit",
            elo_change=elo_change,
            new_elo=new_elo,
            penalty=penalty,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def get_active_session(db: AsyncSession, user: User) -> FreePlayStartResponse | None:
        """Return the user's active Free Play session with problem info, or None."""
        stmt = (
            select(FreePlaySession)
            .where(
                FreePlaySession.user_id == user.id,
                FreePlaySession.status == "active",
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        if session is None:
            return None

        problem = FreePlayProblemInfo(
            contest_id=session.problem_contest_id,
            index=session.problem_index,
            name="",
            rating=session.problem_rating,
            tags=session.problem_tags if session.problem_tags else [],
            url=f"https://codeforces.com/problemset/problem/{session.problem_contest_id}/{session.problem_index}",
        )
        return FreePlayStartResponse(
            session_id=session.id,
            problem=problem,
            status="active",
        )

    @staticmethod
    async def _assert_no_active_session(db: AsyncSession, user_id: uuid.UUID) -> None:
        """Raise BadRequestException if user has an active Free Play session."""
        stmt = (
            select(FreePlaySession)
            .where(
                FreePlaySession.user_id == user_id,
                FreePlaySession.status == "active",
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
            raise BadRequestException(message="You already have an active Free Play session")

    @staticmethod
    async def _get_solved_problem_ids(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
        """Return the set of CF problem IDs the user has already solved (from PP records)."""
        stmt = select(PPRecord.cf_problem_id).where(PPRecord.user_id == user_id)
        result = await db.execute(stmt)
        return {row[0] for row in result.all()}

    @staticmethod
    async def _get_session_or_raise(
        db: AsyncSession,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        required_status: str | None = None,
    ) -> FreePlaySession:
        """Fetch a Free Play session, validating ownership and optionally status."""
        session = await db.get(FreePlaySession, session_id)
        if session is None:
            raise NotFoundException(message="Free Play session not found")

        if session.user_id != user_id:
            raise ForbiddenException(message="Not the owner of this Free Play session")

        if required_status and session.status != required_status:
            raise BadRequestException(message=f"Free Play session is not {required_status} (current: {session.status})")

        return session

    @staticmethod
    def _build_problem_info(problem: dict) -> FreePlayProblemInfo:
        """Build a FreePlayProblemInfo from a CF API problem dict."""
        contest_id = problem.get("contestId", 0)
        index = problem.get("index", "")
        url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}" if contest_id else ""
        return FreePlayProblemInfo(
            contest_id=contest_id,
            index=index,
            name=problem.get("name", ""),
            rating=problem.get("rating"),
            tags=problem.get("tags", []),
            url=url,
        )

    @staticmethod
    async def _fallback_recommend(
        db: AsyncSession,
        user: User,
        cf_service: CFApiService,
    ) -> FreePlayRecommendResponse:
        """Fallback recommendation when no M-Elo data exists.

        Uses the user's global Elo range [elo-100, elo+200].
        """
        solved_ids = await FreePlayService._get_solved_problem_ids(db, user.id)

        try:
            data = await cf_service.get_problemset_problems()
        except Exception:
            return FreePlayRecommendResponse(
                problem=None,
                found=False,
                message="Codeforces API unavailable. Please try again later.",
            )

        problems = data.get("problems", [])
        min_r = user.elo - 100
        max_r = user.elo + 200

        candidates = []
        for p in problems:
            rating = p.get("rating")
            if rating is None:
                continue
            if not (min_r <= rating <= max_r):
                continue
            problem_id = f"{p.get('contestId', 0)}{p.get('index', '')}"
            if problem_id in solved_ids:
                continue
            candidates.append(p)

        if not candidates:
            return FreePlayRecommendResponse(
                problem=None,
                found=False,
                message="No suitable problem found. Try searching manually.",
            )

        chosen = random.choice(candidates)
        problem_info = FreePlayService._build_problem_info(chosen)
        return FreePlayRecommendResponse(
            problem=problem_info,
            found=True,
            message="Recommended problem found.",
            recommended_tag=None,
        )
