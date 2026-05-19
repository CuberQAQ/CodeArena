"""PP (Performance Points) calculation engine.

Provides single-problem base PP calculation, performance factor computation,
total PP aggregation with decay, PP record management, and ranking queries.
"""

import math
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pp_record import PPRecord
from app.models.user import User

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PPConfig:
    """Configuration parameters for PP calculations.

    Fields have sensible defaults.  In a later task (Task 2.3) these will be
    loaded from the ``system_config`` table; until then the defaults are used.
    """

    base_formula_coefficient: float = 10.0
    base_formula_offset: int = 800
    decay_factor: float = 0.95
    max_problems: int = 100
    performance_factor_wa_penalty: float = 0.03
    performance_factor_time_penalty: float = 0.01
    performance_factor_time_min: float = 0.6


_DEFAULT_CONFIG = PPConfig()


# ---------------------------------------------------------------------------
# Core service
# ---------------------------------------------------------------------------


class PPService:
    """Stateless PP calculation engine.

    Every public method is a pure-ish function that receives a database session
    so it can persist / query PP records.  Pure calculation helpers are static
    methods to make testing straightforward.
    """

    # ------------------------------------------------------------------
    # 1. Base PP (single problem)
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_base_pp(
        problem_rating: int,
        config: PPConfig | None = None,
    ) -> float:
        """Return the base PP awarded for solving a problem at *problem_rating*.

        Formula::

            if rating < offset: 0
            else: sqrt((rating - offset) / 100) * coefficient

        Parameters
        ----------
        problem_rating :
            The difficulty rating of the problem.
        config :
            Optional config override.

        Returns
        -------
        float
            Base PP value.
        """
        if config is None:
            config = _DEFAULT_CONFIG
        if problem_rating < config.base_formula_offset:
            return 0.0
        return math.sqrt((problem_rating - config.base_formula_offset) / 100.0) * config.base_formula_coefficient

    # ------------------------------------------------------------------
    # 2. Performance factor
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_performance_factor(
        wa_count: int,
        time_spent_minutes: float,
        config: PPConfig | None = None,
    ) -> float:
        """Return the performance factor f(wa, t) for a solve attempt.

        Formula::

            f(wa, t) = (1 - wa_penalty * wa_count)
                       * max(time_min, 1 - time_penalty * t_minutes)

        Parameters
        ----------
        wa_count :
            Number of wrong answers (WA/TLE/RE/MLE) before AC.
        time_spent_minutes :
            Time from first attempt to AC, in minutes.
        config :
            Optional config override.

        Returns
        -------
        float
            Performance factor in [time_min, 1.0].
        """
        if config is None:
            config = _DEFAULT_CONFIG

        wa_factor = 1.0 - config.performance_factor_wa_penalty * wa_count
        time_factor = max(
            config.performance_factor_time_min,
            1.0 - config.performance_factor_time_penalty * time_spent_minutes,
        )

        # The wa_factor can go below time_min for extreme wa counts, which is
        # intentional -- time_min only protects the time component.
        return wa_factor * time_factor

    # ------------------------------------------------------------------
    # 3. Total PP aggregation
    # ------------------------------------------------------------------

    @staticmethod
    def aggregate_total_pp(
        base_pp_values: list[float],
        config: PPConfig | None = None,
    ) -> float:
        """Compute the total PP from an ordered list of PP values.

        The list should already be sorted **descending**.  Only the first
        ``max_problems`` entries are considered.  Each entry is multiplied by
        ``decay_factor^(i-1)`` where *i* is the 1-based index.

        Result is rounded to 2 decimal places.

        Parameters
        ----------
        base_pp_values :
            PP values sorted in descending order.
        config :
            Optional config override.

        Returns
        -------
        float
            Aggregated total PP, rounded to 2 decimal places.
        """
        if config is None:
            config = _DEFAULT_CONFIG

        capped = base_pp_values[: config.max_problems]
        total = 0.0
        for i, pp in enumerate(capped):
            total += pp * (config.decay_factor ** i)
        return round(total, 2)

    # ------------------------------------------------------------------
    # 4. PP record management
    # ------------------------------------------------------------------

    @staticmethod
    async def record_pp(
        db: AsyncSession,
        user_id: uuid.UUID,
        cf_problem_id: str,
        problem_rating: int,
        hints_used: int = 0,
        wa_count: int = 0,
        time_spent: float = 0.0,
        config: PPConfig | None = None,
    ) -> PPRecord:
        """Create or update a PP record for a user solving a problem.

        - If no record exists for (user_id, cf_problem_id), create one.
        - If a record exists and the new ``problem_rating`` is **higher**,
          update the record (base_pp and problem_rating).
        - ``hints_used`` is always incremented on the existing record so that
          total hint usage is tracked, but hints do **not** affect PP value.

        After the record is created/updated the user's total PP is
        recalculated and written to ``users.pp``.

        Parameters
        ----------
        db :
            Async database session.
        user_id :
            The user who solved the problem.
        cf_problem_id :
            Codeforces problem identifier (e.g. "1234A").
        problem_rating :
            Difficulty rating of the problem.
        hints_used :
            Number of hints used in this solve attempt.
        wa_count :
            Number of wrong answers (WA/TLE/RE/MLE) in this attempt.
        time_spent :
            Time from first attempt to AC, in minutes.
        config :
            Optional config override.

        Returns
        -------
        PPRecord
            The created or updated PP record.
        """
        if config is None:
            config = _DEFAULT_CONFIG

        base_pp = PPService.calculate_base_pp(problem_rating, config)
        performance_factor = PPService.calculate_performance_factor(wa_count, time_spent, config)
        final_pp = base_pp * performance_factor

        # Check for existing record
        stmt = select(PPRecord).where(
            PPRecord.user_id == user_id,
            PPRecord.cf_problem_id == cf_problem_id,
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        now = datetime.now()

        if existing is None:
            record = PPRecord(
                user_id=user_id,
                cf_problem_id=cf_problem_id,
                problem_rating=problem_rating,
                base_pp=base_pp,
                solved_at=now,
                hints_used=hints_used,
                wa_count=wa_count,
                time_spent_minutes=time_spent,
                performance_factor=performance_factor,
                final_pp=final_pp,
            )
            db.add(record)
            await db.flush()
        else:
            # Always accumulate hint usage
            existing.hints_used = existing.hints_used + hints_used

            # Only update PP if the new rating is higher
            if problem_rating > existing.problem_rating:
                existing.problem_rating = problem_rating
                existing.base_pp = base_pp
                existing.solved_at = now
                existing.wa_count = wa_count
                existing.time_spent_minutes = time_spent
                existing.performance_factor = performance_factor
                existing.final_pp = final_pp

            await db.flush()
            record = existing

        # Recalculate total PP for the user
        await PPService.refresh_user_pp(db, user_id, config)

        return record

    # ------------------------------------------------------------------
    # 5. Total PP calculation for a user (DB query)
    # ------------------------------------------------------------------

    @staticmethod
    async def calculate_user_total_pp(
        db: AsyncSession,
        user_id: uuid.UUID,
        config: PPConfig | None = None,
    ) -> float:
        """Compute total PP for a user by querying their PP records.

        Uses ``final_pp`` (base_pp * performance_factor) for aggregation,
        sorted descending.

        Parameters
        ----------
        db :
            Async database session.
        user_id :
            The user whose total PP to calculate.
        config :
            Optional config override.

        Returns
        -------
        float
            Aggregated total PP, rounded to 2 decimal places.
        """
        if config is None:
            config = _DEFAULT_CONFIG

        stmt = (
            select(PPRecord.final_pp)
            .where(PPRecord.user_id == user_id)
            .order_by(PPRecord.final_pp.desc())
            .limit(config.max_problems)
        )
        result = await db.execute(stmt)
        pp_values = [row[0] for row in result.all()]

        return PPService.aggregate_total_pp(pp_values, config)

    # ------------------------------------------------------------------
    # 6. Refresh user.pp field
    # ------------------------------------------------------------------

    @staticmethod
    async def refresh_user_pp(
        db: AsyncSession,
        user_id: uuid.UUID,
        config: PPConfig | None = None,
    ) -> float:
        """Recalculate total PP for a user and update ``users.pp``.

        Parameters
        ----------
        db :
            Async database session.
        user_id :
            The user whose PP to refresh.
        config :
            Optional config override.

        Returns
        -------
        float
            The updated total PP value.
        """
        if config is None:
            config = _DEFAULT_CONFIG

        total_pp = await PPService.calculate_user_total_pp(db, user_id, config)

        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user is not None:
            user.pp = total_pp
            await db.flush()

        return total_pp

    # ------------------------------------------------------------------
    # 7. PP Ranking
    # ------------------------------------------------------------------

    @staticmethod
    async def get_pp_ranking(
        db: AsyncSession,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[tuple[int, str, float]], int]:
        """Return a paginated PP leaderboard.

        Results are ordered by ``users.pp`` descending, then by ``username``
        ascending as a tiebreaker.

        Parameters
        ----------
        db :
            Async database session.
        page :
            1-based page number.
        page_size :
            Number of users per page.

        Returns
        -------
        tuple[list[tuple[int, str, float]], int]
            A pair of (ranking_rows, total_count).  Each row is
            ``(rank, username, pp)`` where rank is 1-based.
        """
        # Validate pagination inputs
        page = max(1, page)
        page_size = max(1, min(page_size, 100))

        # Total count
        count_stmt = select(func.count()).select_from(User).where(User.is_active.is_(True))
        total = (await db.execute(count_stmt)).scalar_one()

        # Paginated query
        offset = (page - 1) * page_size
        stmt = (
            select(User.username, User.pp)
            .where(User.is_active.is_(True))
            .order_by(User.pp.desc(), User.username.asc())
            .offset(offset)
            .limit(page_size)
        )
        result = await db.execute(stmt)
        rows = result.all()

        # Calculate absolute rank based on page offset
        ranking = [(offset + i + 1, row[0], row[1]) for i, row in enumerate(rows)]

        return ranking, total

    # ------------------------------------------------------------------
    # 8. Utility – get user rank
    # ------------------------------------------------------------------

    @staticmethod
    async def get_user_rank(
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> int | None:
        """Return the 1-based PP rank for a specific user.

        The rank is the number of active users whose PP is strictly greater
        than this user's PP, plus one.  Returns ``None`` if the user does not
        exist.

        Parameters
        ----------
        db :
            Async database session.
        user_id :
            The user whose rank to look up.

        Returns
        -------
        int | None
            1-based rank, or None if user not found.
        """
        # Get user's PP
        user_stmt = select(User.pp).where(User.id == user_id, User.is_active.is_(True))
        result = await db.execute(user_stmt)
        user_pp = result.scalar_one_or_none()
        if user_pp is None:
            return None

        # Count users with higher PP
        higher_stmt = (
            select(func.count())
            .select_from(User)
            .where(
                User.is_active.is_(True),
                User.pp > user_pp,
            )
        )
        higher_count = (await db.execute(higher_stmt)).scalar_one()

        return higher_count + 1
