from time import time

from fastapi import HTTPException
from sqlalchemy import insert, select
from sqlalchemy.orm import aliased

from src.constants.job_state import JobState
from src.domain.scenario import CONFIG
from src.models.cases import cases
from src.models.corrections import corrections
from src.models.runs import runs
from . import audit, cases as case_service

origin = aliased(corrections)   # The notice that produced this run (this run is a successor).
replacement = aliased(corrections)  # The notice that voided this run.


def query():
    return (
        select(
            runs, cases.c.title.label("case_title"),
            origin.c.code.label("correction_code"),
            replacement.c.code.label("superseded_by_code"),
            replacement.c.run_id.label("superseded_by_run_id"),
        )
        .select_from(runs)
        .join(cases, cases.c.id == runs.c.case_id)
        .outerjoin(origin, origin.c.run_id == runs.c.id)
        .outerjoin(replacement, replacement.c.parent_run_id == runs.c.id)
    )


def get(db, run_id):
    run = db.execute(query().where(runs.c.id == run_id)).mappings().first()
    if run is None:
        raise HTTPException(404, "执行批次不存在")
    return dict(run)


def list_entries(db):
    return [dict(row) for row in db.execute(query().order_by(runs.c.id.desc()).limit(100)).mappings()]


def enqueue(db, case_id, parameter, actor):
    if parameter > CONFIG["max_parameter"]:
        raise HTTPException(422, f"参数不能超过 {CONFIG['max_parameter']}")
    case_service.get(db, case_id)
    change = db.execute(insert(runs).values(
        case_id=case_id, status=JobState.QUEUED, parameter=parameter, actor=actor,
        created_at=int(time()), kind="original",
    ))
    run_id = change.inserted_primary_key[0]
    audit.record(db, "enqueue", actor, "run", run_id)
    return get(db, run_id)
