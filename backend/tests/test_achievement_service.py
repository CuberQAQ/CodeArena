"""Tests for the achievement event detection service.

Verifies that achievement events are correctly generated (or not) based on
game outcome conditions: overkill bonus, contest win, personal best PP.

Test scenarios:
1. Overkill bonus: triggered when multiplier > 1.0
2. Overkill bonus: not triggered when multiplier == 1.0
3. Overkill bonus: description varies by multiplier tier
4. Contest win: triggered when rank=1 and total > 1
5. Contest win: not triggered when rank > 1
6. Contest win: not triggered when only 1 participant
7. Personal best PP: triggered when new_pp > old_pp and old_pp > 0
8. Personal best PP: not triggered when old_pp == 0
9. Personal best PP: not triggered when new_pp <= old_pp
10. to_dict() serialization
"""

import pytest

from app.services.achievement_service import AchievementService, AchievementType


# ---------------------------------------------------------------------------
# Overkill bonus achievement tests
# ---------------------------------------------------------------------------


class TestCheckOverkill:
    """Verify overkill achievement detection."""

    def test_triggered_when_multiplier_above_1(self):
        """Multiplier > 1.0 should produce an OVERKILL_BONUS event."""
        event = AchievementService.check_overkill(
            user_elo=1200, problem_rating=1400, multiplier=1.2,
        )
        assert event is not None
        assert event.type == AchievementType.OVERKILL_BONUS
        assert event.icon == "zap"

    def test_not_triggered_when_multiplier_is_1(self):
        """Multiplier == 1.0 should produce no event."""
        event = AchievementService.check_overkill(
            user_elo=1200, problem_rating=1200, multiplier=1.0,
        )
        assert event is None

    def test_not_triggered_when_multiplier_below_1(self):
        """Multiplier < 1.0 should produce no event."""
        event = AchievementService.check_overkill(
            user_elo=1200, problem_rating=1200, multiplier=0.9,
        )
        assert event is None

    def test_description_contains_elo_and_rating(self):
        """Event description should mention both Elo and problem rating."""
        event = AchievementService.check_overkill(
            user_elo=1000, problem_rating=1500, multiplier=2.0,
        )
        assert event is not None
        assert "1000" in event.description
        assert "1500" in event.description

    def test_tier_label_for_1_2_multiplier(self):
        """x1.2 multiplier should show 'x1.2' in description."""
        event = AchievementService.check_overkill(
            user_elo=1200, problem_rating=1400, multiplier=1.2,
        )
        assert event is not None
        assert "x1.2" in event.description

    def test_tier_label_for_1_5_multiplier(self):
        """x1.5 multiplier should show 'x1.5' in description."""
        event = AchievementService.check_overkill(
            user_elo=1200, problem_rating=1500, multiplier=1.5,
        )
        assert event is not None
        assert "x1.5" in event.description

    def test_tier_label_for_2_0_multiplier(self):
        """x2.0 multiplier should show 'x2.0' in description."""
        event = AchievementService.check_overkill(
            user_elo=1200, problem_rating=1600, multiplier=2.0,
        )
        assert event is not None
        assert "x2.0" in event.description

    def test_boundary_multiplier_exactly_1(self):
        """Multiplier exactly 1.0 should not trigger."""
        event = AchievementService.check_overkill(
            user_elo=1200, problem_rating=1200, multiplier=1.0,
        )
        assert event is None

    def test_title_is_chinese(self):
        """Title should be in Chinese as per project locale."""
        event = AchievementService.check_overkill(
            user_elo=1200, problem_rating=1400, multiplier=1.2,
        )
        assert event is not None
        assert len(event.title) > 0


# ---------------------------------------------------------------------------
# Contest win achievement tests
# ---------------------------------------------------------------------------


class TestCheckContestWin:
    """Verify contest win achievement detection."""

    def test_triggered_at_rank_1_with_multiple_participants(self):
        """Rank 1 among many participants should produce a CONTEST_WIN event."""
        event = AchievementService.check_contest_win(rank=1, total_participants=51)
        assert event is not None
        assert event.type == AchievementType.CONTEST_WIN
        assert event.icon == "trophy"

    def test_not_triggered_at_rank_2(self):
        """Rank 2 should not produce a contest win event."""
        event = AchievementService.check_contest_win(rank=2, total_participants=51)
        assert event is None

    def test_not_triggered_at_rank_3(self):
        """Rank 3 should not produce a contest win event."""
        event = AchievementService.check_contest_win(rank=3, total_participants=51)
        assert event is None

    def test_not_triggered_with_single_participant(self):
        """Rank 1 with only 1 participant should not trigger."""
        event = AchievementService.check_contest_win(rank=1, total_participants=1)
        assert event is None

    def test_not_triggered_with_zero_participants(self):
        """Rank 1 with 0 participants should not trigger."""
        event = AchievementService.check_contest_win(rank=1, total_participants=0)
        assert event is None

    def test_description_contains_participant_count(self):
        """Event description should mention the total participants."""
        event = AchievementService.check_contest_win(rank=1, total_participants=50)
        assert event is not None
        assert "50" in event.description


# ---------------------------------------------------------------------------
# Personal best PP achievement tests
# ---------------------------------------------------------------------------


class TestCheckPersonalBestPP:
    """Verify personal best PP achievement detection."""

    def test_triggered_when_pp_increases_from_positive(self):
        """New PP > old PP and old PP > 0 should trigger."""
        event = AchievementService.check_personal_best_pp(new_pp=50.0, old_pp=30.0)
        assert event is not None
        assert event.type == AchievementType.PERSONAL_BEST_PP
        assert event.icon == "star"

    def test_not_triggered_when_old_pp_is_zero(self):
        """Old PP == 0 should not trigger (first-time PP, not a record)."""
        event = AchievementService.check_personal_best_pp(new_pp=10.0, old_pp=0.0)
        assert event is None

    def test_not_triggered_when_pp_decreases(self):
        """New PP < old PP should not trigger."""
        event = AchievementService.check_personal_best_pp(new_pp=20.0, old_pp=30.0)
        assert event is None

    def test_not_triggered_when_pp_unchanged(self):
        """New PP == old PP should not trigger."""
        event = AchievementService.check_personal_best_pp(new_pp=30.0, old_pp=30.0)
        assert event is None

    def test_not_triggered_when_old_pp_is_negative(self):
        """Negative old PP should not trigger."""
        event = AchievementService.check_personal_best_pp(new_pp=10.0, old_pp=-5.0)
        assert event is None

    def test_description_contains_pp_values(self):
        """Event description should include both old and new PP."""
        event = AchievementService.check_personal_best_pp(new_pp=100.5, old_pp=80.2)
        assert event is not None
        assert "80.2" in event.description
        assert "100.5" in event.description

    def test_triggered_with_small_increase(self):
        """Even a small PP increase should trigger if old > 0."""
        event = AchievementService.check_personal_best_pp(new_pp=30.1, old_pp=30.0)
        assert event is not None


# ---------------------------------------------------------------------------
# to_dict serialization tests
# ---------------------------------------------------------------------------


class TestToDict:
    """Verify AchievementEvent.to_dict() serialization."""

    def test_to_dict_has_all_fields(self):
        """to_dict() should include type, title, description, icon."""
        event = AchievementService.check_overkill(
            user_elo=1200, problem_rating=1500, multiplier=1.5,
        )
        assert event is not None
        d = event.to_dict()
        assert "type" in d
        assert "title" in d
        assert "description" in d
        assert "icon" in d

    def test_to_dict_type_is_string(self):
        """The 'type' value should be a plain string (the enum value)."""
        event = AchievementService.check_overkill(
            user_elo=1200, problem_rating=1500, multiplier=1.5,
        )
        assert event is not None
        d = event.to_dict()
        assert d["type"] == "overkill_bonus"
        assert isinstance(d["type"], str)

    def test_to_dict_all_types(self):
        """All achievement types should serialize correctly."""
        overkill = AchievementService.check_overkill(1000, 1500, 2.0)
        contest = AchievementService.check_contest_win(1, 50)
        pp = AchievementService.check_personal_best_pp(100.0, 50.0)

        for event in [overkill, contest, pp]:
            assert event is not None
            d = event.to_dict()
            assert isinstance(d["type"], str)
            assert isinstance(d["title"], str)
            assert isinstance(d["description"], str)
            assert isinstance(d["icon"], str)


# ---------------------------------------------------------------------------
# Integration-style tests: verifying the full check -> to_dict -> schema pipeline
# ---------------------------------------------------------------------------


class TestAchievementSchemaPipeline:
    """Verify that achievement events can flow through the Pydantic schema."""

    def test_overkill_event_passes_through_schema(self):
        """An overkill event dict should be accepted by AchievementEventSchema."""
        from app.schemas.pve_challenge import AchievementEventSchema

        event = AchievementService.check_overkill(1200, 1500, 1.5)
        assert event is not None
        schema = AchievementEventSchema(**event.to_dict())
        assert schema.type == "overkill_bonus"
        assert schema.title == event.title
        assert schema.icon == "zap"

    def test_contest_win_event_passes_through_schema(self):
        """A contest win event dict should be accepted by AchievementEventSchema."""
        from app.schemas.pve_challenge import AchievementEventSchema

        event = AchievementService.check_contest_win(1, 51)
        assert event is not None
        schema = AchievementEventSchema(**event.to_dict())
        assert schema.type == "contest_win"
        assert schema.icon == "trophy"

    def test_pp_event_passes_through_schema(self):
        """A personal best PP event dict should be accepted by AchievementEventSchema."""
        from app.schemas.pve_challenge import AchievementEventSchema

        event = AchievementService.check_personal_best_pp(100.0, 50.0)
        assert event is not None
        schema = AchievementEventSchema(**event.to_dict())
        assert schema.type == "personal_best_pp"
        assert schema.icon == "star"
