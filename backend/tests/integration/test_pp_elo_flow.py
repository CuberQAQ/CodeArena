"""Integration test: PP aggregation and Elo calculation.

Tests PP recording, total PP aggregation with decay, Elo calculation for
challenges and contests, and the interplay between PP and Elo.
"""

import math
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.elo_history import EloHistory
from app.models.pp_record import PPRecord

from .conftest import (
    create_test_user,
)


# ---------------------------------------------------------------------------
# PP Tests
# ---------------------------------------------------------------------------


class TestPPBaseCalculation:
    """Test base PP calculation for individual problems."""

    def test_below_offset_gives_zero(self):
        """Problems below the offset rating (800) give 0 PP."""
        from app.services.pp_service import PPService, PPConfig

        assert PPService.calculate_base_pp(500) == 0.0
        assert PPService.calculate_base_pp(799) == 0.0

    def test_exactly_offset_gives_zero(self):
        """A problem exactly at the offset (800) gives 0 PP."""
        from app.services.pp_service import PPService
        assert PPService.calculate_base_pp(800) == 0.0

    def test_above_offset_gives_positive(self):
        """Problems above offset give positive PP."""
        from app.services.pp_service import PPService

        pp = PPService.calculate_base_pp(900)
        assert pp > 0
        expected = math.sqrt(100 / 100.0) * 10.0
        assert abs(pp - expected) < 0.01

    def test_higher_rating_gives_more_pp(self):
        """Higher rated problems give more PP."""
        from app.services.pp_service import PPService

        pp_1000 = PPService.calculate_base_pp(1000)
        pp_1500 = PPService.calculate_base_pp(1500)
        pp_2000 = PPService.calculate_base_pp(2000)

        assert pp_1000 < pp_1500 < pp_2000

    def test_base_pp_formula(self):
        """Verify the exact formula: sqrt((rating - offset) / 100) * coefficient."""
        from app.services.pp_service import PPService, PPConfig

        config = PPConfig()
        rating = 1800
        expected = math.sqrt((rating - config.base_formula_offset) / 100.0) * config.base_formula_coefficient
        assert abs(PPService.calculate_base_pp(rating, config) - expected) < 0.001


class TestPPTotalAggregation:
    """Test total PP aggregation with decay."""

    def test_empty_list_gives_zero(self):
        """Empty PP list gives total 0."""
        from app.services.pp_service import PPService
        assert PPService.aggregate_total_pp([]) == 0.0

    def test_single_problem_no_decay(self):
        """Single problem: total equals base PP (no decay on first item)."""
        from app.services.pp_service import PPService
        pp = PPService.aggregate_total_pp([30.0])
        assert pp == 30.0

    def test_multiple_problems_with_decay(self):
        """Multiple problems are weighted with decreasing decay factor."""
        from app.services.pp_service import PPService, PPConfig

        values = [40.0, 30.0, 20.0]
        config = PPConfig()
        expected = (
            40.0 * (config.decay_factor ** 0)
            + 30.0 * (config.decay_factor ** 1)
            + 20.0 * (config.decay_factor ** 2)
        )
        result = PPService.aggregate_total_pp(values, config)
        assert abs(result - round(expected, 2)) < 0.01

    def test_sorted_descending_gives_higher_total(self):
        """Descending order gives the highest possible total."""
        from app.services.pp_service import PPService

        desc = PPService.aggregate_total_pp([50.0, 30.0, 10.0])
        asc = PPService.aggregate_total_pp([10.0, 30.0, 50.0])
        assert desc > asc

    def test_max_problems_cap(self):
        """Only max_problems entries are considered."""
        from app.services.pp_service import PPService, PPConfig

        config = PPConfig(max_problems=3)
        many_values = [50.0] * 10
        result = PPService.aggregate_total_pp(many_values, config)
        expected = 50.0 * (0.95 ** 0 + 0.95 ** 1 + 0.95 ** 2)
        assert abs(result - round(expected, 2)) < 0.01


class TestPPRecording:
    """Test PP record creation and user PP refresh."""

    async def test_record_pp_creates_record(self, db_session):
        """Recording PP creates a PPRecord in the database."""
        from app.services.pp_service import PPService

        user = await create_test_user(db_session)
        await db_session.commit()

        record = await PPService.record_pp(
            db_session, user.id, cf_problem_id="1000A", problem_rating=1200
        )
        assert record.cf_problem_id == "1000A"
        assert record.problem_rating == 1200
        assert record.base_pp > 0

    async def test_record_pp_updates_user_total(self, db_session):
        """Recording PP refreshes the user's total PP."""
        from app.services.pp_service import PPService

        user = await create_test_user(db_session)
        await db_session.commit()

        await PPService.record_pp(
            db_session, user.id, cf_problem_id="1000A", problem_rating=1200
        )

        await db_session.refresh(user)
        assert user.pp > 0

    async def test_record_pp_multiple_problems_aggregates(self, db_session):
        """Solving multiple problems aggregates PP correctly."""
        from app.services.pp_service import PPService, PPConfig

        user = await create_test_user(db_session)
        await db_session.commit()

        config = PPConfig()
        pp_values = []

        # Solve 3 problems at different ratings
        for i, rating in enumerate([1000, 1200, 1500]):
            pid = f"100{i}A"
            await PPService.record_pp(
                db_session, user.id, cf_problem_id=pid, problem_rating=rating
            )
            pp_values.append(PPService.calculate_base_pp(rating, config))

        # Verify user PP matches aggregation
        total_pp = PPService.aggregate_total_pp(sorted(pp_values, reverse=True))
        await db_session.refresh(user)
        assert abs(user.pp - total_pp) < 0.1

    async def test_record_pp_same_problem_higher_rating_updates(self, db_session):
        """Re-recording a problem with higher rating updates the record."""
        from app.services.pp_service import PPService

        user = await create_test_user(db_session)
        await db_session.commit()

        await PPService.record_pp(
            db_session, user.id, cf_problem_id="1000A", problem_rating=1000
        )
        await PPService.record_pp(
            db_session, user.id, cf_problem_id="1000A", problem_rating=1500
        )

        # Should have only one PP record, with the higher rating
        from sqlalchemy import select
        stmt = select(PPRecord).where(
            PPRecord.user_id == user.id,
            PPRecord.cf_problem_id == "1000A",
        )
        result = await db_session.execute(stmt)
        records = list(result.scalars().all())
        assert len(records) == 1
        assert records[0].problem_rating == 1500


# ---------------------------------------------------------------------------
# Elo Tests
# ---------------------------------------------------------------------------


class TestEloCalculation:
    """Test Elo rating calculations."""

    def test_expected_score_equal_ratings(self):
        """Equal ratings give expected score 0.5."""
        from app.services.elo_service import EloService
        assert abs(EloService.calculate_expected_score(1200, 1200) - 0.5) < 0.001

    def test_expected_score_higher_rating(self):
        """Higher-rated player has expected score > 0.5."""
        from app.services.elo_service import EloService
        e = EloService.calculate_expected_score(1500, 1200)
        assert e > 0.5

    def test_expected_score_lower_rating(self):
        """Lower-rated player has expected score < 0.5."""
        from app.services.elo_service import EloService
        e = EloService.calculate_expected_score(1000, 1500)
        assert e < 0.5

    def test_new_rating_win(self):
        """Winning increases rating."""
        from app.services.elo_service import EloService
        new = EloService.calculate_new_rating(1200, 0.5, 1.0)
        assert new > 1200

    def test_new_rating_loss(self):
        """Losing decreases rating."""
        from app.services.elo_service import EloService
        new = EloService.calculate_new_rating(1200, 0.5, 0.0)
        assert new < 1200

    def test_new_rating_draw(self):
        """Draw with equal expected keeps rating roughly same."""
        from app.services.elo_service import EloService
        new = EloService.calculate_new_rating(1200, 0.5, 0.5)
        assert new == 1200

    def test_challenge_elo_both_players_update(self):
        """Challenge Elo updates both players' ratings."""
        from app.services.elo_service import EloService

        new_a, new_b, change_a = EloService.calculate_challenge_elo(
            rating_a=1200, rating_b=1200, actual_score_a=1.0
        )
        assert new_a > 1200  # winner gains
        assert new_b < 1200  # loser loses
        assert change_a > 0

    def test_challenge_elo_hint_attenuation(self):
        """Using hints reduces positive Elo gains."""
        from app.services.elo_service import EloService

        # Without hints
        _, _, change_no_hints = EloService.calculate_challenge_elo(
            rating_a=1200, rating_b=1200, actual_score_a=1.0, hint_level=0
        )
        # With level 1 hints
        _, _, change_hints_1 = EloService.calculate_challenge_elo(
            rating_a=1200, rating_b=1200, actual_score_a=1.0, hint_level=1
        )
        assert change_hints_1 < change_no_hints

    def test_challenge_elo_loss_not_attenuated(self):
        """Hint attenuation does not affect losses."""
        from app.services.elo_service import EloService

        _, _, change_no_hints = EloService.calculate_challenge_elo(
            rating_a=1200, rating_b=1200, actual_score_a=0.0, hint_level=0
        )
        _, _, change_hints = EloService.calculate_challenge_elo(
            rating_a=1200, rating_b=1200, actual_score_a=0.0, hint_level=3
        )
        assert change_no_hints == change_hints  # losses are identical


class TestEloQuitPenalty:
    """Test Elo quit penalty calculation."""

    def test_zero_submissions_no_penalty(self):
        """0 submissions = no penalty."""
        from app.services.elo_service import EloService
        assert EloService.calculate_quit_penalty(0) == 0

    def test_one_two_submissions_small_penalty(self):
        """1-2 submissions = small random penalty."""
        from app.services.elo_service import EloService
        for _ in range(10):
            penalty = EloService.calculate_quit_penalty(1)
            assert -10 <= penalty <= -5

            penalty = EloService.calculate_quit_penalty(2)
            assert -10 <= penalty <= -5

    def test_three_plus_submissions_sentinel(self):
        """3+ submissions returns -1 (use normal loss)."""
        from app.services.elo_service import EloService
        assert EloService.calculate_quit_penalty(3) == -1
        assert EloService.calculate_quit_penalty(10) == -1


class TestEloContest:
    """Test M-Elo contest calculation."""

    def test_contest_score_all_solved(self):
        """Solving all problems gives base_score 1.0."""
        from app.services.elo_service import EloService
        score = EloService.calculate_contest_score(4, 4, 1800.0, 5400.0)
        assert score > 0.5  # base_score = 1.0 + some time bonus

    def test_contest_score_none_solved(self):
        """Solving no problems gives base_score 0.0."""
        from app.services.elo_service import EloService
        score = EloService.calculate_contest_score(0, 4, 1800.0, 5400.0)
        assert score < 0.3  # base_score = 0.0 + small time bonus

    def test_contest_elo_gain_on_good_performance(self):
        """Good contest performance increases Elo."""
        from app.services.elo_service import EloService
        new_rating, elo_change = EloService.calculate_contest_elo(
            current_rating=1200,
            solved_problems=4,
            total_problems=4,
            time_used_seconds=1800.0,
            time_limit_seconds=5400.0,
        )
        assert new_rating > 1200
        assert elo_change > 0

    def test_contest_elo_loss_on_poor_performance(self):
        """Poor contest performance decreases Elo."""
        from app.services.elo_service import EloService
        new_rating, elo_change = EloService.calculate_contest_elo(
            current_rating=1200,
            solved_problems=0,
            total_problems=4,
            time_used_seconds=5400.0,
            time_limit_seconds=5400.0,
        )
        assert new_rating < 1200
        assert elo_change < 0


class TestEloHistoryRecording:
    """Test Elo history persistence."""

    async def test_record_elo_history(self, db_session):
        """Elo history is recorded correctly."""
        from app.services.elo_service import EloService, EloReason

        user = await create_test_user(db_session)
        await db_session.commit()

        record = await EloService.record_elo_history(
            db_session, user.id,
            elo_before=1200, elo_after=1232,
            reason=EloReason.CHALLENGE_WIN,
            reference_id=uuid.uuid4(),
        )
        assert record.elo_before == 1200
        assert record.elo_after == 1232
        assert record.elo_change == 32

    async def test_process_challenge_result_records_both(self, db_session):
        """Processing a challenge result records history for both players."""
        from app.services.elo_service import EloService

        user_a = await create_test_user(db_session, username="elo_a", email="elo_a@test.com", elo=1200)
        user_b = await create_test_user(db_session, username="elo_b", email="elo_b@test.com", elo=1200)
        await db_session.commit()

        session_id = uuid.uuid4()
        await EloService.process_challenge_result(
            db_session,
            challenger_id=user_a.id,
            opponent_id=user_b.id,
            challenger_rating=1200,
            opponent_rating=1200,
            actual_score_a=1.0,
            session_id=session_id,
        )

        from sqlalchemy import select
        stmt = select(EloHistory).where(EloHistory.reference_id == session_id)
        result = await db_session.execute(stmt)
        records = list(result.scalars().all())
        assert len(records) == 2  # one for each player


class TestPPAndEloIntegration:
    """Test the interplay between PP and Elo."""

    async def test_challenge_updates_both_pp_and_elo(self, db_session):
        """Solving a challenge problem updates both PP and Elo."""
        user_a = await create_test_user(db_session, username="pp_elo_a", email="pp_elo_a@test.com", elo=1200)
        user_b = await create_test_user(db_session, username="pp_elo_b", email="pp_elo_b@test.com", elo=1200)
        await db_session.commit()

        from app.services.elo_service import EloService
        from app.services.pp_service import PPService

        # Simulate challenge settlement
        new_a, new_b, _, _ = await EloService.process_challenge_result(
            db_session,
            challenger_id=user_a.id,
            opponent_id=user_b.id,
            challenger_rating=1200,
            opponent_rating=1200,
            actual_score_a=1.0,
            session_id=uuid.uuid4(),
        )
        user_a.elo = new_a
        await PPService.record_pp(
            db_session, user_a.id, cf_problem_id="1000A", problem_rating=1500
        )

        await db_session.refresh(user_a)
        assert user_a.elo > 1200  # Elo increased
        assert user_a.pp > 0  # PP updated

    async def test_multiple_solves_build_pp_progressively(self, db_session):
        """Solving multiple problems builds PP progressively with decay."""
        from app.services.pp_service import PPService, PPConfig

        user = await create_test_user(db_session)
        await db_session.commit()

        config = PPConfig()
        pp_values = []

        # Solve problems at ratings 1200, 1400, 1600, 1800, 2000
        ratings = [1200, 1400, 1600, 1800, 2000]
        for i, rating in enumerate(ratings):
            pid = f"prob_{i}"
            await PPService.record_pp(
                db_session, user.id, cf_problem_id=pid, problem_rating=rating
            )
            pp_values.append(PPService.calculate_base_pp(rating, config))

        await db_session.refresh(user)

        # Verify PP is the aggregated total
        expected_total = PPService.aggregate_total_pp(
            sorted(pp_values, reverse=True), config
        )
        assert abs(user.pp - expected_total) < 0.1

        # Verify PP is positive
        assert user.pp > 0

        # Each additional solve should increase (or maintain) total PP
        # because we're adding more weighted values
        assert user.pp >= pp_values[0]  # at least the first value

    async def test_pp_ranking(self, db_session):
        """PP ranking orders users by total PP."""
        from app.services.pp_service import PPService

        user_a = await create_test_user(db_session, username="rank_a", email="rank_a@test.com", elo=1200)
        user_b = await create_test_user(db_session, username="rank_b", email="rank_b@test.com", elo=1200)
        await db_session.commit()

        # User A solves a harder problem -> higher PP
        await PPService.record_pp(
            db_session, user_a.id, cf_problem_id="2000A", problem_rating=2000
        )

        # User B solves an easier problem -> lower PP
        await PPService.record_pp(
            db_session, user_b.id, cf_problem_id="1000A", problem_rating=1000
        )

        ranking, total = await PPService.get_pp_ranking(db_session)
        assert total >= 2

        # User A should be ranked higher
        user_a_rank = None
        user_b_rank = None
        for rank, username, pp in ranking:
            if username == "rank_a":
                user_a_rank = rank
            if username == "rank_b":
                user_b_rank = rank

        if user_a_rank is not None and user_b_rank is not None:
            assert user_a_rank < user_b_rank
