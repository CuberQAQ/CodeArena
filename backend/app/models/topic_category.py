from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class TopicCategory(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "topic_categories"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cf_tags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)

    def __repr__(self) -> str:
        return f"<TopicCategory(id={self.id}, name={self.name})>"
