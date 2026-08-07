"""Create all PostgreSQL tables for the application."""

from __future__ import annotations

from sqlalchemy import create_engine, text

from app.database.models import Base, PsychologyToday, ProxyPool
from app.database.repository import database_url


def create_tables() -> None:
    """Create missing tables using the configured PostgreSQL database."""
    print("Tables registered:", list(Base.metadata.tables.keys()))
    engine = create_engine(database_url())
    Base.metadata.create_all(engine)
    add_created_at_column()
    add_phone_number_column()
    add_psychology_today_columns()
    add_profile_scrape_columns()
    add_website_scrape_columns()
    add_profile_identity_and_processing_columns()
    create_proxy_pool_table()
    migrate_proxy_pool_schema()


def create_proxy_pool_table() -> None:
    """Create the proxy_pool table if it does not already exist."""
    engine = create_engine(database_url())
    ProxyPool.__table__.create(engine, checkfirst=True)


def migrate_proxy_pool_schema() -> None:
    """Remove the retired proxy_key column and enforce unique proxy URLs."""
    engine = create_engine(database_url())
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE proxy_pool DROP COLUMN IF EXISTS proxy_key")
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_proxy_pool_proxy_url "
                "ON proxy_pool (proxy_url)"
            )
        )


def add_created_at_column() -> None:
    """Add the UTC creation timestamp to an existing table."""
    engine = create_engine(database_url())
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE psychology_today "
                "ADD COLUMN IF NOT EXISTS created_at "
                "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP"
            )
        )


def add_phone_number_column() -> None:
    """Add the optional phone number to the Psychology Today table."""
    engine = create_engine(database_url())
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE psychology_today "
                "ADD COLUMN IF NOT EXISTS phone_number VARCHAR(50)"
            )
        )


def add_psychology_today_columns() -> None:
    """Append CSV fields missing from existing Psychology Today tables."""
    engine = create_engine(database_url())
    columns = (
        ("client_focus_primary", "TEXT"),
        ("client_focus_secondary", "TEXT"),
        ("insurance_details", "TEXT"),
        ("payment_category", "TEXT"),
        ("fee_raw", "TEXT"),
        ("fee_clean", "TEXT"),
        ("availability_status", "TEXT"),
        ("number_of_cities_served", "INTEGER"),
        ("service_area_cities", "TEXT"),
        ("evidence_snippets", "TEXT"),
        ("category_score", "DOUBLE PRECISION"),
        ("category_evidence", "TEXT"),
        ("all_pages_text", "TEXT"),
    )
    with engine.begin() as connection:
        for name, data_type in columns:
            connection.execute(
                text(
                    f"ALTER TABLE psychology_today "
                    f"ADD COLUMN IF NOT EXISTS {name} {data_type}"
                )
            )


def add_profile_scrape_columns() -> None:
    """Append profile-level scraping status fields to Psychology Today."""
    engine = create_engine(database_url())
    columns = (
        ("profile_scrape_status", "VARCHAR(30)"),
        ("profile_scrape_attempts", "INTEGER"),
        ("profile_scrape_last_error", "TEXT"),
        ("profile_scraped_at", "TIMESTAMP WITH TIME ZONE"),
    )
    with engine.begin() as connection:
        for name, data_type in columns:
            connection.execute(
                text(
                    f"ALTER TABLE psychology_today "
                    f"ADD COLUMN IF NOT EXISTS {name} {data_type}"
                )
                )


def add_website_scrape_columns() -> None:
    """Append website-level scraping status fields to Psychology Today."""
    engine = create_engine(database_url())
    columns = (
        ("website_scrape_status", "VARCHAR(30)"),
        ("website_scrape_attempts", "INTEGER"),
        ("website_scrape_last_error", "TEXT"),
        ("website_scraped_at", "TIMESTAMP WITH TIME ZONE"),
    )
    with engine.begin() as connection:
        for name, data_type in columns:
            connection.execute(
                text(
                    f"ALTER TABLE psychology_today "
                    f"ADD COLUMN IF NOT EXISTS {name} {data_type}"
                )
                )


def add_profile_identity_and_processing_columns() -> None:
    """Append profile identity and processing flags to Psychology Today."""
    engine = create_engine(database_url())
    columns = (
        ("first_name", "VARCHAR(150)"),
        ("last_name", "VARCHAR(150)"),
        ("profile_is_processing", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("website_is_processing", "BOOLEAN NOT NULL DEFAULT FALSE"),
    )
    with engine.begin() as connection:
        for name, data_type in columns:
            connection.execute(
                text(
                    f"ALTER TABLE psychology_today "
                    f"ADD COLUMN IF NOT EXISTS {name} {data_type}"
                )
            )


def drop_psychology_today_table() -> None:
    """Drop the existing Psychology Today table, if it exists."""
    engine = create_engine(database_url())
    PsychologyToday.__table__.drop(engine, checkfirst=True)


def recreate_tables() -> None:
    """Replace the existing Psychology Today table with the current schema."""
    print("creating table")
    drop_psychology_today_table()
    create_tables()


if __name__ == "__main__":
    add_profile_scrape_columns()
    add_website_scrape_columns()
    add_profile_identity_and_processing_columns()
