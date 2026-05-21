"""Problem statement API routes.

Endpoints:
  GET  /problem/{problem_id}/statement  -- get (or scrape) a problem statement
  GET  /problem/statements/check         -- batch cache-check
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import ServiceUnavailableException
from app.core.response import success_response
from app.schemas.problem import CacheCheckResponse, ProblemStatementResponse
from app.services.problem_scraper_service import build_cf_url, parse_problem_id, scraper_service

logger = logging.getLogger("code_arena.problem_api")

router = APIRouter(prefix="/problem", tags=["Problem"])


@router.get("/{problem_id}/statement")
async def get_problem_statement(
    problem_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return a problem statement from cache or scrape it on demand.

    On scrape failure, returns HTTP 503 with a ``fallback_url`` so the
    client can redirect the user to the original CF page.
    """
    try:
        contest_id, index = parse_problem_id(problem_id)
    except ValueError as exc:
        from app.core.exceptions import BadRequestException

        raise BadRequestException(message=str(exc)) from exc

    fallback_url = build_cf_url(contest_id, index)

    try:
        row = await scraper_service.get_or_scrape(db, problem_id)
    except Exception as exc:
        logger.error("Scrape failed for %s: %s", problem_id, exc)
        raise ServiceUnavailableException(
            message=f"Failed to scrape problem {problem_id}",
            detail=str(exc),
            data={"fallback_url": fallback_url},
        ) from exc

    response = ProblemStatementResponse(
        problem_id=row.problem_id,
        contest_id=row.contest_id,
        index=row.index,
        title=row.title,
        time_limit=row.time_limit,
        memory_limit=row.memory_limit,
        body_html=row.body_html,
        input_spec_html=row.input_spec_html,
        output_spec_html=row.output_spec_html,
        samples=row.samples if isinstance(row.samples, list) else [],
        note_html=row.note_html,
        full_html=row.full_html,
        scraped_at=row.scraped_at,
        cached=True,
        fallback_url=fallback_url,
    )
    return success_response(
        data=response.model_dump(mode="json"),
        message="Problem statement retrieved",
    )


@router.get("/statements/check")
async def check_cached_statements(
    problem_ids: str = Query(..., description="Comma-separated problem IDs, e.g. '1A,1B,1C'"),
    db: AsyncSession = Depends(get_db),
):
    """Check which problem statements are already cached.

    Returns ``{"cached": [...], "not_cached": [...]}``.
    """
    ids = [pid.strip() for pid in problem_ids.split(",") if pid.strip()]
    if not ids:
        from app.core.exceptions import BadRequestException

        raise BadRequestException(message="problem_ids must not be empty")

    result = await scraper_service.check_cached(db, ids)
    check = CacheCheckResponse(**result)
    return success_response(
        data=check.model_dump(mode="json"),
        message="Cache check completed",
    )
