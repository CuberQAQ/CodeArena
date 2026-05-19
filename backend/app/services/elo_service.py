import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.elo_history import EloHistory
from app.models.pp_record import PPRecord

# ---------------------------------------------------------------------------
# Enums & data classes
# ---------------------------------------------------------------------------


class EloReason(StrEnum):
    """Reasons for Elo changes recorded in elo_history."""

    CHALLENGE_WIN = "challenge_win"
    CHALLENGE_LOSS = "challenge_loss"
    CHALLENGE_DRAW = "challenge_draw"
    QUIT_PENALTY = "quit_penalty"
    CONTEST = "contest"


@dataclass(frozen=True)
class EloConfig:
    """Configuration parameters for Elo calculations.

    Fields have sensible defaults.  In a later task (Task 2.3) these will be
    loaded from the ``system_config`` table; until then the defaults are used.
    """

    k_factor: float = 32.0
    hint_attenuation: dict[int, float] = field(default_factory=lambda: {
        1: 0.75,
        2: 0.50,
        3: 0.25,
    })
    quit_penalty_min: int = -10
    quit_penalty_max: int = -5
    contest_time_bonus_factor: float = 0.1
    contest_time_bonus_cap: float = 0.2


# ---------------------------------------------------------------------------
# Default singleton – avoids re-creating the dataclass on every call
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = EloConfig()


# ---------------------------------------------------------------------------
# K-factor segment function defaults
# ---------------------------------------------------------------------------

_K_NEWBIE: float = 40.0
_K_VETERAN: float = 20.0
_K_NEWBIE_THRESHOLD: int = 20
_K_VETERAN_THRESHOLD: int = 100


# ---------------------------------------------------------------------------
# Core service
# ---------------------------------------------------------------------------


class EloService:
    """Stateless Elo rating calculation engine.

    Every public method is a pure-ish function that receives a database session
    so it can persist history records.  All calculation helpers are static
    methods to make testing straightforward.
    """

    # ------------------------------------------------------------------
    # S-value grading
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_s_value(
        is_solved: bool,
        is_first_ac: bool,
        error_count: int,
    ) -> float:
        """Calculate the S-value (performance outcome) for a submission.

        The S-value replaces the binary 0/1 actual_score with a continuous
        value that distinguishes "perfect AC" from "flawed AC".

        Formula
        -------
        - Solved with first-attempt AC (is_first_ac=True):  S = 1.0
        - Solved but with errors (is_first_ac=False):       S = max(0.7, 1.0 - 0.05 * N_errors)
        - Not solved:                                       S = 0.0

        Parameters
        ----------
        is_solved:
            Whether the problem was ultimately solved (AC).
        is_first_ac:
            True when the first submission was accepted (no prior errors).
        error_count:
            Number of non-AC submissions (WA, TLE, RE, MLE, etc.).  Only
            relevant when *is_solved* is True and *is_first_ac* is False.

        Returns
        -------
        float
            S-value in the range [0.0, 1.0].
        """
        if not is_solved:
            return 0.0
        if is_first_ac:
            return 1.0
        return max(0.7, 1.0 - 0.05 * error_count)

    # ------------------------------------------------------------------
    # K-factor segmented function
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_k_factor(
        submission_count: int,
        config: dict | None = None,
    ) -> float:
        """Return the K-factor based on the user's total submission count.

        The segmented formula:

        - If N_sub <= newbie_threshold:  K = k_newbie
        - If N_sub >= veteran_threshold: K = k_veteran
        - Otherwise (linear interpolation):
          K = k_newbie - (N_sub - newbie_threshold) * (k_newbie - k_veteran) / (veteran_threshold - newbie_threshold)

        Parameters
        ----------
        submission_count:
            The total number of submissions (approximated by PP records).
        config:
            Optional dict with keys ``k_newbie``, ``k_veteran``,
            ``k_newbie_threshold``, ``k_veteran_threshold``.  Falls back to
            module-level defaults when not provided.
        """
        k_newbie = _K_NEWBIE
        k_veteran = _K_VETERAN
        newbie_threshold = _K_NEWBIE_THRESHOLD
        veteran_threshold = _K_VETERAN_THRESHOLD

        if config is not None:
            k_newbie = float(config.get("k_newbie", k_newbie))
            k_veteran = float(config.get("k_veteran", k_veteran))
            newbie_threshold = int(config.get("k_newbie_threshold", newbie_threshold))
            veteran_threshold = int(config.get("k_veteran_threshold", veteran_threshold))

        if submission_count <= newbie_threshold:
            return k_newbie
        if submission_count >= veteran_threshold:
            return k_veteran

        # Linear interpolation between newbie and veteran thresholds
        ratio = (submission_count - newbie_threshold) / (veteran_threshold - newbie_threshold)
        return k_newbie - ratio * (k_newbie - k_veteran)

    @staticmethod
    async def get_submission_count(db: AsyncSession, user_id: uuid.UUID) -> int:
        """Return the total submission count for a user.

        Currently approximated by counting rows in the ``pp_records`` table,
        which represents successfully solved problems.  This gives a reasonable
        proxy for overall engagement that drives the K-factor segmentation.
        """
        stmt = select(func.count()).select_from(PPRecord).where(PPRecord.user_id == user_id)
        result = await db.scalar(stmt)
        return result or 0

    # ------------------------------------------------------------------
    # 1. Standard Elo (random challenge)
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_expected_score(rating_a: int, rating_b: int) -> float:
        """Return the expected score for player A against player B.

        ``E_A = 1 / (1 + 10^((R_B - R_A) / 400))``
        """
        return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))

    @staticmethod
    def calculate_new_rating(
        current_rating: int,
        expected_score: float,
        actual_score: float,
        k_factor: float | None = None,
    ) -> int:
        """Return the new rating after a single match, rounded to int.

        ``R_new = R_old + K * (S_actual - E_expected)``
        """
        if k_factor is None:
            k_factor = _DEFAULT_CONFIG.k_factor
        new_rating = current_rating + k_factor * (actual_score - expected_score)
        return round(new_rating)

    @staticmethod
    def calculate_challenge_elo(
        rating_a: int,
        rating_b: int,
        actual_score_a: float,
        k_factor: float | None = None,
        hint_level: int = 0,
        config: EloConfig | None = None,
    ) -> tuple[int, int, int]:
        """Calculate new Elo ratings for both players in a challenge.

        Parameters
        ----------
        rating_a, rating_b :
            Current ratings.
        actual_score_a :
            1 for win, 0 for loss, 0.5 for draw (from A's perspective).
        k_factor :
            Override K value; defaults to config.
        hint_level :
            Number of hints used by player A (0-3).  Hint attenuation is only
            applied to *positive* Elo changes for player A.
        config :
            Optional config override.

        Returns
        -------
        (new_rating_a, new_rating_b, elo_change_a)
        """
        if config is None:
            config = _DEFAULT_CONFIG
        if k_factor is None:
            k_factor = config.k_factor

        expected_a = EloService.calculate_expected_score(rating_a, rating_b)
        expected_b = 1.0 - expected_a
        actual_score_b = 1.0 - actual_score_a

        raw_change_a = k_factor * (actual_score_a - expected_a)

        # Apply hint attenuation only to positive gains
        if raw_change_a > 0 and hint_level > 0:
            attenuation = config.hint_attenuation.get(hint_level, 0.0)
            raw_change_a *= attenuation

        new_rating_a = round(rating_a + raw_change_a)
        new_rating_b = round(rating_b + k_factor * (actual_score_b - expected_b))
        elo_change_a = new_rating_a - rating_a

        return new_rating_a, new_rating_b, elo_change_a

    # ------------------------------------------------------------------
    # 2. Quit penalty
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_quit_penalty(
        submissions: int,
        config: EloConfig | None = None,
    ) -> int:
        """Return the Elo penalty for a player who quit.

        Rules
        -----
        - 0 submissions: no change (0).
        - 1-2 submissions: random penalty between ``quit_penalty_min`` and
          ``quit_penalty_max`` (both negative).
        - 3+ submissions: the caller should treat this as a normal loss via
          :meth:`calculate_challenge_elo`.  This method returns -1 as a sentinel
          so the caller knows to invoke the normal Elo calculation instead.

        Returns
        -------
        int
            The Elo change to apply.  ``-1`` is a sentinel meaning "use normal
            loss calculation" (3+ submissions case).
        """
        if config is None:
            config = _DEFAULT_CONFIG

        if submissions == 0:
            return 0
        if submissions <= 2:
            import random

            return random.randint(config.quit_penalty_min, config.quit_penalty_max)
        # 3+ submissions => normal loss
        return -1

    # ------------------------------------------------------------------
    # 3. Hint attenuation (already handled inside calculate_challenge_elo)
    # ------------------------------------------------------------------

    @staticmethod
    def apply_hint_attenuation(elo_change: float, hint_level: int, config: EloConfig | None = None) -> float:
        """Apply hint attenuation to an Elo change value.

        Only positive changes are attenuated.  Negative changes (losses) are
        returned unchanged.

        This is a public helper for callers who already have a pre-computed
        Elo change and need to attenuate it after the fact.
        """
        if config is None:
            config = _DEFAULT_CONFIG
        if elo_change <= 0 or hint_level <= 0:
            return elo_change
        attenuation = config.hint_attenuation.get(hint_level, 0.0)
        return elo_change * attenuation

    # ------------------------------------------------------------------
    # 4. M-Elo (contest Elo)
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_contest_score(
        solved_problems: int,
        total_problems: int,
        time_used_seconds: float,
        time_limit_seconds: float,
        config: EloConfig | None = None,
        s_values: list[float] | None = None,
    ) -> float:
        """Calculate a normalised contest score (0.0 - 1.0+).

        ``base_score = solved_problems / total_problems``

        When *s_values* is provided, it replaces the simple solved-count
        ratio.  Each element is an S-value for one solved problem; the base
        score becomes ``sum(s_values) / total_problems``.  This accounts
        for the quality of each solve (perfect AC vs flawed AC).

        A time bonus is added proportionally to how much time remains:
        ``time_bonus = factor * (1 - time_used / time_limit)``, capped at
        ``time_bonus_cap``.
        """
        if config is None:
            config = _DEFAULT_CONFIG
        if total_problems <= 0:
            return 0.0
        base_score = sum(s_values) / total_problems if s_values is not None else solved_problems / total_problems
        if time_limit_seconds <= 0:
            return base_score
        time_ratio = max(0.0, min(time_used_seconds / time_limit_seconds, 1.0))
        time_bonus = config.contest_time_bonus_factor * (1.0 - time_ratio)
        time_bonus = min(time_bonus, config.contest_time_bonus_cap)
        return base_score + time_bonus

    @staticmethod
    def calculate_contest_elo(
        current_rating: int,
        solved_problems: int,
        total_problems: int,
        time_used_seconds: float,
        time_limit_seconds: float,
        k_factor: float | None = None,
        config: EloConfig | None = None,
        s_values: list[float] | None = None,
    ) -> tuple[int, int]:
        """Calculate new Elo after a contest session.

        The contest score is compared against a fixed expected score of 0.5
        (i.e. the system expects an average performance).  This is the
        simplest reasonable model; it can be refined later.

        When *s_values* is provided, the base score is calculated from
        S-values rather than a simple solved-count ratio.

        Returns
        -------
        (new_rating, elo_change)
        """
        if config is None:
            config = _DEFAULT_CONFIG
        if k_factor is None:
            k_factor = config.k_factor

        contest_score = EloService.calculate_contest_score(
            solved_problems, total_problems, time_used_seconds, time_limit_seconds, config,
            s_values=s_values,
        )
        expected_score = 0.5
        new_rating = round(current_rating + k_factor * (contest_score - expected_score))
        elo_change = new_rating - current_rating
        return new_rating, elo_change

    # ------------------------------------------------------------------
    # 5. History persistence
    # ------------------------------------------------------------------

    @staticmethod
    async def record_elo_history(
        db: AsyncSession,
        user_id: uuid.UUID,
        elo_before: int,
        elo_after: int,
        reason: EloReason,
        reference_id: uuid.UUID | None = None,
    ) -> EloHistory:
        """Persist an Elo change to the ``elo_history`` table.

        This is a low-level helper called by the higher-level methods below.
        """
        record = EloHistory(
            user_id=user_id,
            elo_before=elo_before,
            elo_after=elo_after,
            elo_change=elo_after - elo_before,
            reason=reason.value,
            reference_id=reference_id,
        )
        db.add(record)
        await db.flush()
        return record

    # ------------------------------------------------------------------
    # High-level orchestration helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def process_challenge_result(
        db: AsyncSession,
        challenger_id: uuid.UUID,
        opponent_id: uuid.UUID,
        challenger_rating: int,
        opponent_rating: int,
        actual_score_a: float,
        session_id: uuid.UUID,
        hint_level_challenger: int = 0,
        hint_level_opponent: int = 0,
        config: EloConfig | None = None,
        challenger_submission_count: int | None = None,
        opponent_submission_count: int | None = None,
        k_factor_config: dict | None = None,
        s_value_challenger: float | None = None,
        s_value_opponent: float | None = None,
    ) -> tuple[int, int, int, int]:
        """Process a completed challenge and record Elo history for both players.

        Parameters
        ----------
        hint_level_challenger :
            Number of hints used by the challenger (0-3).  Hint attenuation is
            only applied to *positive* Elo changes for the challenger.
        hint_level_opponent :
            Number of hints used by the opponent (0-3).  Hint attenuation is
            only applied to *positive* Elo changes for the opponent.
        challenger_submission_count :
            Total historical submissions for the challenger.  When provided,
            the K-factor is calculated via ``calculate_k_factor`` instead of
            using the fixed default.
        opponent_submission_count :
            Same for the opponent.
        k_factor_config :
            Dict with K-factor configuration keys (``k_newbie``, etc.) passed
            through to ``calculate_k_factor``.  When ``None`` the module-level
            defaults are used.
        s_value_challenger, s_value_opponent :
            Optional S-values (performance outcomes) for each player.  When
            provided, they replace the binary ``actual_score_a`` in the Elo
            formula for each player independently.  The match outcome (who
            won) is still determined by ``actual_score_a``, but the Elo
            change magnitude is governed by the S-values.

        Returns
        -------
        (new_challenger_rating, new_opponent_rating, challenger_elo_change, opponent_elo_change)
        """
        if config is None:
            config = _DEFAULT_CONFIG

        # Determine K-factor for challenger
        k_challenger = config.k_factor
        if challenger_submission_count is not None:
            k_challenger = EloService.calculate_k_factor(challenger_submission_count, k_factor_config)

        # Determine K-factor for opponent
        k_opponent = config.k_factor
        if opponent_submission_count is not None:
            k_opponent = EloService.calculate_k_factor(opponent_submission_count, k_factor_config)

        expected_a = EloService.calculate_expected_score(challenger_rating, opponent_rating)
        expected_b = 1.0 - expected_a

        # When S-values are provided, use them as the actual scores for Elo calc.
        # Otherwise fall back to the binary actual_score_a (backward compatible).
        score_a = s_value_challenger if s_value_challenger is not None else actual_score_a
        score_b = s_value_opponent if s_value_opponent is not None else 1.0 - actual_score_a

        raw_change_a = k_challenger * (score_a - expected_a)
        raw_change_b = k_opponent * (score_b - expected_b)

        # Apply hint attenuation only to positive gains for challenger
        if raw_change_a > 0 and hint_level_challenger > 0:
            attenuation = config.hint_attenuation.get(hint_level_challenger, 0.0)
            raw_change_a *= attenuation

        # Apply hint attenuation only to positive gains for opponent
        if raw_change_b > 0 and hint_level_opponent > 0:
            attenuation = config.hint_attenuation.get(hint_level_opponent, 0.0)
            raw_change_b *= attenuation

        new_a = round(challenger_rating + raw_change_a)
        new_b = round(opponent_rating + raw_change_b)
        change_a = new_a - challenger_rating
        change_b = new_b - opponent_rating

        # Determine reason from the binary match outcome (actual_score_a)
        if actual_score_a == 1.0:
            reason_a = EloReason.CHALLENGE_WIN
        elif actual_score_a == 0.0:
            reason_a = EloReason.CHALLENGE_LOSS
        else:
            reason_a = EloReason.CHALLENGE_DRAW

        # Opponent reason is the mirror
        if actual_score_a == 1.0:
            reason_b = EloReason.CHALLENGE_LOSS
        elif actual_score_a == 0.0:
            reason_b = EloReason.CHALLENGE_WIN
        else:
            reason_b = EloReason.CHALLENGE_DRAW

        await EloService.record_elo_history(
            db, challenger_id, challenger_rating, new_a, reason_a, session_id
        )
        await EloService.record_elo_history(
            db, opponent_id, opponent_rating, new_b, reason_b, session_id
        )

        return new_a, new_b, change_a, change_b

    @staticmethod
    async def process_quit_penalty(
        db: AsyncSession,
        user_id: uuid.UUID,
        current_rating: int,
        submissions: int,
        session_id: uuid.UUID,
        opponent_id: uuid.UUID | None = None,
        opponent_rating: int | None = None,
        config: EloConfig | None = None,
        user_submission_count: int | None = None,
        opponent_submission_count: int | None = None,
        k_factor_config: dict | None = None,
    ) -> tuple[int, int]:
        """Process Elo changes when a player quits a challenge.

        For 3+ submissions the quit is treated as a normal loss against the
        opponent.  In that case ``opponent_id`` and ``opponent_rating`` must be
        provided.

        Parameters
        ----------
        user_submission_count :
            Total historical submissions for the quitting user.
        opponent_submission_count :
            Total historical submissions for the opponent.
        k_factor_config :
            Dict with K-factor configuration keys for segmented K calculation.

        Returns
        -------
        (new_rating, elo_change) for the quitting player.
        """
        if config is None:
            config = _DEFAULT_CONFIG

        penalty = EloService.calculate_quit_penalty(submissions, config)

        if penalty == -1:
            # 3+ submissions => normal loss
            if opponent_id is None or opponent_rating is None:
                raise ValueError(
                    "opponent_id and opponent_rating are required when submissions >= 3 (normal loss)"
                )

            # Calculate K-factors
            k_user = config.k_factor
            if user_submission_count is not None:
                k_user = EloService.calculate_k_factor(user_submission_count, k_factor_config)
            k_opponent = config.k_factor
            if opponent_submission_count is not None:
                k_opponent = EloService.calculate_k_factor(opponent_submission_count, k_factor_config)

            expected_a = EloService.calculate_expected_score(current_rating, opponent_rating)
            expected_b = 1.0 - expected_a
            raw_change_a = k_user * (0.0 - expected_a)
            new_a = round(current_rating + raw_change_a)
            raw_change_b = k_opponent * (1.0 - expected_b)
            new_b = round(opponent_rating + raw_change_b)
            change_a = new_a - current_rating

            await EloService.record_elo_history(
                db, user_id, current_rating, new_a, EloReason.QUIT_PENALTY, session_id
            )
            # Also record opponent's win
            await EloService.record_elo_history(
                db, opponent_id, opponent_rating, new_b, EloReason.CHALLENGE_WIN, session_id
            )
            return new_a, change_a

        if penalty == 0:
            return current_rating, 0

        new_rating = current_rating + penalty
        await EloService.record_elo_history(
            db, user_id, current_rating, new_rating, EloReason.QUIT_PENALTY, session_id
        )
        return new_rating, penalty

    @staticmethod
    async def process_contest_result(
        db: AsyncSession,
        user_id: uuid.UUID,
        current_rating: int,
        solved_problems: int,
        total_problems: int,
        time_used_seconds: float,
        time_limit_seconds: float,
        contest_session_id: uuid.UUID,
        k_factor: float | None = None,
        config: EloConfig | None = None,
        user_submission_count: int | None = None,
        k_factor_config: dict | None = None,
        s_values: list[float] | None = None,
    ) -> tuple[int, int]:
        """Process a completed contest session and record Elo history.

        Parameters
        ----------
        user_submission_count :
            Total historical submissions for the user.  When provided,
            the K-factor is calculated via ``calculate_k_factor`` instead of
            using the fixed default or explicit ``k_factor``.
        k_factor_config :
            Dict with K-factor configuration keys for segmented K calculation.
        s_values :
            Optional list of S-values (one per solved problem).  When
            provided, the contest score uses S-value weighting instead of a
            simple solved-count ratio.

        Returns
        -------
        (new_rating, elo_change)
        """
        if config is None:
            config = _DEFAULT_CONFIG

        # Determine effective K-factor
        effective_k = k_factor
        if effective_k is None:
            effective_k = config.k_factor
        if user_submission_count is not None:
            effective_k = EloService.calculate_k_factor(user_submission_count, k_factor_config)

        new_rating, elo_change = EloService.calculate_contest_elo(
            current_rating, solved_problems, total_problems,
            time_used_seconds, time_limit_seconds, effective_k, config,
            s_values=s_values,
        )
        await EloService.record_elo_history(
            db, user_id, current_rating, new_rating, EloReason.CONTEST, contest_session_id
        )
        return new_rating, elo_change

    # ------------------------------------------------------------------
    # 6. Utility – get latest Elo for a user from history
    # ------------------------------------------------------------------

    @staticmethod
    async def get_latest_elo(db: AsyncSession, user_id: uuid.UUID, fallback: int = 1200) -> int:
        """Return the most recent ``elo_after`` value for a user, or *fallback*."""
        stmt = (
            select(EloHistory.elo_after)
            .where(EloHistory.user_id == user_id)
            .order_by(EloHistory.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        return row if row is not None else fallback
