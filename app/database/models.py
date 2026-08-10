"""SQLAlchemy models for scraped therapist profiles."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
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
    client_focus_primary: Mapped[str | None] = mapped_column(Text)
    client_focus_secondary: Mapped[str | None] = mapped_column(Text)
    insurance_details: Mapped[str | None] = mapped_column(Text)
    payment_category: Mapped[str | None] = mapped_column(Text)
    fee_raw: Mapped[str | None] = mapped_column(Text)
    fee_clean: Mapped[str | None] = mapped_column(Text)
    availability_status: Mapped[str | None] = mapped_column(Text)
    number_of_cities_served: Mapped[int | None] = mapped_column(Integer)
    service_area_cities: Mapped[str | None] = mapped_column(Text)
    evidence_snippets: Mapped[str | None] = mapped_column(Text)
    category_score: Mapped[float | None] = mapped_column(Float)
    category_evidence: Mapped[str | None] = mapped_column(Text)
    all_pages_text: Mapped[str | None] = mapped_column(Text)
    profile_scrape_status: Mapped[str | None] = mapped_column(String(30))
    profile_scrape_attempts: Mapped[int | None] = mapped_column(Integer)
    profile_scrape_last_error: Mapped[str | None] = mapped_column(Text)
    profile_scraped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    website_scrape_status: Mapped[str | None] = mapped_column(String(30))
    website_scrape_attempts: Mapped[int | None] = mapped_column(Integer)
    website_scrape_last_error: Mapped[str | None] = mapped_column(Text)
    website_scraped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    first_name: Mapped[str | None] = mapped_column(String(150))
    last_name: Mapped[str | None] = mapped_column(String(150))
    profile_is_processing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    website_is_processing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    website_resolution_status: Mapped[str | None] = mapped_column(String(30))
    website_resolution_attempts: Mapped[int | None] = mapped_column(Integer)
    website_resolution_last_error: Mapped[str | None] = mapped_column(Text)
    website_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    pt_website_redirect: Mapped[str | None] = mapped_column(Text)


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


class ProxyPool(Base):
    """Proxy records and their current leasing state."""

    __tablename__ = "proxy_pool"
    __table_args__ = (
        CheckConstraint(
            "times_used >= 0",
            name="CK_proxy_times_used",
        ),
        CheckConstraint(
            "(is_in_use = false AND lease_token IS NULL AND lease_until IS NULL) "
            "OR (is_in_use = true AND lease_token IS NOT NULL AND lease_until IS NOT NULL)",
            name="CK_proxy_lease_state",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    proxy_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_in_use: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    times_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(255))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
