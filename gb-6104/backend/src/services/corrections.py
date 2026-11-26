from time import time

from fastapi import HTTPException
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from src.constants.job_state import OPEN, JobState
from src.domain.contract_terms import apply_adjustments, parse
from src.models.cases import cases
from src.models.corrections import corrections
from src.models.reviews import reviews
from src.models.runs import runs
from src.utils.serial import content_digest
from . import audit


def _digest(code, parent_run_id, adjustments, note):
    """Fingerprint of a correction notice. A retry resends the same body and
    replays silently; any change to the notice under the same number (tonnage or
    note) is a different notice and is refused."""
    return content_digest({
        "code": code, "parent_run_id": parent_run_id, "adjustments": adjustments, "note": note,
    })


def get(db, correction_id):
    row = db.execute(select(corrections).where(corrections.c.id == correction_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "更正记录不存在")
    return dict(row)


def _find(db, code, locking):
    statement = select(corrections).where(corrections.c.code == code)
    if locking:
        # A locking read bypasses the transaction's repeatable-read snapshot and
        # sees the row committed by a concurrent retry.
        statement = statement.with_for_update()
    row = db.execute(statement).mappings().first()
    return dict(row) if row else None


def _answer(existing, digest, replayed):
    """A notice number is an idempotency key: the same content replays the batch
    already produced, while different content is refused."""
    if existing["digest"] != digest:
        raise HTTPException(409, "同一更正单号不能更换更正内容")
    return {**existing, "replayed": replayed}


def _signed(db, run_id):
    statement = select(reviews.c.run_id).where(reviews.c.run_id == run_id).with_for_update()
    return db.scalar(statement)


def _corrected(db, run_id):
    statement = select(corrections.c.id).where(corrections.c.parent_run_id == run_id).with_for_update()
    return db.scalar(statement)


def register(db, parent_run_id, data, actor):
    """Void the target batch and start a successor with the corrected tonnages.

    The parent run row is locked for the whole decision, exactly as signing is,
    so a correction and a signature racing on the same batch serialize:
    whichever commits first wins and the other fails.
    """
    adjustments = dict(data.adjustments)
    digest = _digest(data.code, parent_run_id, adjustments, data.note)

    existing = _find(db, data.code, locking=False)
    if existing is not None:
        return _answer(existing, digest, True)

    # A queued draft may be locked by the worker; wait for that transaction and
    # then decide against the settled state.
    parent = db.execute(
        select(runs).where(runs.c.id == parent_run_id).with_for_update()
    ).mappings().first()
    if parent is None:
        raise HTTPException(404, "执行批次不存在")

    # Re-check under a locking read: a concurrent retry of this same notice may
    # have committed while we waited for the row lock.
    existing = _find(db, data.code, locking=True)
    if existing is not None:
        return _answer(existing, digest, True)
    if parent["status"] not in (*OPEN, JobState.DONE):
        raise HTTPException(409, "该批次已作废或失败，不能再登记更正")
    if _signed(db, parent_run_id) is not None:
        raise HTTPException(409, "该批次已经签核，不能再登记更正")
    if _corrected(db, parent_run_id) is not None:
        raise HTTPException(409, "该批次已经登记过更正")

    merged = {**(parent["adjustments"] or {}), **adjustments}
    payload = db.scalar(select(cases.c.payload).where(cases.c.id == parent["case_id"]))
    trips, _terms, _issued = parse(payload)
    try:
        apply_adjustments(trips, merged)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    # The successor run and the notice row go in one savepoint, so a correction
    # that loses a race leaves no orphan successor behind. Both unique keys
    # (notice code, one correction per parent) enforce the invariants in the
    # database even when two connections pass the pre-checks simultaneously.
    try:
        with db.begin_nested():
            successor_id = db.execute(insert(runs).values(
                case_id=parent["case_id"], status=JobState.QUEUED, parameter=parent["parameter"],
                actor=actor, created_at=int(time()), kind="correction", parent_run_id=parent_run_id,
                adjustments=merged,
            )).inserted_primary_key[0]
            correction_id = db.execute(insert(corrections).values(
                code=data.code, parent_run_id=parent_run_id, run_id=successor_id,
                adjustments=merged, note=data.note, digest=digest, actor=actor, created_at=int(time()),
            )).inserted_primary_key[0]
    except IntegrityError:
        return _resolve_conflict(db, data.code, parent_run_id, digest)

    # Void the old draft before the successor can finish: a late result can no
    # longer become signable, and the new batch is the only one awaiting signing.
    db.execute(update(runs).where(runs.c.id == parent_run_id).values(status=JobState.VOIDED))
    audit.record(db, "correct", actor, "run", parent_run_id)
    audit.record(db, "enqueue", actor, "run", successor_id)
    return {**get(db, correction_id), "replayed": False}


def _resolve_conflict(db, code, parent_run_id, digest):
    """A concurrent correction beat us: replay our own notice if it is a retry,
    otherwise report that the batch was already corrected (first to commit wins)."""
    existing = _find(db, code, locking=True)
    if existing is not None:
        return _answer(existing, digest, True)
    if _corrected(db, parent_run_id) is not None:
        raise HTTPException(409, "该批次已经登记过更正")
    raise HTTPException(409, "更正登记与另一操作冲突，请重试")
