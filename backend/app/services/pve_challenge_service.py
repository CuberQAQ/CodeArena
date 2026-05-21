"""PvE (Player vs Environment) challenge business logic service.

Handles the full PvE challenge lifecycle:
- Starting a random challenge (problem selection with fallback ranges)
- Submitting results and settlement (S-value, Elo, PP, tokens)
- Quitting with tiered penalty
- Session detail and history queries
"""

import logging
import random
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.pp_record import PPRecord
from app.models.pve_challenge_session import PvEChallengeSession
from app.models.user import User
from app.schemas.pve_challenge import (
    AchievementEventSchema,
    PvEDetailResponse,
    PvEHistoryItem,
    PvEHistoryResponse,
    PvEProblemInfo,
    PvEStartResponse,
    PvESubmitResultResponse,
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

logger = logging.getLogger("code_arena.pve_challenge")


# ---------------------------------------------------------------------------
# Problem selection ranges (Elo-based with 3-round fallback)
# ---------------------------------------------------------------------------

_SELECTION_RANGES: list[tuple[int, int]] = [
    (-100, 200),  # Round 1: [Elo-100, Elo+200]
    (-200, 300),  # Round 2: [Elo-200, Elo+300]
    (-300, 400),  # Round 3: [Elo-300, Elo+400]
]


# ---------------------------------------------------------------------------
# PvE Challenge Service
# ---------------------------------------------------------------------------


class PvEChallengeService:
    """Orchestrates PvE challenge sessions.

    Stateless service class -- each method receives the resources it needs
    (db session, external services) as parameters.
    """

    # ------------------------------------------------------------------
    # 1. Start challenge (random problem selection)
    # ------------------------------------------------------------------

    @staticmethod
    async def start_challenge(
        db: AsyncSession,
        user: User,
        cf_service: CFApiService,
    ) -> PvEStartResponse:
        """Create a new PvE challenge session with a random problem.

        Validates that the user does not already have an active session,
        selects a random unsolved problem in the user's Elo range, and
        creates the session.

        Raises:
            BadRequestException: if user already has an active PvE session.
            NotFoundException: if no suitable problem can be found.
        """
        # Check for existing active session
        await PvEChallengeService._assert_no_active_session(db, user.id)

        # Get solved problem IDs (from PP records) to filter
        solved_ids = await PvEChallengeService._get_solved_problem_ids(db, user.id)

        # Select random problem with 3-round fallback
        problem = await PvEChallengeService._select_random_problem(
            user_elo=user.elo,
            cf_service=cf_service,
            solved_ids=solved_ids,
        )

        if problem is None:
            raise NotFoundException(message="No suitable problem found. Please try again later.")

        # Create session
        contest_id = problem.get("contestId", 0)
        index = problem.get("index", "")
        problem_id = f"{contest_id}{index}"
        problem_rating = problem.get("rating", 0)
        problem_tags = problem.get("tags", [])

        session = PvEChallengeSession(
            user_id=user.id,
            problem_id=problem_id,
            problem_rating=problem_rating,
            problem_tags=problem_tags,
            status="active",
        )
        db.add(session)
        await db.flush()

        # Register pending submission tracking so the CF API poller can
        # automatically detect when the user submits on Codeforces.
        await SubmissionTracker.register_pending(
            db=db,
            user_id=user.id,
            session_type="pve",
            session_id=session.id,
            problem_id=problem_id,
            expected_at=datetime.now(UTC),
        )

        problem_info = PvEChallengeService._build_problem_info(problem)
        return PvEStartResponse(
            session_id=session.id,
            problem=problem_info,
            status="active",
        )

    # ------------------------------------------------------------------
    # 2. Submit result
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
    ) -> PvESubmitResultResponse:
        """Submit the result of a PvE challenge.

        If solved:
          - Calculates S-value, Elo change (vs problem rating), PP, tokens.
        If not solved:
          - Treats as a failed attempt with S=0, applies Elo loss.
        """
        session = await PvEChallengeService._get_session_or_raise(
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

        # Apply time factor (FR-16.4): only when solved and cf_service available
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
                    tx_type="pve_challenge_reward",
                    reference_type="pve_challenge_session",
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
                            reference_type="pve_challenge_session",
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
                        tx_type="pve_attempt_reward",
                        reference_type="pve_challenge_session",
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
        session.completed_at = datetime.now(UTC)
        await db.flush()

        # --- M-Elo update (FR-9.1) ---
        problem_tags = session.problem_tags or []
        if problem_tags and session.problem_rating > 0:
            # Get hint attenuation for M-Elo
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
            "PvE challenge completed: session=%s solved=%s elo_change=%d tokens=%d s_value=%.2f",
            session.id,
            solved,
            elo_change,
            tokens_earned,
            s_value,
        )

        # --- Achievement event detection ---
        achievements: list[AchievementEventSchema] = []

        # Check overkill achievement
        overkill_event = AchievementService.check_overkill(
            user_elo=elo_before,
            problem_rating=session.problem_rating,
            multiplier=overkill_multiplier,
        )
        if overkill_event is not None:
            achievements.append(AchievementEventSchema(**overkill_event.to_dict()))

        # Check personal best PP (only on solve with PP gain)
        if solved and pp_change is not None and pp_change > 0:
            pp_before_settlement = user.pp - pp_change
            pp_event = AchievementService.check_personal_best_pp(
                new_pp=user.pp,
                old_pp=pp_before_settlement,
            )
            if pp_event is not None:
                achievements.append(AchievementEventSchema(**pp_event.to_dict()))

        return PvESubmitResultResponse(
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
    # 3. Quit challenge
    # ------------------------------------------------------------------

    @staticmethod
    async def quit_challenge(
        db: AsyncSession,
        user: User,
        session_id: uuid.UUID,
        submissions: int,
    ) -> dict:
        """Quit an active PvE challenge. Applies tiered Elo penalty.

        Penalty rules:
          - 0 submissions: no Elo change
          - 1-2 submissions: Elo drops 5-10 (random)
          - 3+ submissions: normal failure (S=0, full Elo calculation)
        """
        session = await PvEChallengeService._get_session_or_raise(
            db,
            session_id,
            user.id,
            required_status="active",
        )

        current_elo = user.elo

        if submissions == 0:
            # No penalty
            elo_change = 0
            new_elo = current_elo
        elif submissions <= 2:
            # Mild penalty: -5 to -10
            elo_change = random.randint(-10, -5)
            new_elo = current_elo + elo_change
        else:
            # 3+ submissions: treat as normal failure (S=0)
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
            s_value = 0.0  # Failure
            new_elo = round(current_elo + k_factor * (s_value - expected_score))
            elo_change = new_elo - current_elo

        # Record Elo history (quit: time_factor=1.0 since no solve)
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

        # Update session
        session.status = "quit"
        session.error_count = submissions
        session.elo_change = elo_change
        session.s_value = 0.0 if submissions >= 3 else None
        session.completed_at = datetime.now(UTC)
        await db.flush()

        # Update M-Elo for 3+ submissions (normal failure path)
        if submissions >= 3 and session.problem_tags:
            from app.services.melo_service import MEloService

            problem_tags_list = session.problem_tags if isinstance(session.problem_tags, list) else []
            await MEloService.batch_update_melo_for_problem(
                db=db,
                user_id=user.id,
                problem_tags=problem_tags_list,
                problem_rating=session.problem_rating,
                s_value=0.0,
                k_factor=k_factor,
                time_factor=1.0,
                hint_attenuation=1.0,
                coefficient=1.0,
                solved=False,
            )

        logger.info(
            "PvE challenge quit: session=%s submissions=%d elo_change=%d",
            session.id,
            submissions,
            elo_change,
        )

        return {
            "session_id": str(session.id),
            "status": "quit",
            "elo_change": elo_change,
            "new_elo": new_elo,
            "penalty": abs(elo_change) if elo_change < 0 else 0,
        }

    # ------------------------------------------------------------------
    # 4. Get challenge detail
    # ------------------------------------------------------------------

    @staticmethod
    async def get_challenge(
        db: AsyncSession,
        user: User,
        session_id: uuid.UUID,
    ) -> PvEDetailResponse:
        """Return detailed information about a PvE challenge session."""
        session = await PvEChallengeService._get_session_or_raise(
            db,
            session_id,
            user.id,
        )

        problem_info = PvEChallengeService._build_problem_info_from_session(session)

        return PvEDetailResponse(
            id=session.id,
            user_id=session.user_id,
            problem_id=session.problem_id,
            problem_rating=session.problem_rating,
            problem_tags=session.problem_tags or [],
            problem=problem_info,
            status=session.status,
            error_count=session.error_count,
            time_spent=session.time_spent,
            hints_used=session.hints_used,
            elo_change=session.elo_change,
            pp_change=session.pp_change,
            s_value=session.s_value,
            created_at=session.created_at,
            completed_at=session.completed_at,
        )

    # ------------------------------------------------------------------
    # 5. History (paginated)
    # ------------------------------------------------------------------

    @staticmethod
    async def get_history(
        db: AsyncSession,
        user: User,
        page: int = 1,
        page_size: int = 20,
    ) -> PvEHistoryResponse:
        """Return paginated PvE challenge history for the user."""
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size

        # Total count
        count_stmt = select(func.count(PvEChallengeSession.id)).where(PvEChallengeSession.user_id == user.id)
        total = (await db.execute(count_stmt)).scalar_one()

        # Items
        stmt = (
            select(PvEChallengeSession)
            .where(PvEChallengeSession.user_id == user.id)
            .order_by(PvEChallengeSession.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await db.execute(stmt)
        sessions = list(result.scalars().all())

        items = [
            PvEHistoryItem(
                id=s.id,
                problem_id=s.problem_id,
                problem_rating=s.problem_rating,
                problem_tags=s.problem_tags or [],
                status=s.status,
                error_count=s.error_count,
                time_spent=s.time_spent,
                hints_used=s.hints_used,
                elo_change=s.elo_change,
                pp_change=s.pp_change,
                s_value=s.s_value,
                created_at=s.created_at,
                completed_at=s.completed_at,
            )
            for s in sessions
        ]

        return PvEHistoryResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _assert_no_active_session(db: AsyncSession, user_id: uuid.UUID) -> None:
        """Raise BadRequestException if user has an active PvE session."""
        stmt = (
            select(PvEChallengeSession)
            .where(
                PvEChallengeSession.user_id == user_id,
                PvEChallengeSession.status == "active",
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
            raise BadRequestException(message="You already have an active PvE challenge session")

    @staticmethod
    async def _get_solved_problem_ids(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
        """Return the set of CF problem IDs the user has already solved (from PP records)."""
        stmt = select(PPRecord.cf_problem_id).where(PPRecord.user_id == user_id)
        result = await db.execute(stmt)
        return {row[0] for row in result.all()}

    @staticmethod
    async def _select_random_problem(
        user_elo: int,
        cf_service: CFApiService,
        solved_ids: set[str],
    ) -> dict | None:
        """Select a random unsolved problem within the user's Elo range.

        Tries up to 3 rounds with progressively wider ranges:
          Round 1: [Elo-100, Elo+200]
          Round 2: [Elo-200, Elo+300]
          Round 3: [Elo-300, Elo+400]

        Returns None if no suitable problem is found.
        """
        try:
            data = await cf_service.get_problemset_problems()
        except Exception:
            logger.warning("CF API unavailable for PvE problem selection")
            return None

        problems = data.get("problems", [])
        if not problems:
            return None

        for elo_offset, elo_plus in _SELECTION_RANGES:
            min_rating = user_elo + elo_offset
            max_rating = user_elo + elo_plus

            candidates = []
            for p in problems:
                rating = p.get("rating")
                if rating is None:
                    continue
                problem_id = f"{p.get('contestId', 0)}{p.get('index', '')}"
                if problem_id in solved_ids:
                    continue
                if min_rating <= rating <= max_rating:
                    candidates.append(p)

            if candidates:
                return random.choice(candidates)

        return None

    @staticmethod
    async def _get_session_or_raise(
        db: AsyncSession,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        required_status: str | None = None,
    ) -> PvEChallengeSession:
        """Fetch a PvE session, validating ownership and optionally status.

        Raises:
            NotFoundException: session not found
            ForbiddenException: user is not the session owner
            BadRequestException: session status does not match required
        """
        session = await db.get(PvEChallengeSession, session_id)
        if session is None:
            raise NotFoundException(message="PvE challenge session not found")

        if session.user_id != user_id:
            raise ForbiddenException(message="Not the owner of this PvE challenge session")

        if required_status and session.status != required_status:
            raise BadRequestException(
                message=f"PvE challenge session is not {required_status} (current: {session.status})"
            )

        return session

    @staticmethod
    def _build_problem_info(problem: dict) -> PvEProblemInfo:
        """Build a PvEProblemInfo from a CF API problem dict."""
        contest_id = problem.get("contestId", 0)
        index = problem.get("index", "")
        url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}" if contest_id else ""
        return PvEProblemInfo(
            contest_id=contest_id,
            index=index,
            name=problem.get("name", ""),
            rating=problem.get("rating"),
            tags=problem.get("tags", []),
            url=url,
        )

    @staticmethod
    def _build_problem_info_from_session(session: PvEChallengeSession) -> PvEProblemInfo:
        """Build a PvEProblemInfo from a stored session's problem_id and rating."""
        problem_id = session.problem_id
        contest_id = 0
        index = ""
        for i in range(len(problem_id)):
            if problem_id[i].isalpha():
                contest_id = int(problem_id[:i]) if i > 0 else 0
                index = problem_id[i:]
                break
        if not index:
            contest_id = 0
            index = problem_id

        url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}" if contest_id else ""
        return PvEProblemInfo(
            contest_id=contest_id,
            index=index,
            name=problem_id,
            rating=session.problem_rating,
            tags=session.problem_tags or [],
            url=url,
        )
