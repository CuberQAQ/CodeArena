from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    cf_handle: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    cf_handle_verified: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    cf_verification_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    elo: Mapped[int] = mapped_column(Integer, server_default="1200", nullable=False, index=True)
    pp: Mapped[float] = mapped_column(Float, server_default="0", nullable=False, index=True)
    tokens: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    daily_tokens_earned: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    daily_tokens_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)

    # Relationships
    elo_history = relationship("EloHistory", back_populates="user", cascade="all, delete-orphan")
    pp_records = relationship("PPRecord", back_populates="user", cascade="all, delete-orphan")
    challenge_sessions_as_challenger = relationship(
        "ChallengeSession",
        back_populates="challenger",
        cascade="all, delete-orphan",
        foreign_keys="ChallengeSession.challenger_id",
    )
    challenge_sessions_as_opponent = relationship(
        "ChallengeSession",
        back_populates="opponent",
        cascade="all, delete-orphan",
        foreign_keys="ChallengeSession.opponent_id",
    )
    training_sessions = relationship("TrainingSession", back_populates="user", cascade="all, delete-orphan")
    contest_sessions = relationship("ContestSession", back_populates="user", cascade="all, delete-orphan")
    token_transactions = relationship("TokenTransaction", back_populates="user", cascade="all, delete-orphan")
    hint_purchases = relationship("HintPurchase", back_populates="user", cascade="all, delete-orphan")


    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username})>"
