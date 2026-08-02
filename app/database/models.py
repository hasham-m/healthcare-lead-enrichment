"""SQLAlchemy models for scraped therapist profiles."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Identity,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all application database models."""


class PsychologyToday(Base):
    """A therapist profile collected from Psychology Today."""

    __tablename__ = "psychology_today"

    id: Mapped[int] = mapped_column(Integer, Identity(), nullable=False, unique=True)
    directory: Mapped[str] = mapped_column(String(100), nullable=False)
    source_profile_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_url: Mapped[str | None] = mapped_column(Text)
    source_state: Mapped[str | None] = mapped_column(String(100))
    source_city: Mapped[str | None] = mapped_column(String(150))
    all_specialties: Mapped[str | None] = mapped_column(Text)
    best_specialty: Mapped[str | None] = mapped_column(Text)
    client_focus: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(Text)
    phone_number: Mapped[str | None] = mapped_column(String(50))
    best_email: Mapped[str | None] = mapped_column(String(320))
    best_email_score: Mapped[float | None] = mapped_column(Float)
    all_emails: Mapped[str | None] = mapped_column(Text)
    website_best_specialty: Mapped[str | None] = mapped_column(Text)
    website_all_specialties: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(150))
    category_source: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ScrapeRun(Base):
    """Progress and outcome information for one directory scraping run."""

    __tablename__ = "scrape_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'pending')",
            name="scrape_runs_status_check",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    directory: Mapped[str] = mapped_column(String(100), nullable=False)
    start_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_profile: Mapped[int] = mapped_column(Integer, nullable=False)
    max_pages: Mapped[int] = mapped_column(Integer, nullable=False)
    pages_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unique_profile: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_completed_page_url: Mapped[str | None] = mapped_column(Text)
    next_page_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
