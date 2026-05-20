"""Challenge business logic service.

Handles the full challenge lifecycle:
- Creating challenge sessions from match results
- Problem selection based on average Elo
- Start confirmation (problem reveal)
- Result submission and settlement
- Quit with penalty handling
"""

import logging
import random
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.challenge_session import ChallengeSession
from app.models.user import User
from app.schemas.challenge import (
    ChallengeDetail,
    OpponentInfo,
    ProblemInfo,
    StartChallengeResponse,
    SubmitResultResponse,
)
from app.services import economy_service as economy_svc
from app.services.achievement_service import AchievementService
from app.services.cf_api_service import CFApiService
from app.services.config_service import ConfigService
from app.services.elo_service import EloService
from app.services.match_service import MatchService
from app.services.pp_service import PPService

logger = logging.getLogger("code_arena.challenge")

# ---------------------------------------------------------------------------
# Token reward tiers by problem rating
# ---------------------------------------------------------------------------

_TOKEN_TIERS: list[tuple[int, int]] = [
    (1100, 10),   # 灰 (800-1099)
    (1400, 20),   # 绿 (1100-1399)
    (1700, 30),   # 蓝 (1400-1699)
    (2000, 40),   # 紫 (1700-1999)
    (9999, 50),   # 黄/红 (2000+)
]


def _tokens_for_rating(rating: int) -> int:
    """Return the token reward for solving a problem at the given rating."""
    for threshold, reward in _TOKEN_TIERS:
        if rating < threshold:
            return reward
    return 50


# ---------------------------------------------------------------------------
# Problem difficulty offset config
# ---------------------------------------------------------------------------

_DEFAULT_RATING_OFFSET_RANGE = 200  # +/- 200 from average elo


# ---------------------------------------------------------------------------
# Pending match store (in-memory)
# ---------------------------------------------------------------------------

# Tracks matches that have been found but not yet both-confirmed.
# Key: session_id, Value: dict with player confirmations
_pending_matches: dict[uuid.UUID, dict] = {}


def _get_pending(session_id: uuid.UUID) -> dict | None:
    return _pending_matches.get(session_id)


def _set_pending(session_id: uuid.UUID, data: dict) -> None:
    _pending_matches[session_id] = data


def _remove_pending(session_id: uuid.UUID) -> None:
    _pending_matches.pop(session_id, None)


# ---------------------------------------------------------------------------
# Challenge Service
# ---------------------------------------------------------------------------


class ChallengeService:
    """Orchestrates challenge sessions.

    This is a stateless service class -- each method receives the resources
    it needs (db session, external services) as parameters.
    """

    # ------------------------------------------------------------------
    # 1. Join queue and match
    # ------------------------------------------------------------------

    @staticmethod
    async def join_queue(
        db: AsyncSession,
        user: User,
        match_service: MatchService,
    ) -> dict:
        """Add the user to the match queue and attempt immediate matching.

        Returns a dict with ``matched`` (bool) and optional session/opponent info.
        """
        added = await match_service.join_queue(user.id, user.elo, user.username, user.cf_handle)
        if not added:
            raise BadRequestException(message="Already in match queue")

        # Immediately try to find a match
        match_result = await match_service.try_match(user.id)

        if match_result is None:
            return {"matched": False, "message": "Waiting for opponent"}

        # Determine which player is which
        if match_result.player_a.user_id == user.id:
            me_entry = match_result.player_a
            opp_entry = match_result.player_b
        else:
            me_entry = match_result.player_b
            opp_entry = match_result.player_a

        # Fetch opponent User from DB for full data
        opp_user = await db.get(User, opp_entry.user_id)
        if opp_user is None:
            # Opponent disappeared -- put self back in queue
            await match_service.join_queue(user.id, user.elo, user.username, user.cf_handle)
            raise NotFoundException(message="Matched opponent not found")

        # Create the challenge session in DB
        session = ChallengeSession(
            id=match_result.session_id,
            challenger_id=me_entry.user_id,
            opponent_id=opp_entry.user_id,
            problem_id="",  # filled after both confirm start
            problem_rating=0,
            status="pending",
        )
        db.add(session)
        await db.flush()

        # Store pending match info (problem not yet selected)
        _set_pending(match_result.session_id, {
            "player_a_id": match_result.player_a.user_id,
            "player_b_id": match_result.player_b.user_id,
            "avg_elo": match_result.avg_elo,
            "confirmed": set(),
        })

        opponent_info = OpponentInfo(
            id=opp_user.id,
            username=opp_user.username,
            elo=opp_user.elo,
            cf_handle=opp_user.cf_handle,
        )

        return {
            "matched": True,
            "session_id": str(session.id),
            "opponent": opponent_info.model_dump(mode="json"),
        }

    # ------------------------------------------------------------------
    # 2. Leave queue
    # ------------------------------------------------------------------

    @staticmethod
    async def leave_queue(
        user: User,
        match_service: MatchService,
    ) -> bool:
        """Remove the user from the match queue. Returns True if removed."""
        return await match_service.leave_queue(user.id)

    # ------------------------------------------------------------------
    # 3. Query status
    # ------------------------------------------------------------------

    @staticmethod
    async def get_queue_status(
        db: AsyncSession,
        user: User,
        match_service: MatchService,
    ) -> dict:
        """Return the current queue/match status for the user."""
        # Check if in queue
        in_queue = await match_service.is_in_queue(user.id)

        # Check for a pending match involving this user
        for session_id, pending in _pending_matches.items():
            if user.id in (pending["player_a_id"], pending["player_b_id"]):
                opponent_id = pending["player_b_id"] if user.id == pending["player_a_id"] else pending["player_a_id"]
                opp_user = await db.get(User, opponent_id)
                opponent_info = None
                if opp_user:
                    opponent_info = OpponentInfo(
                        id=opp_user.id,
                        username=opp_user.username,
                        elo=opp_user.elo,
                        cf_handle=opp_user.cf_handle,
                    )
                confirmed = pending["confirmed"]
                both_ready = len(confirmed) == 2
                return {
                    "in_queue": False,
                    "matched": True,
                    "session_id": str(session_id),
                    "opponent": opponent_info.model_dump(mode="json") if opponent_info else None,
                    "both_ready": both_ready,
                }

        # Check for active challenge sessions
        stmt = (
            select(ChallengeSession)
            .where(
                (ChallengeSession.challenger_id == user.id) | (ChallengeSession.opponent_id == user.id),
                ChallengeSession.status.in_(["active", "pending"]),
            )
            .order_by(ChallengeSession.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()

        if session is not None and session.status == "active":
            # Active challenge -- return info
            opponent_id = session.opponent_id if session.challenger_id == user.id else session.challenger_id
            opp_user = await db.get(User, opponent_id)
            opponent_info = None
            if opp_user:
                opponent_info = OpponentInfo(
                    id=opp_user.id,
                    username=opp_user.username,
                    elo=opp_user.elo,
                    cf_handle=opp_user.cf_handle,
                )
            return {
                "in_queue": False,
                "matched": True,
                "session_id": str(session.id),
                "opponent": opponent_info.model_dump(mode="json") if opponent_info else None,
                "both_ready": True,
            }

        return {
            "in_queue": in_queue,
            "matched": False,
            "session_id": None,
            "opponent": None,
            "both_ready": False,
        }

    # ------------------------------------------------------------------
    # 4. Confirm start (problem reveal)
    # ------------------------------------------------------------------

    @staticmethod
    async def start_challenge(
        db: AsyncSession,
        user: User,
        session_id: uuid.UUID,
        cf_service: CFApiService,
        rating_offset: int = _DEFAULT_RATING_OFFSET_RANGE,
    ) -> StartChallengeResponse:
        """Confirm start and reveal the challenge problem.

        When both players have confirmed, the problem is selected and revealed.
        The first player to confirm gets a "waiting" response.
        """
        session = await db.get(ChallengeSession, session_id)
        if session is None:
            raise NotFoundException(message="Challenge session not found")

        if user.id not in (session.challenger_id, session.opponent_id):
            raise ForbiddenException(message="Not a participant in this challenge")

        if session.status not in ("pending", "active"):
            raise BadRequestException(message="Challenge is not in a startable state")

        pending = _get_pending(session_id)

        # If session already active (problem already selected), return problem
        if session.status == "active" and session.problem_id:
            problem = _build_problem_info(session.problem_id, session.problem_rating)
            return StartChallengeResponse(
                session_id=session.id,
                problem=problem,
                status="problem_revealed",
            )

        # Mark this player as confirmed
        if pending is not None:
            pending["confirmed"].add(user.id)

            if len(pending["confirmed"]) < 2:
                return StartChallengeResponse(
                    session_id=session.id,
                    problem=ProblemInfo(
                        contest_id=0,
                        index="",
                        name="Waiting for opponent to confirm...",
                        rating=0,
                        tags=[],
                        url="",
                    ),
                    status="waiting_opponent",
                )

            # Both confirmed -- select problem
            avg_elo = pending["avg_elo"]
        else:
            # No pending record -- treat as direct start (shouldn't normally happen)
            challenger = await db.get(User, session.challenger_id)
            opponent = await db.get(User, session.opponent_id)
            if challenger is None or opponent is None:
                raise NotFoundException(message="Player not found")
            avg_elo = (challenger.elo + opponent.elo) / 2.0

        # Select problem from CF
        problem = await _select_problem(cf_service, avg_elo, rating_offset)

        # Update session
        session.problem_id = problem["id"]
        session.problem_rating = problem.get("rating", 0)
        session.status = "active"
        await db.flush()

        # Clean up pending state
        _remove_pending(session_id)

        problem_info = _build_problem_info(session.problem_id, session.problem_rating)
        return StartChallengeResponse(
            session_id=session.id,
            problem=problem_info,
            status="problem_revealed",
        )

    # ------------------------------------------------------------------
    # 5. Submit result
    # ------------------------------------------------------------------

    @staticmethod
    async def submit_result(
        db: AsyncSession,
        user: User,
        session_id: uuid.UUID,
        solved: bool,
        time_spent: float,
        attempts: int,
    ) -> SubmitResultResponse:
        """Submit a player's challenge result.

        If both players have submitted, the challenge is settled immediately.
        """
        session = await db.get(ChallengeSession, session_id)
        if session is None:
            raise NotFoundException(message="Challenge session not found")

        if user.id not in (session.challenger_id, session.opponent_id):
            raise ForbiddenException(message="Not a participant in this challenge")

        if session.status != "active":
            raise BadRequestException(message="Challenge is not active")

        is_challenger = user.id == session.challenger_id

        if is_challenger:
            if session.challenger_solved or session.challenger_time is not None:
                raise BadRequestException(message="Already submitted result")
            session.challenger_solved = solved
            session.challenger_time = time_spent
            session.challenger_submissions = attempts
        else:
            if session.opponent_solved or session.opponent_time is not None:
                raise BadRequestException(message="Already submitted result")
            session.opponent_solved = solved
            session.opponent_time = time_spent
            session.opponent_submissions = attempts

        await db.flush()

        # Check if both submitted
        both_submitted = (
            session.challenger_time is not None
            and session.opponent_time is not None
        )

        if both_submitted:
            return await _settle_challenge(db, session)

        return SubmitResultResponse(
            session_id=session.id,
            solved=solved,
            status="result_submitted",
            settled=False,
        )

    # ------------------------------------------------------------------
    # 6. Get challenge detail
    # ------------------------------------------------------------------

    @staticmethod
    async def get_challenge_detail(
        db: AsyncSession,
        user: User,
        session_id: uuid.UUID,
    ) -> ChallengeDetail:
        """Return detailed information about a challenge session."""
        session = await db.get(ChallengeSession, session_id)
        if session is None:
            raise NotFoundException(message="Challenge session not found")

        if user.id not in (session.challenger_id, session.opponent_id):
            raise ForbiddenException(message="Not a participant in this challenge")

        problem_info = None
        if session.problem_id:
            problem_info = _build_problem_info(session.problem_id, session.problem_rating)

        return ChallengeDetail(
            id=session.id,
            challenger_id=session.challenger_id,
            opponent_id=session.opponent_id,
            problem_id=session.problem_id,
            problem_rating=session.problem_rating,
            problem=problem_info,
            challenger_solved=session.challenger_solved,
            opponent_solved=session.opponent_solved,
            challenger_submissions=session.challenger_submissions,
            opponent_submissions=session.opponent_submissions,
            challenger_time=session.challenger_time,
            opponent_time=session.opponent_time,
            status=session.status,
            result=session.result,
            elo_change=session.elo_change,
            created_at=session.created_at,
            completed_at=session.completed_at,
        )

    # ------------------------------------------------------------------
    # 7. Quit challenge
    # ------------------------------------------------------------------

    @staticmethod
    async def quit_challenge(
        db: AsyncSession,
        user: User,
        session_id: uuid.UUID,
        submissions: int,
    ) -> dict:
        """Quit an active challenge. Applies Elo penalty based on submissions."""
        session = await db.get(ChallengeSession, session_id)
        if session is None:
            raise NotFoundException(message="Challenge session not found")

        if user.id not in (session.challenger_id, session.opponent_id):
            raise ForbiddenException(message="Not a participant in this challenge")

        if session.status not in ("pending", "active"):
            raise BadRequestException(message="Challenge is not active")

        is_challenger = user.id == session.challenger_id
        opponent_id = session.opponent_id if is_challenger else session.challenger_id

        # Update submissions count for quitter
        if is_challenger:
            session.challenger_submissions = submissions
        else:
            session.opponent_submissions = submissions

        current_elo = user.elo
        opponent = await db.get(User, opponent_id)
        opponent_elo = opponent.elo if opponent else 1200

        # Load K-factor config for segmented calculation
        elo_config = await ConfigService.get_config(db, "elo")
        k_factor_config = {
            "k_newbie": elo_config.get("k_newbie", 40),
            "k_veteran": elo_config.get("k_veteran", 20),
            "k_newbie_threshold": elo_config.get("k_newbie_threshold", 20),
            "k_veteran_threshold": elo_config.get("k_veteran_threshold", 100),
        }
        user_sub_count = await EloService.get_submission_count(db, user.id)
        opp_sub_count = await EloService.get_submission_count(db, opponent_id) if opponent else None

        # Process quit penalty via EloService
        new_rating, elo_change = await EloService.process_quit_penalty(
            db=db,
            user_id=user.id,
            current_rating=current_elo,
            submissions=submissions,
            session_id=session.id,
            opponent_id=opponent_id,
            opponent_rating=opponent_elo,
            user_submission_count=user_sub_count,
            opponent_submission_count=opp_sub_count,
            k_factor_config=k_factor_config,
        )

        # Update user's Elo
        user.elo = new_rating

        # If opponent hasn't submitted and session is active, mark it
        if session.status == "active" and opponent and submissions >= 3:
            # Treated as normal loss -- opponent gets win via EloService
            pass

        # Mark session as completed
        session.status = "completed"
        session.result = "challenger_quit" if is_challenger else "opponent_quit"
        session.elo_change = elo_change
        session.completed_at = datetime.now(UTC)

        # Update opponent Elo if needed (for 3+ submissions case, opponent
        # already got Elo update via process_quit_penalty)
        if opponent and submissions >= 3:
            # Opponent Elo was already updated in process_quit_penalty
            # Refresh from DB
            await db.refresh(opponent)

        await db.flush()

        _remove_pending(session_id)

        return {
            "session_id": str(session.id),
            "status": "quit",
            "elo_change": elo_change,
            "new_elo": new_rating,
            "penalty": abs(elo_change) if elo_change and elo_change < 0 else 0,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _select_problem(
    cf_service: CFApiService,
    avg_elo: float,
    rating_offset: int = _DEFAULT_RATING_OFFSET_RANGE,
) -> dict:
    """Select a suitable problem from CF based on average Elo.

    Returns a dict with keys: id, contest_id, index, name, rating, tags.
    """
    target_rating = int(avg_elo + random.randint(-rating_offset, rating_offset))
    target_rating = max(800, min(3500, target_rating))  # clamp to valid CF range

    try:
        data = await cf_service.get_problemset_problems()
    except Exception:
        logger.warning("CF API unavailable, using fallback problem")
        return {
            "id": "1A",
            "contest_id": 1,
            "index": "A",
            "name": "Theatre Square",
            "rating": 800,
            "tags": [],
        }

    problems = data.get("problems", [])
    if not problems:
        return {
            "id": "1A",
            "contest_id": 1,
            "index": "A",
            "name": "Theatre Square",
            "rating": 800,
            "tags": [],
        }

    # Filter problems with ratings close to target
    candidates = []
    for p in problems:
        rating = p.get("rating")
        if rating is not None and abs(rating - target_rating) <= 200:
            candidates.append(p)

    if not candidates:
        # Relax: pick any rated problem
        for p in problems:
            if p.get("rating") is not None:
                candidates.append(p)

    if not candidates:
        return {
            "id": "1A",
            "contest_id": 1,
            "index": "A",
            "name": "Theatre Square",
            "rating": 800,
            "tags": [],
        }

    # Pick random from candidates, preferring closer to target
    candidates.sort(key=lambda p: abs(p.get("rating", 9999) - target_rating))
    # Pick from top 5 candidates randomly
    top = candidates[:5]
    chosen = random.choice(top)

    contest_id = chosen.get("contestId", 0)
    index = chosen.get("index", "")
    return {
        "id": f"{contest_id}{index}",
        "contest_id": contest_id,
        "index": index,
        "name": chosen.get("name", ""),
        "rating": chosen.get("rating", 0),
        "tags": chosen.get("tags", []),
    }


def _build_problem_info(problem_id: str, problem_rating: int) -> ProblemInfo:
    """Build a ProblemInfo from stored problem_id and rating.

    The problem_id is stored as "contestIdindex" (e.g., "1234A").
    We parse it back to extract contest_id and index.
    """
    # Try to split numeric prefix from alpha suffix
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

    return ProblemInfo(
        contest_id=contest_id,
        index=index,
        name=problem_id,
        rating=problem_rating,
        url=url,
    )


async def _settle_challenge(
    db: AsyncSession,
    session: ChallengeSession,
) -> SubmitResultResponse:
    """Settle a challenge after both players have submitted.

    Determines the winner, calculates Elo/PP/tokens, and updates records.
    """
    challenger = await db.get(User, session.challenger_id)
    opponent = await db.get(User, session.opponent_id)

    if challenger is None or opponent is None:
        raise NotFoundException(message="Player not found during settlement")

    # Determine actual score from challenger's perspective
    if session.challenger_solved and not session.opponent_solved:
        actual_score_a = 1.0
        result = "challenger_win"
    elif not session.challenger_solved and session.opponent_solved:
        actual_score_a = 0.0
        result = "opponent_win"
    elif session.challenger_solved and session.opponent_solved:
        # Both solved -- faster time wins
        if (session.challenger_time or float("inf")) < (session.opponent_time or float("inf")):
            actual_score_a = 1.0
            result = "challenger_win"
        elif (session.challenger_time or float("inf")) > (session.opponent_time or float("inf")):
            actual_score_a = 0.0
            result = "opponent_win"
        else:
            actual_score_a = 0.5
            result = "draw"
    else:
        # Neither solved
        actual_score_a = 0.5
        result = "draw"

    # Process Elo with K-factor segmentation and S-value grading
    elo_config = await ConfigService.get_config(db, "elo")
    k_factor_config = {
        "k_newbie": elo_config.get("k_newbie", 40),
        "k_veteran": elo_config.get("k_veteran", 20),
        "k_newbie_threshold": elo_config.get("k_newbie_threshold", 20),
        "k_veteran_threshold": elo_config.get("k_veteran_threshold", 100),
    }
    challenger_sub_count = await EloService.get_submission_count(db, challenger.id)
    opponent_sub_count = await EloService.get_submission_count(db, opponent.id)

    # Calculate S-values for each player independently
    # S-value distinguishes "perfect AC" (first attempt) from "flawed AC" (with errors)
    s_value_challenger = EloService.calculate_s_value(
        is_solved=bool(session.challenger_solved),
        is_first_ac=bool(session.challenger_solved) and (session.challenger_submissions or 0) <= 1,
        error_count=max(0, (session.challenger_submissions or 0) - 1) if session.challenger_solved else 0,
    )
    s_value_opponent = EloService.calculate_s_value(
        is_solved=bool(session.opponent_solved),
        is_first_ac=bool(session.opponent_solved) and (session.opponent_submissions or 0) <= 1,
        error_count=max(0, (session.opponent_submissions or 0) - 1) if session.opponent_solved else 0,
    )

    new_challenger_elo, new_opponent_elo, challenger_elo_change, _opponent_elo_change = (
        await EloService.process_challenge_result(
            db=db,
            challenger_id=challenger.id,
            opponent_id=opponent.id,
            challenger_rating=challenger.elo,
            opponent_rating=opponent.elo,
            actual_score_a=actual_score_a,
            session_id=session.id,
            hint_level_challenger=session.hints_used_challenger or 0,
            hint_level_opponent=session.hints_used_opponent or 0,
            challenger_submission_count=challenger_sub_count,
            opponent_submission_count=opponent_sub_count,
            k_factor_config=k_factor_config,
            s_value_challenger=s_value_challenger,
            s_value_opponent=s_value_opponent,
        )
    )

    # Save pre-settlement Elo for PP overkill calculation
    challenger_elo_original = challenger.elo
    opponent_elo_original = opponent.elo

    # Update user Elo
    challenger.elo = new_challenger_elo
    opponent.elo = new_opponent_elo

    # Calculate tokens for the winner (or both for draw)
    tokens_challenger = 0
    tokens_opponent = 0
    if session.problem_rating > 0:
        base_tokens = _tokens_for_rating(session.problem_rating)
        if actual_score_a == 1.0:
            tokens_challenger = base_tokens
        elif actual_score_a == 0.0:
            tokens_opponent = base_tokens
        else:
            tokens_challenger = base_tokens // 2
            tokens_opponent = base_tokens // 2

    # Award tokens via economy_service (enforces daily cap, updates daily_tokens_earned)
    if tokens_challenger > 0:
        await economy_svc.award_tokens(
            db, challenger, tokens_challenger,
            tx_type="challenge_reward",
            reference_type="challenge_session",
            reference_id=session.id,
        )

    if tokens_opponent > 0:
        await economy_svc.award_tokens(
            db, opponent, tokens_opponent,
            tx_type="challenge_reward",
            reference_type="challenge_session",
            reference_id=session.id,
        )

    # Time bonus: if solved and time_spent > 20 min, award extra tokens
    challenger_time_bonus = (
        session.challenger_solved
        and session.challenger_time is not None
        and session.challenger_time > economy_svc.TIME_BONUS_THRESHOLD_SECONDS
        and session.problem_rating > 0
    )
    if challenger_time_bonus:
        time_bonus = economy_svc.time_bonus_for_rating(session.problem_rating)
        if time_bonus > 0:
            await economy_svc.award_tokens(
                db, challenger, time_bonus,
                tx_type="time_bonus",
                reference_type="challenge_session",
                reference_id=session.id,
            )
            tokens_challenger += time_bonus

    opponent_time_bonus = (
        session.opponent_solved
        and session.opponent_time is not None
        and session.opponent_time > economy_svc.TIME_BONUS_THRESHOLD_SECONDS
        and session.problem_rating > 0
    )
    if opponent_time_bonus:
        time_bonus = economy_svc.time_bonus_for_rating(session.problem_rating)
        if time_bonus > 0:
            await economy_svc.award_tokens(
                db, opponent, time_bonus,
                tx_type="time_bonus",
                reference_type="challenge_session",
                reference_id=session.id,
            )
            tokens_opponent += time_bonus

    # Attempt reward: players who submitted but did not AC still get attempt tokens
    if session.problem_rating > 0:
        if not session.challenger_solved and (session.challenger_submissions or 0) > 0:
            attempt_tokens = economy_svc.attempt_tokens_for_rating(session.problem_rating)
            if attempt_tokens > 0:
                awarded = await economy_svc.award_tokens(
                    db, challenger, attempt_tokens,
                    tx_type="reward_attempt",
                    reference_type="challenge_session",
                    reference_id=session.id,
                )
                tokens_challenger += awarded

        if not session.opponent_solved and (session.opponent_submissions or 0) > 0:
            attempt_tokens = economy_svc.attempt_tokens_for_rating(session.problem_rating)
            if attempt_tokens > 0:
                awarded = await economy_svc.award_tokens(
                    db, opponent, attempt_tokens,
                    tx_type="reward_attempt",
                    reference_type="challenge_session",
                    reference_id=session.id,
                )
                tokens_opponent += awarded

    # Record PP for solvers
    if session.challenger_solved and session.problem_rating > 0:
        challenger_wa = max(0, (session.challenger_submissions or 0) - 1)
        challenger_time_min = (session.challenger_time or 0.0) / 60.0
        await PPService.record_pp(
            db=db,
            user_id=challenger.id,
            cf_problem_id=session.problem_id,
            problem_rating=session.problem_rating,
            wa_count=challenger_wa,
            time_spent=challenger_time_min,
            user_elo=challenger_elo_original,
        )

    if session.opponent_solved and session.problem_rating > 0:
        opponent_wa = max(0, (session.opponent_submissions or 0) - 1)
        opponent_time_min = (session.opponent_time or 0.0) / 60.0
        await PPService.record_pp(
            db=db,
            user_id=opponent.id,
            cf_problem_id=session.problem_id,
            problem_rating=session.problem_rating,
            wa_count=opponent_wa,
            time_spent=opponent_time_min,
            user_elo=opponent_elo_original,
        )

    # Update session
    session.status = "completed"
    session.result = result
    session.elo_change = challenger_elo_change
    session.completed_at = datetime.now(UTC)
    await db.flush()

    logger.info(
        "Challenge settled: session=%s result=%s elo_change=%d tokens_challenger=%d tokens_opponent=%d",
        session.id,
        result,
        challenger_elo_change,
        tokens_challenger,
        tokens_opponent,
    )

    # --- Achievement event detection ---
    achievements: list[dict] = []

    # Check overkill for challenger (if they solved)
    if session.challenger_solved and session.problem_rating > 0:
        # Use pre-settlement Elo for overkill detection (fair comparison with problem rating)
        challenger_elo_before = new_challenger_elo - challenger_elo_change
        challenger_overkill = PPService.calculate_overkill_multiplier(
            challenger_elo_before, session.problem_rating,
        )
        overkill_event = AchievementService.check_overkill(
            user_elo=challenger_elo_before,
            problem_rating=session.problem_rating,
            multiplier=challenger_overkill,
        )
        if overkill_event is not None:
            achievements.append(overkill_event.to_dict())

    # Determine the submitting user's perspective
    return SubmitResultResponse(
        session_id=session.id,
        solved=session.challenger_solved or session.opponent_solved,
        status="settled",
        settled=True,
        result=result,
        elo_change=challenger_elo_change,
        tokens_earned=tokens_challenger,
        achievements=achievements,
    )
