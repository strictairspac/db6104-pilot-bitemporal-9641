from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from src.config.resources import engine
from src.constants.job_state import JobState
from src.controllers.access import identity, operator, reviewer
from src.controllers.workbench import new_correction, new_review
from src.models.corrections import corrections
from src.schemas.corrections import CorrectionEntry, CorrectionInput
from src.schemas.reviews import ReviewEntry, ReviewInput
from src.schemas.runs import RunEntry
from src.services import reviews as review_service, runs
from src.utils.serial import canonical_json

router = APIRouter(prefix="/runs", tags=["Execution"])


@router.get("", response_model=list[RunEntry], dependencies=[Depends(identity)])
def list_runs():
    with engine.connect() as db:
        return runs.list_entries(db)


@router.get("/{run_id}", response_model=RunEntry, dependencies=[Depends(identity)])
def run_detail(run_id: int):
    with engine.connect() as db:
        return runs.get(db, run_id)


@router.get("/{run_id}/review", response_model=ReviewEntry | None, dependencies=[Depends(identity)])
def review_detail(run_id: int):
    with engine.connect() as db:
        runs.get(db, run_id)
        return review_service.get(db, run_id)


@router.get("/{run_id}/correction", response_model=CorrectionEntry | None, dependencies=[Depends(identity)])
def correction_detail(run_id: int):
    with engine.connect() as db:
        runs.get(db, run_id)
        row = db.execute(select(corrections).where(corrections.c.run_id == run_id)).mappings().first()
        return dict(row) if row else None


@router.post("/{run_id}/corrections", response_model=CorrectionEntry, status_code=202)
def register_correction(run_id: int, form: CorrectionInput, user=Depends(operator)):
    return new_correction(run_id, form, user)


@router.post("/{run_id}/review", response_model=ReviewEntry, status_code=201)
def sign(run_id: int, form: ReviewInput, user=Depends(reviewer)):
    return new_review(run_id, form, user)


@router.get("/{run_id}/export", dependencies=[Depends(identity)])
def export(run_id: int):
    with engine.connect() as db:
        run = runs.get(db, run_id)
        # A signed batch stays downloadable exactly as it was signed, even after
        # a later correction. An unsigned voided draft has no evidence to give.
        if run["status"] == JobState.VOIDED and review_service.get(db, run_id) is None:
            raise HTTPException(409, "该批次已被更正取代，没有可导出的证据")
        if run["status"] not in (JobState.DONE, JobState.VOIDED):
            raise HTTPException(409, "没有可导出的执行结果")
        run["review"] = review_service.get(db, run_id)
        correction = db.execute(select(corrections).where(corrections.c.run_id == run_id)).mappings().first()
        run["correction"] = dict(correction) if correction else None
    return Response(canonical_json(run), media_type="application/json", headers={
        "Content-Disposition": f"attachment; filename=evidence-{run_id}.json",
    })
