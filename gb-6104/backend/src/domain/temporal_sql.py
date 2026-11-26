from datetime import date

from sqlalchemy import text

MATCH = """
    SELECT t.voyage, t.zone, t.service_date, t.gross_ton,
           COUNT(r.revision) AS match_count, MIN(r.revision) AS revision_code,
           MIN(r.rate_cents) AS rate_cents, MIN(r.min_cents) AS min_cents
    FROM pilot_trip t
    LEFT JOIN pilot_terms r ON r.zone = t.zone
        AND t.service_date >= r.valid_from
        AND (r.valid_until IS NULL OR t.service_date < r.valid_until)
        AND :as_of >= r.recorded_from
        AND (r.recorded_until IS NULL OR :as_of < r.recorded_until)
    WHERE t.account = :account
    GROUP BY t.voyage, t.zone, t.service_date, t.gross_ton
    ORDER BY t.voyage
"""

# The two accounts share one trip table keyed by (account, voyage); MySQL keeps
# the original InnoDB table definition and the app's normal dialect otherwise.
TRIP_SCHEMA = """
    account VARCHAR(8) NOT NULL, voyage VARCHAR(30) NOT NULL, zone VARCHAR(30) NOT NULL,
    service_date DATE NOT NULL, gross_ton INT NOT NULL, PRIMARY KEY (account, voyage)
"""

TERMS_SCHEMA = {
    "mysql": """
        revision VARCHAR(30) PRIMARY KEY, zone VARCHAR(30) NOT NULL,
        valid_from DATE NOT NULL, valid_until DATE,
        recorded_from DATE NOT NULL, recorded_until DATE,
        rate_cents INT NOT NULL, min_cents INT NOT NULL,
        INDEX term_seek (zone, recorded_from, valid_from)
    """,
    "default": """
        revision VARCHAR(30) PRIMARY KEY, zone VARCHAR(30) NOT NULL,
        valid_from DATE NOT NULL, valid_until DATE,
        recorded_from DATE NOT NULL, recorded_until DATE,
        rate_cents INT NOT NULL, min_cents INT NOT NULL
    """,
}


def _ddl(dialect, name, schema):
    engine = " ENGINE=InnoDB" if dialect == "mysql" else ""
    body = schema["mysql" if dialect == "mysql" else "default"] if isinstance(schema, dict) else schema
    return f"CREATE TEMPORARY TABLE {name} ({body}){engine}"


def compare_revisions(db, trips, reviewed_trips, versions, issued, as_of):
    """Price both accounts in one pass.

    The original-account rows use the untouched trips; the review-account rows
    use the corrected tonnages. Both look up rates at the same original review
    day, so a correction changes weights but never the temporal reading.
    """
    dialect = db.engine.dialect.name
    db.execute(text(_ddl(dialect, "pilot_trip", TRIP_SCHEMA)))
    try:
        db.execute(text(_ddl(dialect, "pilot_terms", TERMS_SCHEMA)))
        rows = [
            {"account": account, "voyage": trip["voyage"], "zone": trip["zone"],
             "service_date": trip["service_date"].isoformat(), "gross_ton": trip["gross_ton"]}
            for account, batch in (("original", trips), ("review", reviewed_trips))
            for trip in batch
        ]
        db.execute(text("""
            INSERT INTO pilot_trip VALUES (:account, :voyage, :zone, :service_date, :gross_ton)
        """), rows)
        db.execute(text("""
            INSERT INTO pilot_terms
            VALUES (:revision, :zone, :valid_from, :valid_until, :recorded_from, :recorded_until, :rate, :minimum)
        """), [
            {key: (value.isoformat() if isinstance(value, date) else value) for key, value in term.items()}
            for term in versions
        ])
        original = _account(db, "original", issued)
        review = _account(db, "review", as_of)
        return original, review
    finally:
        db.execute(text("DROP TABLE IF EXISTS pilot_terms"))
        db.execute(text("DROP TABLE IF EXISTS pilot_trip"))


def _account(db, account, as_of):
    rows = db.execute(text(MATCH), {
        "as_of": as_of.isoformat() if isinstance(as_of, date) else as_of, "account": account,
    }).mappings().all()
    # SQLite returns DATE columns as text; MySQL returns date objects. Normalize
    # so the pricing layer always sees a date.
    return [
        {**row, "service_date": _as_date(row["service_date"])}
        for row in rows
    ]


def _as_date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])
