from sqlalchemy import JSON, BigInteger, Column, ForeignKey, Integer, String, Table
from .base import metadata


runs = Table(
    "runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", ForeignKey("cases.id"), nullable=False, index=True),
    Column("status", String(16), nullable=False, index=True),
    Column("parameter", Integer, nullable=False),
    Column("actor", String(48), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("finished_at", BigInteger, nullable=True),
    Column("result", JSON(none_as_null=True), nullable=True),
    Column("failure", String(320), nullable=True),
    Column("digest", String(64), nullable=True),
    # "original" for a first review batch, "correction" for a successor batch.
    Column("kind", String(16), nullable=False, default="original", server_default="original"),
    # The review batch this correction batch supersedes.
    Column("parent_run_id", ForeignKey("runs.id"), nullable=True, index=True),
    # voyage -> corrected gross tonnage, accumulated across a correction chain.
    Column("adjustments", JSON(none_as_null=True), nullable=True),
    # Claim token set when a worker starts computing; cleared on finish. A stale
    # token lets recovery requeue a batch whose worker died.
    Column("claimed_at", BigInteger, nullable=True),
)
