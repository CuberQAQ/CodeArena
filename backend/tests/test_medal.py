"""Tests for the medal system: tier mapping, overall/skill medals, contest awards, stats, settings.

Uses lightweight SQLite-compatible test models and the same patching strategy as
test_contest.py.  MedalService is mostly pure-logic (rating-to-medal mapping),
with only award/stats methods hitting the DB.
"""

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import Boolean, DateTime, Float, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.services.medal_service import MEDAL_TIERS, MedalService

# ---------------------------------------------------------------------------
# Lightweight SQLite-compatible test models
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _TestContestMedal(_TestBase):
    __tablename__ = "contest_medals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    contest_session_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    medal_level: Mapped[str] = mapped_column(String(30), nullable=False)
    medal_type: Mapped[str] = mapped_column(String(10), nullable=False)
    pr_value: Mapped[int] = mapped_column(Integer, nullable=False)
    awarded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestUserSettings(_TestBase):
    __tablename__ = "user_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, unique=True)
    display_mode: Mapped[str] = mapped_column(String(20), default="medal", nullable=False)
    avatar_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestUserTagElo(_TestBase):
    __tablename__ = "user_tag_elo"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    tag: Mapped[str] = mapped_column(String(100), nullable=False)
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)


class _TestUser(_TestBase):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def db(async_engine):
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    from app.services import medal_service as medal_svc_module

    async with session_factory() as session:
        with (
            patch.object(medal_svc_module, "ContestMedal", _TestContestMedal),
            patch.object(medal_svc_module, "UserTagElo", _TestUserTagElo),
        ):
            yield session


def _make_user(**kwargs) -> _TestUser:
    """Create a test user with sensible defaults."""
    defaults = {
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "email": f"{uuid.uuid4().hex[:8]}@test.com",
        "password_hash": "hash",
        "elo": 1200,
        "tokens": 0,
    }
    defaults.update(kwargs)
    return _TestUser(**defaults)


# ===========================================================================
# Test: Medal tier mapping (FR-10.1)
# ===========================================================================


class TestMedalTierMapping:
    """Verify MEDAL_TIERS constant and _rating_to_medal mapping."""

    def test_medal_tiers_has_four_levels(self):
        """Four XCPC tiers defined."""
        levels = [t["level"] for t in MEDAL_TIERS]
        assert levels == ["world_finals", "ec_final", "regional", "provincial"]

    def test_world_finals_gold_threshold(self):
        """World Finals gold requires rating >= 2800."""
        assert MEDAL_TIERS[0]["gold"] == 2800
        assert MEDAL_TIERS[0]["silver"] == 2600
        assert MEDAL_TIERS[0]["bronze"] == 2400

    def test_provincial_bronze_threshold(self):
        """Provincial bronze requires rating >= 1200."""
        assert MEDAL_TIERS[3]["bronze"] == 1200


# ===========================================================================
# Test: Overall medal calculation (FR-10.2)
# ===========================================================================


class TestOverallMedal:
    """Test calculate_overall_medal for various Elo values."""

    def test_world_finals_gold(self):
        result = MedalService.calculate_overall_medal(2800)
        assert result == {"level": "world_finals", "type": "gold"}

    def test_ec_final_gold_2700(self):
        """D-31: 2700 >= 2600 → EC Final Gold."""
        result = MedalService.calculate_overall_medal(2700)
        assert result == {"level": "ec_final", "type": "gold"}

    def test_regional_gold_2500(self):
        """D-31: 2500 >= 2200 → Regional Gold."""
        result = MedalService.calculate_overall_medal(2500)
        assert result == {"level": "regional", "type": "gold"}

    def test_ec_final_gold_2650(self):
        """D-31: 2650 >= 2600 → EC Final Gold."""
        result = MedalService.calculate_overall_medal(2650)
        assert result == {"level": "ec_final", "type": "gold"}

    def test_regional_gold_2350(self):
        # 2350: no WF medal (bronze requires 2400), regional gold at 2200
        result = MedalService.calculate_overall_medal(2350)
        assert result == {"level": "regional", "type": "gold"}

    def test_regional_gold_exact(self):
        """PR 2200 -> regional gold (per task test expectation)."""
        result = MedalService.calculate_overall_medal(2200)
        assert result == {"level": "regional", "type": "gold"}

    def test_provincial_gold_2100(self):
        """D-31: 2100 >= 1600 → Provincial Gold."""
        result = MedalService.calculate_overall_medal(2100)
        assert result == {"level": "provincial", "type": "gold"}

    def test_provincial_gold_2000(self):
        """D-31: 2000 >= 1600 → Provincial Gold."""
        result = MedalService.calculate_overall_medal(2000)
        assert result == {"level": "provincial", "type": "gold"}

    def test_provincial_gold_1800(self):
        """D-31: 1800 >= 1600 → Provincial Gold."""
        result = MedalService.calculate_overall_medal(1800)
        assert result == {"level": "provincial", "type": "gold"}

    def test_provincial_gold(self):
        result = MedalService.calculate_overall_medal(1600)
        assert result == {"level": "provincial", "type": "gold"}

    def test_provincial_silver(self):
        """Elo 1500 -> provincial silver."""
        result = MedalService.calculate_overall_medal(1500)
        assert result == {"level": "provincial", "type": "silver"}

    def test_provincial_bronze(self):
        result = MedalService.calculate_overall_medal(1200)
        assert result == {"level": "provincial", "type": "bronze"}

    def test_unranked(self):
        """Elo 1100 -> unranked."""
        result = MedalService.calculate_overall_medal(1100)
        assert result == {"level": "unranked"}

    def test_unranked_zero(self):
        result = MedalService.calculate_overall_medal(0)
        assert result == {"level": "unranked"}

    def test_exact_threshold_boundary(self):
        """Exact boundary values should meet the threshold."""
        # Exactly 2800 -> world_finals gold
        assert MedalService.calculate_overall_medal(2800)["type"] == "gold"
        # Exactly 2799 -> ec_final gold (D-31: 2799 >= 2600)
        assert MedalService.calculate_overall_medal(2799) == {"level": "ec_final", "type": "gold"}
        # Exactly 2599 -> regional gold (D-31: 2599 >= 2200)
        assert MedalService.calculate_overall_medal(2599) == {"level": "regional", "type": "gold"}
        # Exactly 1199 -> unranked
        assert MedalService.calculate_overall_medal(1199) == {"level": "unranked"}


# ===========================================================================
# Test: Skill medal calculation (FR-10.3)
# ===========================================================================


class TestSkillMedal:
    """Test calculate_skill_medal -- same logic as overall but for M-Elo."""

    def test_dp_provincial_gold(self):
        """D-31: M-Elo(DP)=1800 >= 1600 → Provincial Gold."""
        result = MedalService.calculate_skill_medal(1800)
        assert result == {"level": "provincial", "type": "gold"}

    def test_dp_world_finals_gold(self):
        result = MedalService.calculate_skill_medal(2900)
        assert result == {"level": "world_finals", "type": "gold"}

    def test_dp_unranked(self):
        result = MedalService.calculate_skill_medal(1000)
        assert result == {"level": "unranked"}

    def test_skill_medal_same_mapping_as_overall(self):
        """Skill medal mapping is identical to overall at same rating."""
        for rating in [1000, 1200, 1500, 1800, 2000, 2200, 2500, 2800, 3000]:
            assert MedalService.calculate_skill_medal(rating) == MedalService.calculate_overall_medal(rating)


# ===========================================================================
# Test: Contest medal awarding (FR-10.4)
# ===========================================================================


class TestContestMedalAwarding:
    """Test award_contest_medal for PR-based medal awarding."""

    @pytest.mark.asyncio
    async def test_pr_2200_regional_gold(self, db):
        """PR 2200 -> regional gold (per task test expectation)."""
        user_id = uuid.uuid4()
        contest_id = uuid.uuid4()

        medal = await MedalService.award_contest_medal(
            db=db,
            user_id=user_id,
            contest_session_id=contest_id,
            pr=2200,
        )

        assert medal is not None
        assert medal.medal_level == "regional"
        assert medal.medal_type == "gold"
        assert medal.pr_value == 2200

    @pytest.mark.asyncio
    async def test_pr_1100_no_medal(self, db):
        """PR 1100 -> no medal (below provincial bronze threshold)."""
        user_id = uuid.uuid4()
        contest_id = uuid.uuid4()

        medal = await MedalService.award_contest_medal(
            db=db,
            user_id=user_id,
            contest_session_id=contest_id,
            pr=1100,
        )

        assert medal is None

    @pytest.mark.asyncio
    async def test_no_duplicate_medal(self, db):
        """Same user + contest should not produce duplicate medals."""
        user_id = uuid.uuid4()
        contest_id = uuid.uuid4()

        medal1 = await MedalService.award_contest_medal(
            db=db,
            user_id=user_id,
            contest_session_id=contest_id,
            pr=2200,
        )
        medal2 = await MedalService.award_contest_medal(
            db=db,
            user_id=user_id,
            contest_session_id=contest_id,
            pr=2200,
        )

        assert medal1 is not None
        assert medal2 is None  # Second call returns None (duplicate blocked)

    @pytest.mark.asyncio
    async def test_different_contests_different_medals(self, db):
        """User can earn medals in different contest sessions."""
        user_id = uuid.uuid4()
        contest1 = uuid.uuid4()
        contest2 = uuid.uuid4()

        medal1 = await MedalService.award_contest_medal(
            db=db,
            user_id=user_id,
            contest_session_id=contest1,
            pr=2200,
        )
        medal2 = await MedalService.award_contest_medal(
            db=db,
            user_id=user_id,
            contest_session_id=contest2,
            pr=1400,
        )

        assert medal1 is not None
        assert medal2 is not None
        # D-31: PR 2200 -> regional gold, PR 1400 -> provincial silver
        assert medal1.medal_level == "regional"
        assert medal1.medal_type == "gold"
        assert medal2.medal_level == "provincial"
        assert medal2.medal_type == "silver"
        assert medal1.contest_session_id != medal2.contest_session_id

    @pytest.mark.asyncio
    async def test_pr_boundary_values(self, db):
        """Test exact PR boundary values."""
        user_id = uuid.uuid4()

        # PR exactly 1200 -> provincial bronze
        medal = await MedalService.award_contest_medal(
            db=db,
            user_id=user_id,
            contest_session_id=uuid.uuid4(),
            pr=1200,
        )
        assert medal is not None
        assert medal.medal_level == "provincial"
        assert medal.medal_type == "bronze"

        # PR exactly 1199 -> no medal
        medal = await MedalService.award_contest_medal(
            db=db,
            user_id=user_id,
            contest_session_id=uuid.uuid4(),
            pr=1199,
        )
        assert medal is None

    @pytest.mark.asyncio
    async def test_pr_medal_independent_of_tier(self, db):
        """Medal is based on PR, not contest tier (beginner/advanced/master)."""
        user_id = uuid.uuid4()

        # PR 2200 -> regional gold (medal based purely on PR value)
        medal = await MedalService.award_contest_medal(
            db=db,
            user_id=user_id,
            contest_session_id=uuid.uuid4(),
            pr=2200,
        )
        assert medal.medal_level == "regional"
        assert medal.medal_type == "gold"


# ===========================================================================
# Test: Medal stats (FR-10.5)
# ===========================================================================


class TestMedalStats:
    """Test get_user_medal_stats for trophy cabinet aggregation."""

    @pytest.mark.asyncio
    async def test_empty_stats(self, db):
        """User with no medals returns empty stats."""
        user_id = uuid.uuid4()
        stats = await MedalService.get_user_medal_stats(db, user_id)
        assert stats == {}

    @pytest.mark.asyncio
    async def test_stats_after_multiple_contests(self, db):
        """Stats correctly aggregate medals across multiple contests."""
        user_id = uuid.uuid4()

        # Award 3 regional gold (PR 2200)
        for _ in range(3):
            await MedalService.award_contest_medal(
                db=db,
                user_id=user_id,
                contest_session_id=uuid.uuid4(),
                pr=2200,
            )
        # D-31: PR 1400 → provincial silver (no longer regional silver)
        await MedalService.award_contest_medal(
            db=db,
            user_id=user_id,
            contest_session_id=uuid.uuid4(),
            pr=1400,
        )
        # Award 2 provincial gold (PR 1600)
        for _ in range(2):
            await MedalService.award_contest_medal(
                db=db,
                user_id=user_id,
                contest_session_id=uuid.uuid4(),
                pr=1600,
            )

        stats = await MedalService.get_user_medal_stats(db, user_id)

        assert stats["regional"]["gold"] == 3
        assert stats["provincial"]["silver"] == 1
        assert stats["provincial"]["gold"] == 2
        assert "silver" not in stats.get("regional", {})

    @pytest.mark.asyncio
    async def test_stats_isolated_per_user(self, db):
        """Medal stats for one user don't include another user's medals."""
        user1 = uuid.uuid4()
        user2 = uuid.uuid4()

        await MedalService.award_contest_medal(
            db=db,
            user_id=user1,
            contest_session_id=uuid.uuid4(),
            pr=2200,
        )
        await MedalService.award_contest_medal(
            db=db,
            user_id=user2,
            contest_session_id=uuid.uuid4(),
            pr=1600,
        )

        stats1 = await MedalService.get_user_medal_stats(db, user1)
        stats2 = await MedalService.get_user_medal_stats(db, user2)

        assert stats1 == {"regional": {"gold": 1}}
        assert stats2 == {"provincial": {"gold": 1}}


# ===========================================================================
# Test: Skill medals for all tags (FR-10.3)
# ===========================================================================


class TestAllSkillMedals:
    """Test get_all_skill_medals for per-tag medal breakdown."""

    @pytest.mark.asyncio
    async def test_no_skills(self, db):
        """User with no tag elos returns empty dict."""
        user_id = uuid.uuid4()
        result = await MedalService.get_all_skill_medals(db, user_id)
        assert result == {}

    @pytest.mark.asyncio
    async def test_multiple_skill_medals(self, db):
        """Each tag's medal is calculated from its M-Elo."""
        user_id = uuid.uuid4()

        # Insert tag elos directly
        dp = _TestUserTagElo(user_id=user_id, tag="dp", elo=1800)
        greedy = _TestUserTagElo(user_id=user_id, tag="greedy", elo=1500)
        math = _TestUserTagElo(user_id=user_id, tag="math", elo=2900)
        db.add_all([dp, greedy, math])
        await db.flush()

        result = await MedalService.get_all_skill_medals(db, user_id)

        # D-31: dp=1800 >= 1600 → Provincial Gold
        assert result["dp"]["level"] == "provincial"
        assert result["dp"]["type"] == "gold"
        assert result["dp"]["melo"] == 1800

        assert result["greedy"]["level"] == "provincial"
        assert result["greedy"]["type"] == "silver"
        assert result["greedy"]["melo"] == 1500

        assert result["math"]["level"] == "world_finals"
        assert result["math"]["type"] == "gold"
        assert result["math"]["melo"] == 2900


# ===========================================================================
# Test: Real-time medal updates (FR-10.2 real-time)
# ===========================================================================


class TestRealTimeMedalUpdate:
    """Verify that medal calculation is purely based on current rating."""

    def test_elo_change_updates_medal(self):
        """When Elo changes, the medal automatically reflects the new value."""
        # Start at provincial silver
        medal = MedalService.calculate_overall_medal(1500)
        assert medal == {"level": "provincial", "type": "silver"}

        # D-31: Elo 2100 >= 1600 → Provincial Gold
        medal = MedalService.calculate_overall_medal(2100)
        assert medal == {"level": "provincial", "type": "gold"}

        # Elo drops to unranked
        medal = MedalService.calculate_overall_medal(1100)
        assert medal == {"level": "unranked"}

    def test_no_caching(self):
        """MedalService.calculate_overall_medal is a pure function, no caching."""
        # Call multiple times with different values -- each returns correctly
        # D-31: 1100→unranked, 1500→provincial silver, 1800→provincial gold, 2100→provincial gold, 2800→WF gold
        results = [MedalService.calculate_overall_medal(r) for r in [1100, 1500, 1800, 2100, 2800]]
        assert results[0]["level"] == "unranked"
        assert results[1]["level"] == "provincial"
        assert results[1]["type"] == "silver"
        assert results[2]["level"] == "provincial"
        assert results[2]["type"] == "gold"
        assert results[3]["level"] == "provincial"
        assert results[3]["type"] == "gold"
        assert results[4]["level"] == "world_finals"


# ===========================================================================
# Test: User settings (display_mode)
# ===========================================================================


class TestUserSettings:
    """Test UserSettings model and update logic."""

    @pytest.mark.asyncio
    async def test_create_default_settings(self, db):
        """Default settings have display_mode='medal'."""
        user_id = uuid.uuid4()
        settings = _TestUserSettings(user_id=user_id, display_mode="medal")
        db.add(settings)
        await db.flush()

        assert settings.display_mode == "medal"
        assert settings.avatar_path is None

    @pytest.mark.asyncio
    async def test_update_display_mode(self, db):
        """Display mode can be changed to cf_tier."""
        user_id = uuid.uuid4()
        settings = _TestUserSettings(user_id=user_id, display_mode="medal")
        db.add(settings)
        await db.flush()

        # Simulate update
        settings.display_mode = "cf_tier"
        await db.flush()

        # Verify
        from sqlalchemy import select

        result = await db.execute(select(_TestUserSettings).where(_TestUserSettings.user_id == user_id))
        fetched = result.scalar_one()
        assert fetched.display_mode == "cf_tier"
