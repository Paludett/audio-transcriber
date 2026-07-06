import logging
import os
import shutil

from fastapi import HTTPException

from . import config
from .audio_utils import convert_to_wav
from .transcriber import transcribe_audio
from .youtube_utils import fetch_captions, get_video_info, download_audio

logger = logging.getLogger("pipeline")


def process_file_job(raw_path: str, language: str | None) -> dict:
    """Convert and transcribe an already-saved raw upload. Owns cleanup of raw_path/wav_path."""
    wav_path = None
    try:
        wav_path = convert_to_wav(raw_path)
        try:
            return transcribe_audio(wav_path, language=language)
        except Exception as exc:
            logger.error("Transcription failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to transcribe audio: {exc}")
    finally:
        for p in (raw_path, wav_path):
            if p and os.path.exists(p):
                os.remove(p)


def process_youtube_job(video_id: str, video_url: str, language: str | None) -> dict:
    """Fetch captions or fall back to downloading + transcribing a YouTube video."""
    info = get_video_info(video_id, video_url)

    if info["duration_seconds"] > config.YOUTUBE_MAX_DURATION_SECONDS:
        raise HTTPException(
            status_code=413,
            detail=f"Video exceeds the maximum allowed duration of {config.YOUTUBE_MAX_DURATION_SECONDS}s.",
        )

    captions = fetch_captions(video_id, language)
    if captions is not None:
        return {
            **captions,
            "duration_seconds": info["duration_seconds"],
            "source": "captions",
            "video_id": video_id,
            "video_title": info["title"],
            "video_url": video_url,
        }

    raw_path, yt_tmp_dir = download_audio(video_id, video_url)
    wav_path = None
    try:
        wav_path = convert_to_wav(raw_path)
        try:
            result = transcribe_audio(wav_path, language=language)
        except Exception as exc:
            logger.error("YouTube transcription failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to transcribe audio: {exc}")

        return {
            **result,
            "source": "whisper",
            "video_id": video_id,
            "video_title": info["title"],
            "video_url": video_url,
        }
    finally:
        shutil.rmtree(yt_tmp_dir, ignore_errors=True)
        if wav_path and os.path.exists(wav_path):
            os.remove(wav_path)
