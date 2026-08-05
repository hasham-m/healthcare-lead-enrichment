"""Persistence operations for scraped therapist profiles."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.directories.helpers import Helpers
from app.database.models import ProxyPool, PsychologyToday, ScrapeRun


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

    def finish(
        self, run_id: int, *, status: str, last_error: str | None = None
    ) -> None:
        """Mark a run as completed, failed, or pending."""
        self.update(
            run_id,
            status=status,
            last_error=last_error,
            completed_at=datetime.now(timezone.utc) if status != "pending" else None,
        )


class ProxyPoolRepository:
    """Database operations for proxies sourced from a CSV file."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        if session_factory is None:
            engine = create_engine(database_url())
            session_factory = sessionmaker(bind=engine)
        self._session_factory = session_factory

    def sync_csv_proxies(
        self, proxies: Iterable[Mapping[str, object]]
    ) -> tuple[int, int, int]:
        """Reconcile the proxy pool with the current CSV snapshot."""
        proxy_rows = list(proxies)
        csv_proxy_urls = {str(proxy["proxy_url"]) for proxy in proxy_rows}
        added = deactivated = reactivated = 0
        with self._session_factory() as session:
            existing_proxies = list(session.scalars(select(ProxyPool)))
            existing_by_url = {proxy.proxy_url: proxy for proxy in existing_proxies}

            # this for loop deactivates proxies in the database that no longer exist in the csv
            for current in existing_proxies:
                if current.proxy_url not in csv_proxy_urls and current.is_active:
                    current.is_active = False
                    deactivated += 1

            # this for loop adds the unique and active proxies from the csv to the database
            for proxy in proxy_rows:
                proxy_url = str(proxy["proxy_url"])
                current = existing_by_url.get(proxy_url)
                if current is None:
                    session.add(
                        ProxyPool(
                            proxy_url=proxy_url,
                            is_active=bool(proxy["is_active"]),
                        )
                    )
                    added += 1
                    continue

                is_active = bool(proxy["is_active"])
                if current.is_active != is_active:
                    if is_active:
                        reactivated += 1
                    else:
                        deactivated += 1
                    current.is_active = is_active
            session.commit()
        return added, deactivated, reactivated

    def active_proxy_urls(self) -> list[str]:
        """Return active, currently unleased proxy URLs in stable order."""
        with self._session_factory() as session:
            statement = (
                select(ProxyPool.proxy_url)
                .where(ProxyPool.is_active.is_(True), ProxyPool.is_in_use.is_(False))
                .order_by(ProxyPool.id)
            )
            return list(session.scalars(statement))

    def acquire_proxy(self, lease_minutes: int = 10) -> dict[str, object] | None:
        """Atomically lease the least-used available proxy."""
        now = datetime.now(timezone.utc)
        lease_token = uuid4().hex
        lease_until = now + timedelta(minutes=lease_minutes)

        with self._session_factory() as session:
            statement = (
                select(ProxyPool)
                .where(
                    ProxyPool.is_active.is_(True),
                    or_(
                        ProxyPool.is_in_use.is_(False),
                        ProxyPool.lease_until <= now,
                    ),
                )
                .order_by(ProxyPool.times_used, ProxyPool.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            proxy = session.scalar(statement)
            if proxy is None:
                return None

            proxy.is_in_use = True
            proxy.lease_token = lease_token
            proxy.lease_until = lease_until
            proxy.times_used += 1
            session.commit()
            return {
                "id": proxy.id,
                "proxy_url": proxy.proxy_url,
                "lease_token": lease_token,
                "lease_until": lease_until,
            }

    def renew_proxy_lease(
        self, lease_token: str, extension_minutes: int = 5
    ) -> dict[str, object] | None:
        """Extend an active lease from its current expiry by five minutes."""
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            statement = (
                select(ProxyPool)
                .where(
                    ProxyPool.lease_token == lease_token,
                    ProxyPool.is_in_use.is_(True),
                )
                .with_for_update()
            )
            proxy = session.scalar(statement)
            if proxy is None:
                return None

            current_until = proxy.lease_until or now
            proxy.lease_until = max(current_until, now) + timedelta(
                minutes=extension_minutes
            )
            session.commit()
            return {
                "id": proxy.id,
                "proxy_url": proxy.proxy_url,
                "lease_token": lease_token,
                "lease_until": proxy.lease_until,
            }

    def release_proxy(self, lease_token: str) -> bool:
        """Release a lease and record when the proxy finished its session."""
        with self._session_factory() as session:
            statement = (
                select(ProxyPool)
                .where(
                    ProxyPool.lease_token == lease_token,
                    ProxyPool.is_in_use.is_(True),
                )
                .with_for_update()
            )
            proxy = session.scalar(statement)
            if proxy is None:
                return False

            proxy.is_in_use = False
            proxy.lease_token = None
            proxy.lease_until = None
            proxy.last_used_at = datetime.now(timezone.utc)
            session.commit()
            return True
