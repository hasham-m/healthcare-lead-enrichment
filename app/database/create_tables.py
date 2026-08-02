"""Create all PostgreSQL tables for the application."""

from __future__ import annotations

from sqlalchemy import create_engine, text

from app.database.models import Base, PsychologyToday
from app.database.repository import database_url


def create_tables() -> None:
    """Create missing tables using the configured PostgreSQL database."""
    print("Tables registered:", list(Base.metadata.tables.keys()))
    engine = create_engine(database_url())
    Base.metadata.create_all(engine)
    add_created_at_column()
    add_phone_number_column()


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
    create_tables()
