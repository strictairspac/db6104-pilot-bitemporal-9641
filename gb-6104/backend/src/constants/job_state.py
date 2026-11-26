from enum import StrEnum


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    VOIDED = "voided"


# States that still await a decision. A correction may void either one.
OPEN = (JobState.QUEUED, JobState.RUNNING)
