# Therapist Scraper

## Proxy CSV synchronization

The application treats `proxies.csv` as the source of proxy definitions and
`proxy_pool` as the runtime proxy store. At the beginning of each scraper run,
the CSV is synchronized to PostgreSQL. New unique proxy URLs are inserted, and
existing rows are not replaced. Proxies absent from the current CSV are marked
inactive, while returning proxies are reactivated when their CSV `enabled`
value is true and counted as reactivated. CSV rows marked disabled are stored
as inactive and counted as deactivated.

### Proxy-related files

- `app/database/models.py` - defines the `ProxyPool` PostgreSQL table and its
  lease-state and non-negative usage constraints.
- `app/database/repository.py` - `ProxyPoolRepository` inserts unique URLs,
  marks missing URLs inactive, and reads active, unleased proxies.
- `app/directories/scrape_runs.py` - `ScrapeRunManager` is the universal
  directory-level facade for starting, updating, finishing, querying, and
  resuming pending or failed scrape runs. `ScrapeRunState` is a Pydantic model
  used for structured run state.
- `app/directories/resume_run.py` - test utility that automatically queries the
  first pending or failed run, then passes its saved start URL, target limits,
  and run ID to the normal scraper without user input.
- `app/database/create_tables.py` - initializes `proxy_pool` and removes the
  retired `proxy_key` column from existing databases.
- `app/infrastructure/proxies/csv_loader.py` - validates proxy URLs and CSV
  enabled values with Pydantic.
- `app/infrastructure/proxies/service.py` - coordinates CSV loading,
  `proxy_pool` synchronization, and ten-minute proxy leases using Pydantic
  lease/result models.
- `app/directories/psychology_today/pages_scraper.py` - synchronizes the CSV
  at scraper startup, uses active proxy URLs from `proxy_pool`, records page
  progress through `ScrapeRunManager`, and supports `resume_run_id` to continue
  from the saved `next_page_url`.

Proxy acquisition locks the least-used active row with `SKIP LOCKED`, sets
`is_in_use`, assigns a ten-minute lease, and increments `times_used` once for
the session. The lease is extended by five minutes when it has five minutes
remaining. Release clears the lease fields, sets `is_in_use` to false, and
updates `last_used_at`; `last_checked_at` is left untouched.

To resume a pending or failed run, pass its ID and the original start URL to
`scrape_profile_urls(..., resume_run_id=RUN_ID)`. The manager changes the run
back to `running`, reads `next_page_url`, and the normal page loop continues
from that URL.

On Windows, use `Ctrl+C` to interrupt the process. `Ctrl+Z` is not a process
interrupt signal in the Windows console; it behaves as input EOF and cannot be
reliably used to raise `KeyboardInterrupt` inside an HTTP request.

## Psychology Today profile enrichment

- `app/directories/schemas.py` - Pydantic contracts for profiles claimed from
  the database, parsed profile enrichment fields, and async worker summaries.
- `app/directories/psychology_today/profile_enrichment.py` - pure HTML parser
  for individual Psychology Today profiles. It extracts names, phone number,
  the Psychology Today website redirect (or `__unavailable__`), specialties,
  client focus, insurance/payment category, fees, and availability.
- `app/directories/psychology_today/profile_scraper.py` - async worker
  coordinator. Workers claim pending profiles directly from PostgreSQL using
  `PsychologyTodayProfileRepository`, obtain one proxy lease per profile HTTP
  session, request and parse the profile, then persist the enriched fields.
- `app/database/repository.py` - `PsychologyTodayProfileRepository` now also
  exposes `release_profile_claim()` for retryable errors. It returns the row to
  `pending`, records the error, and clears `profile_is_processing`.

`scrape_pending_profiles()` supports optional `created_since`, `source_city`,
and `source_state` filters. A successful scrape sets
`profile_scrape_status=completed`, clears `profile_is_processing`, stamps
`profile_scraped_at` in UTC, and queues website scraping by setting a null
`website_scrape_status` to `pending`. Retryable errors return the profile to
pending; after the configured attempt limit, the profile is marked failed.

The profile parser reads leaf `div` values in Practice at a Glance (including
waitlist/not-accepting availability messages) and reads Client Focus values
from semantic `span[data-x="attribute-…"]` elements. It combines Age,
Participants, Communities, and Ethnicity while avoiding duplicate layout
containers.

## Manual Psychology Today enrichment CSV test

`tests/psychology_today/validation/pt_profile_enrichment_validation.py` is a
database-safe manual test for parser review. It contains the selected profile
URLs, fetches them concurrently through the normal proxy leases, validates each
parser result with `ProfileEnrichment` and `EnrichmentCsvRow` Pydantic models,
and writes `pt_profile_enrichment_results.csv` to the repository root. It does
not claim, insert, or update rows in `psychology_today`; only the normal
`proxy_pool` lease/usage bookkeeping is exercised.

`tests/psychology_today/fixtures` contains short, version-controlled HTML
snippets. `tests/psychology_today/regression/test_profile_enrichment_regressions.py`
uses those fixtures to protect parser behavior without network, proxy, or
database access.
