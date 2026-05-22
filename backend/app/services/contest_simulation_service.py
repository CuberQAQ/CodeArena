"""Contest simulation service -- generates AI bots and simulates their performance.

Handles:
- Generating N bots with Elo normally distributed around the user's Elo
- Tick-by-tick simulation of bot problem-solving using P(AC) formula
- Each bot works on one problem at a time, with Elo-aware delays
- Retry mechanism on failed attempts
- Give-up mechanism for problems far above bot's Elo
- Starting/stopping background simulation tasks
- Building combined human+bot leaderboards
"""

import asyncio
import contextlib
import logging
import random
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.default_config import DEFAULT_CONFIG
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
    "Algo",
    "Code",
    "Binary",
    "Quick",
    "Smart",
    "Deep",
    "Logic",
    "Pixel",
    "Turbo",
    "Super",
    "Hyper",
    "Ultra",
    "Mega",
    "Micro",
    "Nano",
    "Brute",
    "Greedy",
    "Dynamic",
    "Sparse",
    "Swift",
    "Optimal",
    "Random",
    "Minimal",
    "Parallel",
    "Serial",
    "Async",
    "Linear",
    "Vertex",
    "Edge",
    "Node",
]

_SUFFIXES: list[str] = [
    "King",
    "Queen",
    "Master",
    "Ninja",
    "Wizard",
    "Hacker",
    "Bot",
    "Dev",
    "Coder",
    "Solver",
    "Pro",
    "Guru",
    "Ace",
    "Star",
    "Fox",
    "Panda",
    "Eagle",
    "Tiger",
    "Dragon",
    "Knight",
    "Rogue",
    "Sage",
    "Wolf",
    "Hawk",
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
# Per-contest bot states (in-memory, not persisted to DB)
# Key: contest_id, Value: dict mapping bot_id -> bot state dict
# ---------------------------------------------------------------------------

_bot_states: dict[uuid.UUID, dict[uuid.UUID, dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# Simulation config helpers
# ---------------------------------------------------------------------------


def _get_simulation_config() -> dict[str, Any]:
    """Return the contest.simulation config dict from DEFAULT_CONFIG.

    Used as a fallback when no db session is available (e.g. in background
    loop).  The config service cache TTL is 60s which is good enough for
    hot-reload behaviour when combined with the tick interval.
    """
    return DEFAULT_CONFIG.get("contest", {}).get("simulation", {})


# ---------------------------------------------------------------------------
# Elo-aware tick calculation
# ---------------------------------------------------------------------------


def _get_ticks_for_bot_problem(
    bot_elo: int,
    problem_rating: int,
    total_minutes: int,
    n_problems: int,
    tick_interval: int = 30,
    jitter: float = 0.3,
) -> int:
    """Calculate ticks needed for a bot to attempt a problem.

    The model uses an Elo-gap scaling formula that determines how long a bot
    spends on a problem based on the relationship between the bot's Elo and
    the problem's rating.

    Key behaviors:
    - Higher Elo bots solve lower-rated problems faster
    - Lower Elo bots spend much more time on hard problems
    - Tick count scales with contest duration and problem count
    - Random jitter (+/-30%) adds natural variation

    Parameters
    ----------
    bot_elo:
        The bot's Elo rating.
    problem_rating:
        The problem's difficulty rating.
    total_minutes:
        Total contest duration in minutes.
    n_problems:
        Number of problems in the contest.
    tick_interval:
        Seconds per simulation tick.
    jitter:
        Fractional jitter to apply (0.3 = +/-30%).

    Returns
    -------
    int
        Number of ticks (always >= 1).
    """
    # Effective Elo: ensure minimum of 800 for calculations
    effective_elo = max(bot_elo, 800)
    effective_rating = max(problem_rating, 800)

    # Elo ratio: how hard is this problem for this bot?
    # ratio > 1.0 means problem is harder than bot's level
    # ratio < 1.0 means problem is easier than bot's level
    elo_ratio = effective_rating / effective_elo

    # Base ticks per problem: proportional to contest duration and problem count.
    # A bot that solves all problems would spend total_ticks / n_problems ticks
    # on average per problem. Scale by elo_ratio so harder problems take more.
    total_ticks = total_minutes * 60 / tick_interval
    base_ticks_per_problem = total_ticks / n_problems

    # Scale by elo_ratio: problems above the bot's level take proportionally
    # longer, problems below take proportionally less time.
    # Use a power function to create steeper differentiation:
    #   ratio < 1.0 -> fewer ticks (easy for this bot)
    #   ratio = 1.0 -> average ticks
    #   ratio > 1.0 -> more ticks (hard for this bot)
    scaled_ticks = base_ticks_per_problem * (elo_ratio**1.5)

    # Ensure minimum of 1 tick
    ticks = max(1, int(scaled_ticks))

    # Apply +/- jitter
    if jitter > 0:
        jitter_amount = ticks * jitter
        ticks = max(1, int(ticks + random.uniform(-jitter_amount, jitter_amount)))

    return max(1, ticks)


def _get_tick_range_for_rating(
    rating: int,
    difficulty_ticks: dict[str, list[int]] | None = None,
    jitter: float = 0.3,
) -> int:
    """Return the number of ticks a bot needs to work on a problem.

    .. deprecated::
        This function uses only problem difficulty, ignoring bot Elo.
        It is retained for backward compatibility when the new config
        keys are not present.  New code should use ``_get_ticks_for_bot_problem``.

    Parameters
    ----------
    rating:
        Problem rating.
    difficulty_ticks:
        Dict with keys "easy", "medium", "hard" mapping to [min, max] lists.
        Falls back to DEFAULT_CONFIG if not provided.
    jitter:
        Fractional jitter to apply (0.3 = +/-30%).

    Returns
    -------
    int
        Number of ticks (always >= 1).
    """
    if difficulty_ticks is None:
        difficulty_ticks = _get_simulation_config().get(
            "difficulty_ticks",
            {"easy": [2, 4], "medium": [6, 16], "hard": [16, 30]},
        )

    if rating < 1200:
        lo, hi = difficulty_ticks.get("easy", [2, 4])
    elif rating < 1800:
        lo, hi = difficulty_ticks.get("medium", [6, 16])
    else:
        lo, hi = difficulty_ticks.get("hard", [16, 30])

    # Sample a base value uniformly from [lo, hi]
    base = random.randint(lo, hi)

    # Apply +/- jitter
    jitter_amount = int(base * jitter)
    base += random.randint(-jitter_amount, jitter_amount)

    return max(1, base)


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

        Each bot works on one unsolved problem at a time with a tick-based
        delay determined by the relationship between the bot's Elo and the
        problem's difficulty rating.  When the delay expires, the bot rolls
        P(AC) to determine if it solved the problem.  Bots may retry failed
        problems or skip problems far above their skill level.

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

        # Read simulation config
        sim_config = _get_simulation_config()
        tick_interval = sim_config.get("tick_interval_seconds", 30)
        jitter = sim_config.get("jitter", 0.3)
        give_up_threshold = sim_config.get("give_up_threshold", 800)
        retry_base_prob = sim_config.get("retry_base_prob", 0.3)

        # Get or create bot states for this contest
        contest_states = _bot_states.setdefault(contest_id, {})

        # Fetch bots
        bots_stmt = select(ContestBot).where(ContestBot.contest_id == contest_id)
        bots_result = await db.execute(bots_stmt)
        bots = bots_result.scalars().all()

        all_newly_solved: list[str] = []

        for bot in bots:
            # Get or initialize state for this bot
            bot_state = contest_states.setdefault(
                bot.id,
                {
                    "current_problem": None,
                    "ticks_remaining": 0,
                    "attempted_and_failed": [],  # track failed problem_ids for retry
                    "skipped_problems": [],  # problems this bot gave up on
                },
            )

            newly_solved = ContestSimulationService._simulate_bot_tick(
                bot,
                problems,
                time_factor,
                bot_state,
                total_minutes=total_minutes,
                n_problems=len(problems),
                tick_interval=tick_interval,
                jitter=jitter,
                give_up_threshold=give_up_threshold,
                retry_base_prob=retry_base_prob,
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
            """Background loop: tick at configured interval until contest ends."""
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
                                logger.exception("Error in simulation tick for contest %s", contest_id)
                    except Exception:
                        logger.exception("DB session error in simulation for contest %s", contest_id)

                    # Read tick interval from config (allows hot-reload)
                    sim_config = _get_simulation_config()
                    tick_interval = sim_config.get("tick_interval_seconds", 30)
                    await asyncio.sleep(tick_interval)
            except asyncio.CancelledError:
                logger.info("Simulation cancelled for contest %s", contest_id)
            except Exception:
                logger.exception("Simulation crashed for contest %s", contest_id)
            finally:
                _active_simulations.pop(contest_id, None)
                # Clean up bot states
                _bot_states.pop(contest_id, None)
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
        # Clean up bot states regardless
        _bot_states.pop(contest_id, None)
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
        entries.append(
            LeaderboardEntry(
                rank=0,  # placeholder, will be set after sorting
                name=user.username,
                elo=user.elo,
                solved=session.problems_solved,
                is_bot=False,
            )
        )

        # Bot entries
        for bot in bots:
            entries.append(
                LeaderboardEntry(
                    rank=0,
                    name=bot.bot_name,
                    elo=bot.bot_elo,
                    solved=bot.problems_solved,
                    is_bot=True,
                )
            )

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
            player_solved,
            bot_elos,
            problem_ratings,
        )

        # Binary search for PR in [0, 4000]
        lo, hi = 0, 4000
        while hi - lo > 1:
            mid = (lo + hi) // 2
            expected_rank = ContestSimulationService.calculate_expected_rank(
                mid,
                bot_elos,
                problem_ratings,
                player_solved,
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
        bot_state: dict[str, Any],
        total_minutes: int = 120,
        n_problems: int = 5,
        tick_interval: int = 30,
        jitter: float = 0.3,
        give_up_threshold: int = 800,
        retry_base_prob: float = 0.3,
        difficulty_ticks: dict[str, list[int]] | None = None,
    ) -> list[str]:
        """Simulate a single bot's problem-solving for one tick.

        Each bot works on one problem at a time.  It first selects the
        lowest-rating unsolved problem (that it hasn't given up on), then
        spends an Elo-aware number of ticks working on it.  When the tick
        counter expires, it rolls P(AC) to determine success.  On failure,
        it may retry the problem.  Problems far above the bot's Elo are
        skipped entirely.

        Parameters
        ----------
        bot:
            The bot to simulate.
        problems:
            List of problem dicts with at least 'problem_id' and 'rating' keys.
        time_factor:
            A multiplier (0.0-1.0) that scales P(AC) based on time elapsed.
        bot_state:
            In-memory state dict for this bot with keys:
            - "current_problem": str | None -- problem_id being worked on
            - "ticks_remaining": int -- ticks left until P(AC) roll
            - "attempted_and_failed": list[str] -- problem_ids that failed
            - "skipped_problems": list[str] -- problem_ids the bot gave up on
        total_minutes:
            Total contest duration in minutes.
        n_problems:
            Number of problems in the contest.
        tick_interval:
            Seconds per simulation tick.
        jitter:
            Fractional jitter for tick calculation.
        give_up_threshold:
            Problems rated more than this above bot Elo are skipped.
        retry_base_prob:
            Base probability of retrying a failed problem.
        difficulty_ticks:
            Optional override for legacy difficulty tick ranges.

        Returns
        -------
        list[str]
            IDs of problems the bot solved this tick.
        """
        solved_set = set(bot.solved_problem_ids or [])
        newly_solved: list[str] = []

        # Get skipped and failed lists from state
        skipped = set(bot_state.get("skipped_problems", []))
        failed = set(bot_state.get("attempted_and_failed", []))

        # Find unsolved problems, sorted by rating ascending (easiest first),
        # excluding problems the bot has given up on
        unsolved = sorted(
            [
                p
                for p in problems
                if p.get("problem_id", "") not in solved_set and p.get("problem_id", "") not in skipped
            ],
            key=lambda p: p.get("rating", 1000),
        )

        # If all problems are solved, skipped, or none exist, nothing to do
        if not unsolved:
            bot.total_attempts += 1
            return newly_solved

        current_problem = bot_state.get("current_problem")
        ticks_remaining = bot_state.get("ticks_remaining", 0)

        # If bot is idle or its current problem is already solved/skipped, pick next
        if current_problem is None or current_problem in solved_set or current_problem in skipped:
            next_problem = None
            for p in unsolved:
                pid = p.get("problem_id", "")
                rating = p.get("rating", 1000)

                # Give-up mechanism: skip problems far above bot's Elo
                if rating > bot.bot_elo + give_up_threshold:
                    skipped.add(pid)
                    bot_state.setdefault("skipped_problems", []).append(pid)
                    logger.debug(
                        "Bot %s (elo=%d) skips problem %s (rating=%d, threshold=%d)",
                        bot.bot_name,
                        bot.bot_elo,
                        pid,
                        rating,
                        bot.bot_elo + give_up_threshold,
                    )
                    continue

                next_problem = p
                break

            if next_problem is None:
                # No solvable problems left for this bot
                bot.total_attempts += 1
                return newly_solved

            current_problem = next_problem.get("problem_id", "")
            rating = next_problem.get("rating", 1000)

            # Use Elo-aware tick calculation
            ticks_remaining = _get_ticks_for_bot_problem(
                bot_elo=bot.bot_elo,
                problem_rating=rating,
                total_minutes=total_minutes,
                n_problems=n_problems,
                tick_interval=tick_interval,
                jitter=jitter,
            )
            bot_state["current_problem"] = current_problem
            bot_state["ticks_remaining"] = ticks_remaining

        # Decrement tick counter
        ticks_remaining -= 1
        bot_state["ticks_remaining"] = ticks_remaining

        # If still working, return empty (no solve this tick)
        if ticks_remaining > 0:
            bot.total_attempts += 1
            return newly_solved

        # Tick counter reached 0 -- roll P(AC)
        problem = next(
            (p for p in problems if p.get("problem_id", "") == current_problem),
            None,
        )
        if problem is not None:
            rating = problem.get("rating", 1000)
            # P(AC) = 1 / (1 + 10^((rating - bot_elo) / 400))
            p_ac = 1.0 / (1.0 + 10.0 ** ((rating - bot.bot_elo) / 400.0))

            if random.random() < p_ac * time_factor:
                solved_set.add(current_problem)
                newly_solved.append(current_problem)
                # Remove from failed set if it was there
                failed.discard(current_problem)
            else:
                # Failed attempt: record and decide on retry
                failed.add(current_problem)

                # Retry mechanism: probability based on Elo ratio
                effective_elo = max(bot.bot_elo, 800)
                effective_rating = max(rating, 800)
                retry_prob = retry_base_prob * min(1.0, effective_elo / effective_rating)

                if random.random() < retry_prob:
                    # Bot will retry: re-queue the current problem
                    # The problem stays in the unsolved list, and the bot will
                    # pick it up again on the next tick (since it's the easiest unsolved)
                    bot_state["current_problem"] = None
                    bot_state["ticks_remaining"] = 0
                    # Update failed tracking
                    bot_state["attempted_and_failed"] = list(failed)
                    bot.total_attempts += 1
                    # Note: solved_set is NOT updated -- problem remains unsolved
                    return newly_solved
                # else: move on to next problem (fall through)

        # Move to next problem for next tick
        bot_state["current_problem"] = None
        bot_state["ticks_remaining"] = 0
        bot_state["attempted_and_failed"] = list(failed)

        # Update bot state on the ORM object
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
