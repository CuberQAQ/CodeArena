"""Global ranking API routes.

Mounts endpoints under ``/api/v1/ranking/``:
  GET  /global  -- mixed ranking of CodeArena + CF users
  GET  /arena   -- CodeArena-only ranking
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.models.cf_sample_user import CFSampleUser
from app.models.user import User
from app.services.cf_ranking_service import (
    build_cdf,
    get_latest_pipeline_metadata,
    pp_to_rating,
)

router = APIRouter(prefix="/ranking", tags=["Ranking"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_PAGE = 1
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200


def _paginate(items: list[dict], page: int, page_size: int) -> dict:
    """Apply offset-based pagination to a pre-sorted list of items."""
    total = len(items)
    offset = (page - 1) * page_size
    page_items = items[offset : offset + page_size]
    return {
        "items": page_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/global")
async def get_global_ranking(
    country: str | None = Query(default=None, description="ISO 3166-1 alpha-2 country code filter"),
    page: int = Query(default=_DEFAULT_PAGE, ge=1, description="Page number"),
    page_size: int = Query(default=_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    """Mixed ranking combining CodeArena users (verified PP) with CF sample users (estimated PP).

    CA users are marked ``verified: true`` and take priority on equal PP.
    CF sample users are marked ``verified: false``.

    When pipeline metadata is available, each item includes an
    ``estimated_percentile`` (0-100) calibrated against the full CF user base
    via the rating histogram CDF.  The ``calibrated`` flag indicates whether
    this estimation is available.
    """
    # --- Fetch pipeline metadata for CDF estimation ---
    metadata = await get_latest_pipeline_metadata(db)
    calibrated = metadata is not None and metadata.rating_histogram is not None
    cdf_fn = None
    if calibrated and metadata is not None:
        cdf_fn = build_cdf(metadata.rating_histogram, metadata.total_rated_users)

    # --- Fetch CodeArena active users with PP > 0 ---
    ca_result = await db.execute(
        select(User.username, User.pp, User.elo, User.cf_handle, User.cf_handle_verified).where(
            User.is_active == True,  # noqa: E712 — SQLAlchemy filter
            User.pp > 0,
        )
    )
    ca_rows = ca_result.all()

    # Build lookup for CA user country via their verified CF handle
    ca_cf_handles: set[str] = set()
    for _username, _pp, _elo, cf_handle, cf_handle_verified in ca_rows:
        if cf_handle and cf_handle_verified:
            ca_cf_handles.add(cf_handle)

    # --- Fetch CF sample users from the latest batch ---
    max_batch_result = await db.execute(
        select(CFSampleUser.sample_batch).order_by(CFSampleUser.sample_batch.desc()).limit(1)
    )
    max_batch_row = max_batch_result.first()
    if max_batch_row is None:
        cf_rows = []
    else:
        max_batch = max_batch_row[0]
        cf_result = await db.execute(
            select(
                CFSampleUser.cf_handle,
                CFSampleUser.cf_rating,
                CFSampleUser.estimated_pp,
                CFSampleUser.country,
            ).where(
                CFSampleUser.sample_batch == max_batch,
                CFSampleUser.estimated_pp.isnot(None),
                CFSampleUser.estimated_pp > 0,
            )
        )
        cf_rows = cf_result.all()

    # Build a country lookup from CF sample data for CA users with verified CF handles
    cf_country_lookup: dict[str, str | None] = {}
    for cf_handle, _rating, _est_pp, cf_country in cf_rows:
        cf_country_lookup[cf_handle] = cf_country

    # --- Assemble combined list ---
    # Track CF handles that belong to CA users to avoid duplicates
    ca_cf_handle_set: set[str] = set()
    combined: list[dict] = []

    for username, pp, _elo, cf_handle, cf_handle_verified in ca_rows:
        # Determine country for CA user
        ca_country = None
        if cf_handle and cf_handle_verified:
            ca_country = cf_country_lookup.get(cf_handle)
            ca_cf_handle_set.add(cf_handle)

        # Estimate percentile via PP -> rating -> CDF when metadata available
        estimated_percentile = None
        if cdf_fn is not None and metadata is not None and metadata.regression_coefficients and pp > 0:
            rating = pp_to_rating(pp, metadata.regression_coefficients)
            if rating is not None:
                estimated_percentile = round(cdf_fn(rating) * 100, 1)

        combined.append(
            {
                "name": username,
                "pp": round(pp, 2),
                "country": ca_country,
                "verified": True,
                "estimated_percentile": estimated_percentile,
            }
        )

    for cf_handle, cf_rating, estimated_pp, cf_country in cf_rows:
        # Skip CF users who are also CA users (CA entry takes precedence)
        if cf_handle in ca_cf_handle_set:
            continue

        # CF users have a direct rating, so CDF is straightforward
        estimated_percentile = None
        if cdf_fn is not None and cf_rating > 0:
            estimated_percentile = round(cdf_fn(cf_rating) * 100, 1)

        combined.append(
            {
                "name": cf_handle,
                "pp": round(estimated_pp, 2),
                "country": cf_country,
                "verified": False,
                "cf_rating": cf_rating,
                "estimated_percentile": estimated_percentile,
            }
        )

    # --- Sort ---
    # PP descending, CA users (verified=True) first on tie
    combined.sort(key=lambda x: (-x["pp"], not x["verified"]))

    # --- Country filter ---
    if country is not None:
        combined = [item for item in combined if item.get("country") == country]

    result = _paginate(combined, page, page_size)
    result["calibrated"] = calibrated
    return success_response(data=result, message="Global ranking retrieved")


@router.get("/arena")
async def get_arena_ranking(
    sort_by: str = Query(default="pp", description="Sort field (pp or elo)"),
    country: str | None = Query(default=None, description="ISO 3166-1 alpha-2 country code filter"),
    page: int = Query(default=_DEFAULT_PAGE, ge=1, description="Page number"),
    page_size: int = Query(default=_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    """CodeArena-only ranking using real PP/Elo values.

    Only active users with PP > 0 are included.
    """
    # Fetch CA active users
    ca_result = await db.execute(
        select(User.username, User.pp, User.elo, User.cf_handle, User.cf_handle_verified).where(
            User.is_active == True,  # noqa: E712
            User.pp > 0,
        )
    )
    ca_rows = ca_result.all()

    if not ca_rows:
        result = _paginate([], page, page_size)
        return success_response(data=result, message="Arena ranking retrieved")

    # Fetch CF sample country data for country resolution
    ca_cf_handles: set[str] = set()
    for _username, _pp, _elo, cf_handle, cf_handle_verified in ca_rows:
        if cf_handle and cf_handle_verified:
            ca_cf_handles.add(cf_handle)

    cf_country_lookup: dict[str, str | None] = {}
    if ca_cf_handles:
        cf_country_result = await db.execute(
            select(CFSampleUser.cf_handle, CFSampleUser.country).where(
                CFSampleUser.cf_handle.in_(ca_cf_handles),
            )
        )
        for handle, c in cf_country_result.all():
            if c and handle not in cf_country_lookup:
                cf_country_lookup[handle] = c

    # Assemble list
    items: list[dict] = []
    for username, pp, elo, cf_handle, cf_handle_verified in ca_rows:
        ca_country = None
        if cf_handle and cf_handle_verified:
            ca_country = cf_country_lookup.get(cf_handle)

        items.append(
            {
                "name": username,
                "pp": round(pp, 2),
                "elo": elo,
                "country": ca_country,
                "verified": True,
            }
        )

    # --- Sort ---
    if sort_by == "elo":
        items.sort(key=lambda x: -x["elo"])
    else:
        # Default: sort by PP descending
        items.sort(key=lambda x: -x["pp"])

    # --- Country filter ---
    if country is not None:
        items = [item for item in items if item.get("country") == country]

    result = _paginate(items, page, page_size)
    return success_response(data=result, message="Arena ranking retrieved")
