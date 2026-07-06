import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

from fastapi import HTTPException

from . import config, pipeline

logger = logging.getLogger("jobs")

JobType = Literal["file", "youtube"]
JobStatus = Literal["queued", "processing", "done", "error"]


@dataclass
class Job:
    id: str
    type: JobType
    name: str
    language: str | None
    status: JobStatus = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    result: dict | None = None
    # Processing inputs, internal only — never serialized to the API.
    raw_path: str | None = None
    video_id: str | None = None
    video_url: str | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_queue: "queue.Queue[str]" = queue.Queue()
_worker_started = False


def _enqueue(job: Job) -> Job:
    with _lock:
        _jobs[job.id] = job
    _queue.put(job.id)
    return job


def create_file_job(raw_path: str, name: str, language: str | None) -> Job:
    job = Job(id=str(uuid.uuid4()), type="file", name=name, language=language, raw_path=raw_path)
    return _enqueue(job)


def create_youtube_job(video_id: str, video_url: str, name: str, language: str | None) -> Job:
    job = Job(
        id=str(uuid.uuid4()), type="youtube", name=name, language=language,
        video_id=video_id, video_url=video_url,
    )
    return _enqueue(job)


def create_error_job(job_type: JobType, name: str, reason: str) -> Job:
    now = time.time()
    job = Job(
        id=str(uuid.uuid4()), type=job_type, name=name, language=None,
        status="error", error=reason, created_at=now, started_at=now, finished_at=now,
    )
    with _lock:
        _jobs[job.id] = job
    _prune_finished()
    return job


def get_job(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def list_jobs() -> list[Job]:
    with _lock:
        return list(_jobs.values())


def clear_finished() -> None:
    with _lock:
        for job_id in [jid for jid, j in _jobs.items() if j.status in ("done", "error")]:
            del _jobs[job_id]


def _prune_finished() -> None:
    with _lock:
        finished_ids = [jid for jid, j in _jobs.items() if j.status in ("done", "error")]
        excess = len(finished_ids) - config.MAX_JOB_HISTORY
        for jid in finished_ids[:excess]:
            del _jobs[jid]


def _worker_loop() -> None:
    while True:
        job_id = _queue.get()
        job = get_job(job_id)
        if job is None:
            _queue.task_done()
            continue

        job.status = "processing"
        job.started_at = time.time()
        try:
            if job.type == "file":
                job.result = pipeline.process_file_job(job.raw_path, job.language)
            else:
                job.result = pipeline.process_youtube_job(job.video_id, job.video_url, job.language)
            job.status = "done"
        except HTTPException as exc:
            job.status = "error"
            job.error = str(exc.detail)
        except Exception as exc:
            logger.error("Job %s failed: %s", job.id, exc)
            job.status = "error"
            job.error = str(exc)
        finally:
            job.finished_at = time.time()
            _prune_finished()
            _queue.task_done()


def start_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    _worker_started = True
    threading.Thread(target=_worker_loop, daemon=True, name="transcription-worker").start()


def _base_dict(job: Job) -> dict:
    meta = {}
    if job.result:
        for key in ("duration_seconds", "processing_time_seconds", "source", "video_title"):
            if key in job.result:
                meta[key] = job.result[key]
    return {
        "id": job.id,
        "type": job.type,
        "name": job.name,
        "status": job.status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error,
        "meta": meta,
    }


def to_summary(job: Job) -> dict:
    return _base_dict(job)


def to_detail(job: Job) -> dict:
    data = _base_dict(job)
    data["result"] = job.result if job.status == "done" else None
    return data
