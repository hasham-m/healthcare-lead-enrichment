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
- `app/database/create_tables.py` - initializes `proxy_pool` and removes the
  retired `proxy_key` column from existing databases.
- `app/infrastructure/proxies/csv_loader.py` - validates proxy URLs and CSV
  enabled values with Pydantic.
- `app/infrastructure/proxies/service.py` - coordinates CSV loading,
  `proxy_pool` synchronization, and ten-minute proxy leases using Pydantic
  lease/result models.
- `app/directories/psychology_today/pages_scraper.py` - synchronizes the CSV
  at scraper startup, then uses active proxy URLs from `proxy_pool`.

Proxy acquisition locks the least-used active row with `SKIP LOCKED`, sets
`is_in_use`, assigns a ten-minute lease, and increments `times_used` once for
the session. The lease is extended by five minutes when it has five minutes
remaining. Release clears the lease fields, sets `is_in_use` to false, and
updates `last_used_at`; `last_checked_at` is left untouched.
