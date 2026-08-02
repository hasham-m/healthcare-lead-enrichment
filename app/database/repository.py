"""Persistence operations for scraped therapist profiles."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.directories.helpers import Helpers
from app.database.models import PsychologyToday, ScrapeRun


def database_url() -> str:
    """Return the configured SQLAlchemy PostgreSQL connection URL."""
    Helpers.load_root_env()
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return url


class ProfileRepository:
    """Repository for creating and reading Psychology Today profiles."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        if session_factory is None:
            engine = create_engine(database_url())
            session_factory = sessionmaker(bind=engine)
        self._session_factory = session_factory

    def add(self, profile: PsychologyToday) -> PsychologyToday:
        """Persist one profile and return it after the transaction commits."""
        with self._session_factory() as session:
            session.add(profile)
            session.commit()
            session.refresh(profile)
            return profile

    def add_many(self, profiles: Iterable[PsychologyToday]) -> None:
        """Persist multiple profiles in one transaction."""
        with self._session_factory() as session:
            session.add_all(profiles)
            session.commit()

    def save_scraped_profiles(self, profiles: Iterable[Mapping[str, str]]) -> int:
        """Insert or update the fields currently returned by the scraper."""
        models = [
            PsychologyToday(
                directory=profile.get("directory", "psychology_today"),
                source_profile_id=profile.get(
                    "source_profile_id", f"PT:{profile['profile_id']}"
                ),
                profile_id=profile["profile_id"],
                profile_url=profile["profile_url"],
                source_city=profile["source_city"],
                source_state=profile["source_state"],
            )
            for profile in profiles
            if profile.get("profile_id")
        ]
        with self._session_factory() as session:
            for profile in models:
                session.merge(profile)
            session.commit()
        return len(models)

    def get(self, source_profile_id: str) -> PsychologyToday | None:
        """Find a profile by its source-specific primary key."""
        with self._session_factory() as session:
            statement = select(PsychologyToday).where(
                PsychologyToday.source_profile_id == source_profile_id,
            )
            return session.scalar(statement)


class ScrapeRunRepository:
    """Repository for tracking directory scrape progress."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        if session_factory is None:
            engine = create_engine(database_url())
            session_factory = sessionmaker(bind=engine)
        self._session_factory = session_factory

    def start(
        self,
        *,
        directory: str,
        start_url: str,
        target_profile: int,
        max_pages: int,
        next_page_url: str,
    ) -> ScrapeRun:
        """Create a running record for a new scrape."""
        run = ScrapeRun(
            directory=directory,
            start_url=start_url,
            target_profile=target_profile,
            max_pages=max_pages,
            pages_completed=0,
            unique_profile=0,
            next_page_url=next_page_url,
            status="running",
        )
        with self._session_factory() as session:
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

    def update(self, run_id: int, **values: object) -> None:
        """Update progress or outcome fields for a scrape run."""
        with self._session_factory() as session:
            run = session.get(ScrapeRun, run_id)
            if run is None:
                raise LookupError(f"Scrape run {run_id} was not found")
            for field, value in values.items():
                setattr(run, field, value)
            session.commit()

    def finish(self, run_id: int, *, status: str, last_error: str | None = None) -> None:
        """Mark a run as completed, failed, or pending."""
        self.update(
            run_id,
            status=status,
            last_error=last_error,
            completed_at=datetime.now(timezone.utc) if status != "pending" else None,
        )
