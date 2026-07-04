import logging
import os
import shutil
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import config
from .audio_utils import convert_to_wav
from .transcriber import get_active_device, load_model, transcribe_audio
from .youtube_utils import canonical_url, download_audio, extract_video_id, fetch_captions, get_video_info

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
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
    info = get_video_info(video_id, url)

    if info["duration_seconds"] > config.YOUTUBE_MAX_DURATION_SECONDS:
        raise HTTPException(
            status_code=413,
            detail=f"Video exceeds the maximum allowed duration of {config.YOUTUBE_MAX_DURATION_SECONDS}s.",
        )

    captions = fetch_captions(video_id, payload.language)
    if captions is not None:
        return {
            **captions,
            "duration_seconds": info["duration_seconds"],
            "source": "captions",
            "video_id": video_id,
            "video_title": info["title"],
            "video_url": url,
        }

    raw_path, yt_tmp_dir = download_audio(video_id, url)
    wav_path = None
    try:
        wav_path = convert_to_wav(raw_path)

        try:
            result = transcribe_audio(wav_path, language=payload.language)
        except Exception as exc:
            logger.error("YouTube transcription failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to transcribe audio: {exc}")

        return {
            **result,
            "source": "whisper",
            "video_id": video_id,
            "video_title": info["title"],
            "video_url": url,
        }
    finally:
        shutil.rmtree(yt_tmp_dir, ignore_errors=True)
        if wav_path and os.path.exists(wav_path):
            os.remove(wav_path)


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...), language: str | None = Form(None)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Extension '{ext}' is not supported. Use: {', '.join(sorted(config.ALLOWED_EXTENSIONS))}",
        )

    raw_fd, raw_path = tempfile.mkstemp(suffix=ext)
    wav_path = None
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

        wav_path = convert_to_wav(raw_path)

        try:
            result = transcribe_audio(wav_path, language=language)
        except Exception as exc:
            logger.error("Transcription failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to transcribe audio: {exc}")

        return result
    finally:
        for p in (raw_path, wav_path):
            if p and os.path.exists(p):
                os.remove(p)
