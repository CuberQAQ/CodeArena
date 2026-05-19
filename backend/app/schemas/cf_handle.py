"""Pydantic schemas for CF Handle binding and verification."""

from pydantic import BaseModel, Field


class BindCFHandleRequest(BaseModel):
    """Request body for binding a CF Handle."""

    cf_handle: str = Field(
        min_length=1,
        max_length=100,
        description="Codeforces handle to bind",
    )


class VerifyCFHandleRequest(BaseModel):
    """Request body for verifying a CF Handle via bio check."""

    cf_handle: str = Field(
        min_length=1,
        max_length=100,
        description="Codeforces handle to verify",
    )
    verification_code: str = Field(
        min_length=8,
        max_length=8,
        description="8-character verification code",
    )


class CFUserInfo(BaseModel):
    """CF user info returned from binding and lookup."""

    handle: str
    rating: int | None = None
    max_rating: int | None = None
    avatar: str | None = None
    rank: str | None = None
    max_rank: str | None = None
    title_photo: str | None = None

    model_config = {"from_attributes": True}
