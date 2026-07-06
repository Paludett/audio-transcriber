import logging
import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import config, jobs, pipeline
from .transcriber import get_active_device, load_model
from .youtube_utils import canonical_url, extract_video_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    jobs.start_worker()
    yield


app = FastAPI(title="Local Transcriber", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local use, no auth required
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "device": get_active_device(), "model": config.WHISPER_MODEL}


class YoutubeTranscribeRequest(BaseModel):
    url: str
    language: str | None = None


@app.post("/transcribe/youtube")
async def transcribe_youtube(payload: YoutubeTranscribeRequest):
    try:
        video_id = extract_video_id(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    url = canonical_url(video_id)
    return pipeline.process_youtube_job(video_id, url, payload.language)


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...), language: str | None = Form(None)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Extension '{ext}' is not supported. Use: {', '.join(sorted(config.ALLOWED_EXTENSIONS))}",
        )

    raw_fd, raw_path = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(raw_fd, "wb") as f:
            size = 0
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > config.MAX_UPLOAD_SIZE:
                    raise HTTPException(status_code=413, detail="File exceeds the maximum allowed size.")
                f.write(chunk)

        if size == 0:
            raise HTTPException(status_code=400, detail="Empty file.")
    except Exception:
        if os.path.exists(raw_path):
            os.remove(raw_path)
        raise

    return pipeline.process_file_job(raw_path, language)


@app.post("/jobs/files")
async def create_file_jobs(files: list[UploadFile] = File(...), language: str | None = Form(None)):
    created = []
    for file in files:
        name = file.filename or "unknown"
        ext = os.path.splitext(name)[1].lower()
        if ext not in config.ALLOWED_EXTENSIONS:
            job = jobs.create_error_job(
                "file", name,
                f"Extension '{ext}' is not supported. Use: {', '.join(sorted(config.ALLOWED_EXTENSIONS))}",
            )
            created.append(job.id)
            continue

        raw_fd, raw_path = tempfile.mkstemp(suffix=ext)
        try:
            size = 0
            oversized = False
            with os.fdopen(raw_fd, "wb") as f:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > config.MAX_UPLOAD_SIZE:
                        oversized = True
                        break
                    f.write(chunk)

            if oversized or size == 0:
                os.remove(raw_path)
                reason = "File exceeds the maximum allowed size." if oversized else "Empty file."
                job = jobs.create_error_job("file", name, reason)
            else:
                job = jobs.create_file_job(raw_path, name, language)
        except Exception as exc:
            if os.path.exists(raw_path):
                os.remove(raw_path)
            job = jobs.create_error_job("file", name, str(exc))
        created.append(job.id)

    return {"created": created}


class YoutubeJobsRequest(BaseModel):
    urls: list[str]
    language: str | None = None


@app.post("/jobs/youtube")
async def create_youtube_jobs(payload: YoutubeJobsRequest):
    created = []
    for url in payload.urls:
        try:
            video_id = extract_video_id(url)
        except ValueError as exc:
            job = jobs.create_error_job("youtube", url, str(exc))
        else:
            job = jobs.create_youtube_job(video_id, canonical_url(video_id), url, payload.language)
        created.append(job.id)

    return {"created": created}


@app.get("/jobs")
def list_jobs():
    return [jobs.to_summary(j) for j in jobs.list_jobs()]


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return jobs.to_detail(job)


@app.delete("/jobs/finished")
def clear_finished_jobs():
    jobs.clear_finished()
    return {"ok": True}
