from sqlalchemy import JSON, BigInteger, Column, ForeignKey, Integer, String, Table
from .base import metadata


# One row per accepted correction notice. `code` is the notice number and acts as
# the idempotency key: replaying the same notice returns the same successor batch.
corrections = Table(
    "corrections",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("code", String(48), unique=True, nullable=False),
    # A parent batch can be corrected at most once; the successor may be
    # corrected in turn, which is how a chain forms.
    Column("parent_run_id", ForeignKey("runs.id"), nullable=False, unique=True, index=True),
    Column("run_id", ForeignKey("runs.id"), nullable=False, unique=True),
    Column("adjustments", JSON, nullable=False),
    Column("note", String(500), nullable=False),
    Column("digest", String(64), nullable=False),
    Column("actor", String(48), nullable=False),
    Column("created_at", BigInteger, nullable=False),
)
