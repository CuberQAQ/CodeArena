"""Time factor prediction API routes.

Provides a single endpoint that returns predicted Elo change estimates
at various solve-time milestones, used by the frontend SolvingTimeline
component to display a real-time Elo prediction timeline during problem
solving.

Mounts one endpoint under ``/api/v1/time-factor-prediction``:
  GET /time-factor-prediction  -- get predicted Elo change at various time points
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.services.cf_api_service import CFApiService
from app.services.time_factor_service import (
    SECONDS_PER_MINUTE,
    TimeFactorService,
)

router = APIRouter(prefix="/time-factor-prediction", tags=["Time Factor"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fixed time points (minutes) at which to sample predictions
PREDICTION_MINUTES: list[int] = [5, 10, 15, 20, 30, 45, 60]

# Approximate K-value used for Elo change estimation.
# This is a rough estimate (actual K depends on game mode), used only to
# show relative trends ("faster = more Elo") rather than precise values.
APPROX_K: float = 30.0

# Approximate base Elo change for solving at expected time (time_factor = 1.0).
# In practice: Elo_change = K * (S - expected_score) where S depends on result.
# For a win (S=1.0) and roughly even match: base_change ≈ K/2 ≈ 16.
# We use a simplified formula: base_change * time_factor.
APPROX_BASE_CHANGE: float = 16.0

# ---------------------------------------------------------------------------
# CF API singleton
# ---------------------------------------------------------------------------

_cf_service: CFApiService | None = None


def _get_cf_service() -> CFApiService:
    global _cf_service
    if _cf_service is None:
        _cf_service = CFApiService()
    return _cf_service


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TimePoint(BaseModel):
    """A single prediction point on the timeline."""

    minutes: int = Field(..., description="Time in minutes")
    time_factor: float = Field(..., description="Time factor at this duration")
    elo_change_estimate: int = Field(..., description="Estimated Elo change (approximate)")


class PredictionResponse(BaseModel):
    """Full prediction response."""

    expected_time_minutes: float = Field(..., description="Expected solve time in minutes")
    time_points: list[TimePoint] = Field(..., description="Predicted Elo change at each time milestone")


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("")
async def get_time_factor_prediction(
    problem_id: str = Query(..., description="Problem ID, e.g. '1920A'"),
    problem_rating: int = Query(..., ge=800, le=4000, description="Problem difficulty rating"),
    user_elo: int = Query(..., ge=0, le=5000, description="User's current Elo rating"),
    current_user: User = Depends(get_current_user),
):
    """Return predicted Elo change estimates at various solve-time milestones.

    The ``elo_change_estimate`` values are approximate (using a fixed K and S=1.0)
    and are intended only to show the relative trend: faster solve = more Elo gain.
    """
    cf_service = _get_cf_service()

    # Calculate expected time (seconds -> minutes)
    expected_time_seconds = await TimeFactorService.calculate_expected_time(
        cf_service,
        problem_id,
        problem_rating,
        user_elo,
    )
    expected_time_minutes = expected_time_seconds / SECONDS_PER_MINUTE

    # Generate prediction points
    time_points: list[TimePoint] = []
    for minutes in PREDICTION_MINUTES:
        effective_seconds = minutes * SECONDS_PER_MINUTE

        # Use the same time_factor calculation as the actual settlement
        time_factor = TimeFactorService.calculate_time_factor(
            effective_seconds,
            expected_time_seconds,
            s_value=1.0,
        )

        # Elo change estimate: base * time_factor (approximate, for display only)
        elo_estimate = round(APPROX_BASE_CHANGE * time_factor)

        time_points.append(
            TimePoint(
                minutes=minutes,
                time_factor=round(time_factor, 2),
                elo_change_estimate=elo_estimate,
            )
        )

    return success_response(
        data=PredictionResponse(
            expected_time_minutes=round(expected_time_minutes, 1),
            time_points=time_points,
        ).model_dump(),
        message="Time factor prediction calculated",
    )
