from time import time

from fastapi import HTTPException
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from src.constants.job_state import JobState
from src.models.corrections import corrections
from src.models.reviews import reviews
from src.models.runs import runs
from . import audit


def get(db, run_id):
    row = db.execute(select(reviews).where(reviews.c.run_id == run_id)).mappings().first()
    return dict(row) if row else None


def sign(db, run_id, data, actor):
    row = db.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().first()
    if row is None:
        raise HTTPException(404, "执行批次不存在")
    if row["status"] == JobState.VOIDED:
        raise HTTPException(409, "该批次已被更正取代，不能再签核")
    if row["status"] != JobState.DONE:
        raise HTTPException(409, "批次执行成功后才能签核")
    # A voided draft can never carry a correction, but guard the chain anyway:
    # signing must not land on a batch that was superseded.
    superseded = db.scalar(select(corrections.c.id).where(corrections.c.parent_run_id == run_id))
    if superseded is not None:
        raise HTTPException(409, "该批次已被更正取代，不能再签核")
    try:
        db.execute(insert(reviews).values(run_id=run_id, note=data.note, actor=actor, created_at=int(time())))
    except IntegrityError as exc:
        raise HTTPException(409, "该批次已经签核") from exc
    audit.record(db, "review", actor, "run", run_id)
    return get(db, run_id)
