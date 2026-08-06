"""Universal scrape-run lifecycle and resumability helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.database.models import ScrapeRun
from app.database.repository import ScrapeRunRepository


class ScrapeRunState(BaseModel):
    """Safe structured representation of a scrape run."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    directory: str
    start_url: str
    target_profile: int
    max_pages: int
    pages_completed: int
    unique_profile: int
    last_completed_page_url: str | None
    next_page_url: str | None
    status: Literal["running", "completed", "failed", "pending"]
    last_error: str | None
    created_at: datetime
    completed_at: datetime | None


class ScrapeRunManager:
    """Universal facade for scrape-run persistence and resumption."""

    def __init__(self, repository: ScrapeRunRepository | None = None) -> None:
        self._repository = repository or ScrapeRunRepository()

    def start(
        self,
        *,
        directory: str,
        start_url: str,
        target_profile: int,
        max_pages: int,
        next_page_url: str,
    ) -> ScrapeRunState:
        """Create a new running scrape record."""
        return ScrapeRunState.model_validate(
            self._repository.start(
                directory=directory,
                start_url=start_url,
                target_profile=target_profile,
                max_pages=max_pages,
                next_page_url=next_page_url,
            )
        )

    def update(self, run_id: int, **values: object) -> None:
        """Persist page progress for a run."""
        self._repository.update(run_id, **values)

    def finish(
        self,
        run_id: int,
        *,
        status: Literal["completed", "failed", "pending"],
        last_error: str | None = None,
    ) -> None:
        """Finalize a run with its outcome."""
        self._repository.finish(run_id, status=status, last_error=last_error)

    def find_resumable(
        self,
        run_id: int | None = None,
        *,
        status: Literal["pending", "failed"] | None = None,
        directory: str | None = None,
        start_url: str | None = None,
    ) -> ScrapeRunState | None:
        """Find the first pending or failed run that can resume."""
        run = self._repository.get_resumable(
            run_id, status=status, directory=directory, start_url=start_url
        )
        return ScrapeRunState.model_validate(run) if run else None

    def resume(self, run_id: int) -> ScrapeRunState:
        """Mark a pending or failed run as running and return its saved state."""
        run = self.find_resumable(run_id)
        if run is None:
            raise LookupError(f"No resumable scrape run found for ID {run_id}")
        self._repository.update(
            run.id,
            status="running",
            last_error=None,
            completed_at=None,
        )
        resumed = self.find_running(run.id)
        if resumed is None:
            raise LookupError(f"Scrape run {run.id} could not be resumed")
        return resumed

    def find_running(self, run_id: int) -> ScrapeRunState | None:
        """Read a run after it has been marked running."""
        run = self._repository.get_by_id(run_id)
        return ScrapeRunState.model_validate(run) if run else None
