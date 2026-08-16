"""Download filtered Psychology Today lead data from PostgreSQL into a CSV."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

from pydantic import BaseModel

from app.database.repository import DEFAULT_LEAD_EXPORT_COLUMNS, LeadExportRepository


class LeadDownloadResult(BaseModel):
    """Summary of one CSV lead-data export."""

    output_path: Path
    rows_exported: int
    columns: list[str]


def download_leads(
    *,
    output_path: str | Path = "downloaded_leads.csv",
    columns: Sequence[str] | None = None,
    directory: str | None = None,
    source_city: str | None = None,
    source_state: str | None = None,
    profile_scrape_status: str | None = None,
    website_resolution_status: str | None = None,
    website_scrape_status: str | None = None,
    website_scrape_eligible: bool | None = None,
    created_since: datetime | None = None,
    created_within_hours: int | None = None,
    filters: Mapping[str, object] | None = None,
    repository: LeadExportRepository | None = None,
) -> LeadDownloadResult:
    """Write selected lead data to CSV using optional database filters.

    Set any named filter to ``None`` to omit it. ``filters`` additionally accepts
    any mapped ``psychology_today`` field, such as
    ``{"category": "private_practice"}`` or a list of allowed values.
    """
    if created_since is not None and created_within_hours is not None:
        raise ValueError("Pass either created_since or created_within_hours, not both")
    if created_within_hours is not None and created_within_hours < 0:
        raise ValueError("created_within_hours must be zero or greater")

    created_since = created_since or (
        datetime.now(timezone.utc) - timedelta(hours=created_within_hours)
        if created_within_hours is not None
        else None
    )
    selected_columns = tuple(columns or DEFAULT_LEAD_EXPORT_COLUMNS)
    rows = (repository or LeadExportRepository()).fetch_leads(
        columns=selected_columns,
        directory=directory,
        source_city=source_city,
        source_state=source_state,
        profile_scrape_status=profile_scrape_status,
        website_resolution_status=website_resolution_status,
        website_scrape_status=website_scrape_status,
        website_scrape_eligible=website_scrape_eligible,
        created_since=created_since,
        filters=filters,
    )

    destination = Path(output_path).resolve()
    with destination.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=selected_columns)
        writer.writeheader()
        writer.writerows(rows)

    return LeadDownloadResult(
        output_path=destination,
        rows_exported=len(rows),
        columns=list(selected_columns),
    )


if __name__ == "__main__":
    result = download_leads(
        output_path="downloaded_leads.csv",
        website_resolution_status="completed",
    )
    print(result.model_dump_json(indent=2))
