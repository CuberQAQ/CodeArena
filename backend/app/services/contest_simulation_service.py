"""Contest simulation service -- generates AI bots and simulates their performance.

Handles:
- Generating N bots with Elo normally distributed around the user's Elo
- Minute-by-minute simulation of bot problem-solving using P(AC) formula
- Starting/stopping background simulation tasks
- Building combined human+bot leaderboards
"""

import asyncio
import contextlib
import logging
import random
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contest_bot import ContestBot
from app.models.contest_session import ContestSession
from app.schemas.contest import LeaderboardEntry, LeaderboardResponse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger("code_arena.contest_simulation")

# ---------------------------------------------------------------------------
# Bot name generation
# ---------------------------------------------------------------------------

_PREFIXES: list[str] = [
    "Algo", "Code", "Binary", "Quick", "Smart", "Deep", "Logic", "Pixel",
    "Turbo", "Super", "Hyper", "Ultra", "Mega", "Micro", "Nano", "Brute",
    "Greedy", "Dynamic", "Sparse", "Swift", "Optimal", "Random", "Minimal",
    "Parallel", "Serial", "Async", "Linear", "Vertex", "Edge", "Node",
]

_SUFFIXES: list[str] = [
    "King", "Queen", "Master", "Ninja", "Wizard", "Hacker", "Bot", "Dev",
    "Coder", "Solver", "Pro", "Guru", "Ace", "Star", "Fox", "Panda",
    "Eagle", "Tiger", "Dragon", "Knight", "Rogue", "Sage", "Wolf", "Hawk",
]


def _generate_bot_name(index: int) -> str:
    """Generate a unique bot name from prefix + suffix + index."""
    prefix = random.choice(_PREFIXES)
    suffix = random.choice(_SUFFIXES)
    return f"{prefix}{suffix}_{index}"


# ---------------------------------------------------------------------------
# Active simulation tasks registry (module-level, keyed by contest_id)
# ---------------------------------------------------------------------------

_active_simulations: dict[uuid.UUID, asyncio.Task] = {}


# ---------------------------------------------------------------------------
# Contest Simulation Service
# ---------------------------------------------------------------------------


class ContestSimulationService:
    """Stateless service for bot generation and contest simulation.

    Each method receives the resources it needs (db session, parameters)
    as arguments.  Background simulation tasks are tracked in a module-level
    dict keyed by contest_id.
    """

    # ------------------------------------------------------------------
    # 1. Generate bots
    # ------------------------------------------------------------------

    @staticmethod
    async def generate_bots(
        db: AsyncSession,
        contest_id: uuid.UUID,
        user_elo: int,
        count: int = 50,
        sigma: int = 200,
    ) -> list[ContestBot]:
        """Generate *count* bots with Elo normally distributed around *user_elo*.

        Parameters
        ----------
        db:
            Async database session.
        contest_id:
            The contest session the bots belong to.
        user_elo:
            Mean Elo for the normal distribution.
        count:
            Number of bots to generate.  Must be >= 0.
        sigma:
            Standard deviation of the Elo distribution.

        Returns
        -------
        list[ContestBot]
            The newly created bot instances (already flushed to the session).
        """
        if count <= 0:
            return []

        used_names: set[str] = set()
        bots: list[ContestBot] = []

        for i in range(1, count + 1):
            # Generate unique name
            name = _generate_bot_name(i)
            attempts = 0
            while name in used_names and attempts < 100:
                name = _generate_bot_name(random.randint(1, count * 10))
                attempts += 1
            used_names.add(name)

            # Elo from normal distribution, clamped to reasonable range
            elo = max(0, int(random.gauss(user_elo, sigma)))

            bot = ContestBot(
                contest_id=contest_id,
                bot_name=name,
                bot_elo=elo,
                problems_solved=0,
                solved_problem_ids=[],
                total_attempts=0,
                created_at=datetime.now(UTC),
            )
            bots.append(bot)
            db.add(bot)

        await db.flush()
        logger.info("Generated %d bots for contest %s (mean_elo=%d)", count, contest_id, user_elo)
        return bots

    # ------------------------------------------------------------------
    # 2. Simulate one tick for all bots in a contest
    # ------------------------------------------------------------------

    @staticmethod
    async def tick_simulation(
        db: AsyncSession,
        contest_id: uuid.UUID,
    ) -> list[str]:
        """Run one simulation tick for all bots in a contest.

        For each bot, evaluates P(AC) against each unsolved problem and
        determines which problems are solved this tick.  Persists changes
        to the database.

        Parameters
        ----------
        db:
            Async database session.
        contest_id:
            The contest session to simulate.

        Returns
        -------
        list[str]
            IDs of all problems solved by any bot during this tick.
        """
        # Fetch contest session
        session = await db.get(ContestSession, contest_id)
        if session is None or session.status != "active":
            return []

        # Fetch problems
        problems = session.problems or []
        if not problems:
            return []

        # Calculate elapsed minutes
        started_at = ContestSimulationService._ensure_utc(session.started_at)
        elapsed_minutes = max(0, int((datetime.now(UTC) - started_at).total_seconds() / 60))
        total_minutes = session.time_limit

        # Time factor: bots slow down toward end of contest
        time_factor = ContestSimulationService._calculate_time_factor(elapsed_minutes, total_minutes)

        # Fetch bots
        bots_stmt = select(ContestBot).where(ContestBot.contest_id == contest_id)
        bots_result = await db.execute(bots_stmt)
        bots = bots_result.scalars().all()

        all_newly_solved: list[str] = []

        for bot in bots:
            newly_solved = ContestSimulationService._simulate_bot_tick(
                bot, problems, time_factor,
            )
            all_newly_solved.extend(newly_solved)

        await db.flush()
        return all_newly_solved

    # ------------------------------------------------------------------
    # 3. Start background simulation
    # ------------------------------------------------------------------

    @staticmethod
    async def start_simulation(
        contest_id: uuid.UUID,
        db_factory: "async_sessionmaker[AsyncSession]",
    ) -> asyncio.Task | None:
        """Start a background simulation task for a contest.

        Parameters
        ----------
        contest_id:
            The contest session to simulate.
        db_factory:
            An async session factory for creating new db sessions in the
            background task (each tick gets its own session).

        Returns
        -------
        asyncio.Task | None
            The background task, or None if a simulation is already running.
        """
        if contest_id in _active_simulations:
            logger.warning("Simulation already running for contest %s", contest_id)
            return None

        async def _run():
            """Background loop: tick every 60 seconds until contest ends."""
            logger.info("Simulation started for contest %s", contest_id)
            try:
                while contest_id in _active_simulations:
                    try:
                        async with db_factory() as db:
                            try:
                                await ContestSimulationService.tick_simulation(db, contest_id)
                                await db.commit()
                            except Exception:
                                await db.rollback()
                                logger.exception(
                                    "Error in simulation tick for contest %s", contest_id
                                )
                    except Exception:
                        logger.exception(
                            "DB session error in simulation for contest %s", contest_id
                        )

                    await asyncio.sleep(60)
            except asyncio.CancelledError:
                logger.info("Simulation cancelled for contest %s", contest_id)
            except Exception:
                logger.exception("Simulation crashed for contest %s", contest_id)
            finally:
                _active_simulations.pop(contest_id, None)
                logger.info("Simulation stopped for contest %s", contest_id)

        task = asyncio.create_task(_run())
        _active_simulations[contest_id] = task
        return task

    # ------------------------------------------------------------------
    # 4. Stop background simulation
    # ------------------------------------------------------------------

    @staticmethod
    async def stop_simulation(contest_id: uuid.UUID) -> bool:
        """Stop the background simulation task for a contest.

        Returns
        -------
        bool
            True if a simulation was stopped, False if none was running.
        """
        task = _active_simulations.pop(contest_id, None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            logger.info("Stopped simulation for contest %s", contest_id)
            return True
        return False

    # ------------------------------------------------------------------
    # 5. Build leaderboard
    # ------------------------------------------------------------------

    @staticmethod
    async def build_leaderboard(
        db: AsyncSession,
        contest_id: uuid.UUID,
        user: "User",  # noqa: F821
    ) -> LeaderboardResponse:
        """Build a combined human+bot leaderboard for a contest.

        Parameters
        ----------
        db:
            Async database session.
        contest_id:
            The contest session.
        user:
            The human player (for their current solved count).

        Returns
        -------
        LeaderboardResponse
            Sorted leaderboard with timing info.
        """
        session = await db.get(ContestSession, contest_id)
        if session is None:
            return LeaderboardResponse()

        # Fetch bots
        bots_stmt = select(ContestBot).where(ContestBot.contest_id == contest_id)
        bots_result = await db.execute(bots_stmt)
        bots = bots_result.scalars().all()

        # Build entries
        entries: list[LeaderboardEntry] = []

        # Human entry
        entries.append(LeaderboardEntry(
            rank=0,  # placeholder, will be set after sorting
            name=user.username,
            elo=user.elo,
            solved=session.problems_solved,
            is_bot=False,
        ))

        # Bot entries
        for bot in bots:
            entries.append(LeaderboardEntry(
                rank=0,
                name=bot.bot_name,
                elo=bot.bot_elo,
                solved=bot.problems_solved,
                is_bot=True,
            ))

        # Sort by solved desc, then by elo desc (tiebreaker)
        entries.sort(key=lambda e: (-e.solved, -e.elo))

        # Assign ranks
        for i, entry in enumerate(entries):
            entry.rank = i + 1

        # Timing
        started_at = ContestSimulationService._ensure_utc(session.started_at)
        elapsed = max(0, int((datetime.now(UTC) - started_at).total_seconds() / 60))
        total = session.time_limit

        return LeaderboardResponse(
            leaderboard=entries,
            time_elapsed=elapsed,
            time_total=total,
        )

    # ------------------------------------------------------------------
    # 6. Performance Rating (PR) calculation
    # ------------------------------------------------------------------

    @staticmethod
    async def calculate_performance_rating(
        db: AsyncSession,
        contest_id: uuid.UUID,
        player_solved: int,
    ) -> int:
        """Calculate the Performance Rating (PR) for a player via binary search.

        Finds the PR value such that, when treated as the player's Elo, the
        player's expected rank among all participants (bots + player) matches
        their actual rank.

        Parameters
        ----------
        db:
            Async database session.
        contest_id:
            The contest session whose bots are used as the reference field.
        player_solved:
            Number of problems solved by the human player.

        Returns
        -------
        int
            The Performance Rating, clamped to [0, 4000].
        """
        # Fetch contest session to get problem ratings
        session = await db.get(ContestSession, contest_id)
        problems: list[dict] = session.problems or [] if session else []

        # Fetch bots
        bots_stmt = select(ContestBot).where(ContestBot.contest_id == contest_id)
        bots_result = await db.execute(bots_stmt)
        bots = bots_result.scalars().all()

        bot_elos: list[int] = [b.bot_elo for b in bots]

        # Edge case: no bots -> PR equals a simple estimate based on solved ratio
        if not bot_elos:
            return ContestSimulationService._estimate_pr_no_bots(player_solved, problems)

        problem_ratings: list[int] = [p.get("rating", 1000) for p in problems]

        # Calculate actual rank (smooth) of the player among all participants
        # Uses the same sigmoid-based metric as calculate_expected_rank for consistency
        actual_rank = ContestSimulationService.calculate_actual_rank_smooth(
            player_solved, bot_elos, problem_ratings,
        )

        # Binary search for PR in [0, 4000]
        lo, hi = 0, 4000
        while hi - lo > 1:
            mid = (lo + hi) // 2
            expected_rank = ContestSimulationService.calculate_expected_rank(
                mid, bot_elos, problem_ratings, player_solved,
            )
            if expected_rank < actual_rank:
                hi = mid
            elif expected_rank > actual_rank:
                lo = mid
            else:
                # Exact match
                hi = mid
                break

        return hi

    @staticmethod
    def calculate_actual_rank(
        player_solved: int,
        bot_solved: list[int],
    ) -> int:
        """Calculate the player's actual rank (1-based, integer) among all participants.

        Rank is based on how many participants have strictly more problems
        solved, plus 1.

        Parameters
        ----------
        player_solved:
            Problems solved by the human player.
        bot_solved:
            List of problems solved by each bot.

        Returns
        -------
        int
            1-based rank.
        """
        # Count bots with strictly more solved than the player
        ahead = sum(1 for s in bot_solved if s > player_solved)
        return ahead + 1

    @staticmethod
    def calculate_actual_rank_smooth(
        player_solved: int,
        bot_elos: list[int],
        problem_ratings: list[int],
    ) -> float:
        """Calculate the player's actual rank as a target for the binary search.

        Computes each bot's expected solve count from their Elo, then counts
        how many bots have a higher expected solve count than the player's
        actual solve count, plus 1.

        This produces an integer-compatible rank value that serves as the
        target for the binary search.

        Parameters
        ----------
        player_solved:
            Problems solved by the human player.
        bot_elos:
            Elo values of all bots.
        problem_ratings:
            Ratings of all contest problems.

        Returns
        -------
        float
            Target rank for binary search (1-based).
        """
        player_solved_f = float(player_solved)
        n_problems = len(problem_ratings)
        if n_problems == 0:
            return 1.0

        # Each bot's expected solved count
        ahead = 0
        for elo in bot_elos:
            bot_expected_solved = 0.0
            for rating in problem_ratings:
                p_ac = 1.0 / (1.0 + 10.0 ** ((rating - elo) / 400.0))
                bot_expected_solved += p_ac
            if bot_expected_solved > player_solved_f:
                ahead += 1

        return float(ahead + 1)

    @staticmethod
    def calculate_expected_rank(
        player_elo: int,
        bot_elos: list[int],
        problem_ratings: list[int],
        player_solved: int,
    ) -> float:
        """Calculate the expected rank of the player given a hypothetical Elo.

        Computes each participant's expected solve count using P(AC) formula.
        The rank is 1 + (number of bots with higher expected solve count).

        This is directly comparable with ``calculate_actual_rank_smooth``.

        Parameters
        ----------
        player_elo:
            Hypothetical Elo (the PR candidate).
        bot_elos:
            Elo values of all bots.
        problem_ratings:
            Ratings of all contest problems.
        player_solved:
            Actual problems solved by the player (unused, kept for API compat).

        Returns
        -------
        float
            Expected rank (1-based).
        """
        n_problems = len(problem_ratings)
        if n_problems == 0:
            return 1.0

        # Player's expected solved count at this hypothetical Elo
        player_expected_solved = 0.0
        for rating in problem_ratings:
            p_ac = 1.0 / (1.0 + 10.0 ** ((rating - player_elo) / 400.0))
            player_expected_solved += p_ac

        # Count bots with higher expected solve count
        ahead = 0
        for elo in bot_elos:
            bot_expected_solved = 0.0
            for rating in problem_ratings:
                p_ac = 1.0 / (1.0 + 10.0 ** ((rating - elo) / 400.0))
                bot_expected_solved += p_ac
            if bot_expected_solved > player_expected_solved:
                ahead += 1

        return float(ahead + 1)

    @staticmethod
    def _estimate_pr_no_bots(
        player_solved: int,
        problems: list[dict],
    ) -> int:
        """Estimate PR when there are no bots (fallback).

        Uses the average problem rating as a baseline, adjusted by solve
        ratio.

        Returns
        -------
        int
            Estimated PR clamped to [0, 4000].
        """
        if not problems:
            return 1000  # default fallback
        avg_rating = sum(p.get("rating", 1000) for p in problems) / len(problems)
        solve_ratio = player_solved / len(problems) if problems else 0
        # Scale: full solve -> avg_rating * 1.5, no solve -> avg_rating * 0.5
        pr = int(avg_rating * (0.5 + solve_ratio))
        return max(0, min(4000, pr))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _simulate_bot_tick(
        bot: ContestBot,
        problems: list[dict],
        time_factor: float,
    ) -> list[str]:
        """Simulate a single bot's problem-solving attempts for one tick.

        Parameters
        ----------
        bot:
            The bot to simulate.
        problems:
            List of problem dicts with at least 'problem_id' and 'rating' keys.
        time_factor:
            A multiplier (0.0-1.0) that scales P(AC) based on time elapsed.

        Returns
        -------
        list[str]
            IDs of problems the bot solved this tick.
        """
        solved_set = set(bot.solved_problem_ids or [])
        newly_solved: list[str] = []

        for problem in problems:
            pid = problem.get("problem_id", "")
            if pid in solved_set:
                continue

            rating = problem.get("rating", 1000)
            # P(AC) = 1 / (1 + 10^((rating - bot_elo) / 400))
            p_ac = 1.0 / (1.0 + 10.0 ** ((rating - bot.bot_elo) / 400.0))

            if random.random() < p_ac * time_factor:
                solved_set.add(pid)
                newly_solved.append(pid)

        # Update bot state
        if bot.solved_problem_ids is None:
            bot.solved_problem_ids = []
        bot.solved_problem_ids = list(solved_set)
        bot.problems_solved = len(solved_set)
        bot.total_attempts += 1

        return newly_solved

    @staticmethod
    def _calculate_time_factor(elapsed_minutes: int, total_minutes: int) -> float:
        """Calculate time-based scaling factor for bot solve probability.

        Bots solve problems faster early in the contest and slow down
        toward the end, mimicking realistic contest behavior.

        Returns a value in [0.2, 1.0].
        """
        if total_minutes <= 0:
            return 1.0
        ratio = elapsed_minutes / total_minutes
        # Linear decay from 1.0 to 0.2 over the contest duration
        return max(0.2, 1.0 - 0.8 * ratio)

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        """Ensure a datetime is timezone-aware (UTC). Handles naive datetimes from SQLite."""
        if dt is None:
            return datetime.now(UTC)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt

    # ------------------------------------------------------------------
    # Utility: check if simulation is active
    # ------------------------------------------------------------------

    @staticmethod
    def is_simulation_active(contest_id: uuid.UUID) -> bool:
        """Return True if a simulation is currently running for the given contest."""
        task = _active_simulations.get(contest_id)
        return task is not None and not task.done()
