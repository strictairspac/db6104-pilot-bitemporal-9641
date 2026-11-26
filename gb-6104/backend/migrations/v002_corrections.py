from sqlalchemy import inspect, text

from src.models.base import metadata

# Columns added to the runs table after version 1 shipped. Kept additive so an
# existing deployment can pick them up without dropping its data.
RUN_COLUMNS = {
    "kind": "VARCHAR(16) NOT NULL DEFAULT 'original'",
    "parent_run_id": "INT NULL",
    "adjustments": "JSON NULL",
    "claimed_at": "BIGINT NULL",
}


def upgrade(connection):
    # create_all is a no-op for tables that already exist, and creates the
    # corrections table (with its unique keys) on a fresh or upgraded volume.
    metadata.create_all(connection)
    inspector = inspect(connection)
    existing = {column["name"] for column in inspector.get_columns("runs")}
    for name, definition in RUN_COLUMNS.items():
        if name in existing:
            continue
        # Each ALTER is independent so a re-run after a partial failure only
        # adds what is still missing. MySQL commits DDL implicitly.
        connection.execute(text(f"ALTER TABLE runs ADD COLUMN {name} {definition}"))
    indexes = {index["name"] for index in inspect(connection).get_indexes("runs")}
    if "ix_runs_parent_run_id" not in indexes:
        connection.execute(text("CREATE INDEX ix_runs_parent_run_id ON runs (parent_run_id)"))
