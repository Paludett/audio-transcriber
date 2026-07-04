import logging
import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .audio_utils import convert_to_wav
from .transcriber import get_active_device, load_model, transcribe_audio

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
