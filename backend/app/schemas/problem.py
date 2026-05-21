"""Pydantic schemas for problem statement API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SampleTest(BaseModel):
    """A single sample test case."""

    input: str
    output: str


class ProblemStatementResponse(BaseModel):
    """Full problem statement returned by the API."""

    problem_id: str
    contest_id: int
    index: str
    title: str
    time_limit: str | None = None
    memory_limit: str | None = None
    body_html: str
    input_spec_html: str | None = None
    output_spec_html: str | None = None
    samples: list[SampleTest] = []
    note_html: str | None = None
    full_html: str
    scraped_at: datetime
    cached: bool = True
    fallback_url: str

    model_config = {"from_attributes": True}


class CacheCheckResponse(BaseModel):
    """Response for the batch cache-check endpoint."""

    cached: list[str] = Field(default_factory=list, description="Problem IDs already cached")
    not_cached: list[str] = Field(default_factory=list, description="Problem IDs not yet cached")
