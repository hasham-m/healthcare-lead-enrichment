"""Pydantic contracts shared by directory scraping workers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ClaimedProfile(BaseModel):
    """A Psychology Today profile atomically assigned to one worker."""

    model_config = ConfigDict(extra="ignore")

    id: int
    source_profile_id: str
    profile_url: str
    profile_scrape_attempts: int = 0


class ProfileEnrichment(BaseModel):
    """Fields extracted from one Psychology Today profile page."""

    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None
    pt_website_redirect: str | None = None
    all_specialties: str | None = None
    best_specialty: str | None = None
    client_focus: str | None = None
    client_focus_primary: str | None = None
    client_focus_secondary: str | None = None
    insurance_details: str | None = None
    payment_category: Literal["hybrid", "self_pay", "insurance_only"] | None = None
    fee_raw: str | None = None
    fee_clean: str | None = None
    availability_status: Literal[
        "waitlist", "not_accepting_new_clients", "accepting_new_clients"
    ] | None = None


class ProfileScrapeSummary(BaseModel):
    """Result counters for an async Psychology Today profile-worker run."""

    claimed: int = 0
    completed: int = 0
    requeued: int = 0
    failed: int = 0
    started_at: datetime
    finished_at: datetime | None = None
