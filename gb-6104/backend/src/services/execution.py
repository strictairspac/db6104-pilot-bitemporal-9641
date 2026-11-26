import logging
from time import time, time_ns

from sqlalchemy import select, update

from src.config.resources import engine
from src.constants.job_state import JobState
from src.domain import scenario
from src.models.cases import cases
from src.models.runs import runs
from src.services.audit import record
from src.utils.serial import content_digest

logger = logging.getLogger(__name__)

# A claim older than this is assumed dead (worker crashed mid-computation) and
# is put back on the queue. In-flight computations take milliseconds.
LEASE_NS = 120 * 1_000_000_000


def recover_stale():
    """Requeue batches whose worker died while computing them.

    A correction cannot leave a stale claim behind: it moves the batch to
    voided, which recovery never touches.
    """
    with engine.begin() as db:
        db.execute(update(runs).where(
            runs.c.status == JobState.RUNNING,
            runs.c.claimed_at.is_not(None),
            runs.c.claimed_at < time_ns() - LEASE_NS,
        ).values(status=JobState.QUEUED, claimed_at=None))


def service_one():
    # Claim in a short transaction, then compute outside any row lock so a
    # correction can still void the batch while the work is in flight.
    with engine.begin() as db:
        task = _claim(db)
    if task is None:
        return False
    token = task["claimed_at"]
    try:
        with engine.begin() as db:
            payload = db.scalar(select(cases.c.payload).where(cases.c.id == task["case_id"]))
            result = scenario.run(payload, task["parameter"], db, task["adjustments"])
            output = {"status": JobState.DONE, "result": result, "digest": content_digest(result)}
    except Exception as exc:
        # The failed transaction rolled back cleanly; persist the error next.
        raise JobFailure(task["id"], token, exc) from exc
    # A discarded result (voided or re-queued) still counts as work done, so the
    # loop keeps draining instead of pausing for the next wake.
    finish(task["id"], token, output)
    return True


class JobFailure(Exception):
    def __init__(self, run_id, token, cause):
        super().__init__(str(cause))
        self.run_id = run_id
        self.token = token
        self.cause = cause


def _claim(db):
    statement = (
        select(runs).where(runs.c.status == JobState.QUEUED).order_by(runs.c.id)
        .limit(1).with_for_update(skip_locked=True)
    )
    task = db.execute(statement).mappings().first()
    if task is None:
        return None
    token = time_ns()
    db.execute(update(runs).where(runs.c.id == task["id"]).values(
        status=JobState.RUNNING, claimed_at=token,
    ))
    return {**dict(task), "claimed_at": token}


def fail(job_failure):
    cause = job_failure.cause
    if isinstance(cause, (ValueError, TypeError, KeyError, OverflowError)):
        reason = str(cause) or "输入资料或批次参数不符合要求"
    else:
        reason = "处理失败，请检查 worker 日志"
    return finish(job_failure.run_id, job_failure.token, {"status": JobState.FAILED, "failure": reason[:320]})


def finish(run_id, token, output):
    """Write a terminal state only if this claim still owns the batch.

    A correction voids the batch while the computation is in flight; a stale
    claim (recovered and re-queued elsewhere) also no longer matches. In both
    cases the late result is discarded rather than overwriting the newer state,
    so a voided draft can never become done and therefore can never be signed.
    """
    with engine.begin() as db:
        row = db.execute(
            select(runs.c.status, runs.c.claimed_at).where(runs.c.id == run_id).with_for_update()
        ).first()
        if row is None or row.status != JobState.RUNNING or row.claimed_at != token:
            return False
        db.execute(update(runs).where(runs.c.id == run_id).values(
            **output, finished_at=int(time()), claimed_at=None,
        ))
        record(db, str(output["status"]), "worker", "run", run_id)
        return True
