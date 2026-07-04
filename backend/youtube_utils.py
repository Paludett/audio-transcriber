import logging
import re
import shutil
import tempfile
import time
from urllib.parse import parse_qs, urlparse

import yt_dlp
from fastapi import HTTPException
from youtube_transcript_api import CouldNotRetrieveTranscript, YouTubeTranscriptApi

from . import config

logger = logging.getLogger("youtube_utils")

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(url: str) -> str:
    """Validate the URL is a YouTube link and return its 11-char video ID.

    Raises ValueError (not HTTPException): this is pure input validation with no
    I/O, kept distinct from the network-backed functions below so main.py can map
    it to a 400 at the HTTP boundary, mirroring the extension check in main.py.
    """
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host not in config.ALLOWED_YOUTUBE_HOSTS:
        raise ValueError(f"'{host or url}' is not a supported YouTube URL.")

    if host == "youtu.be":
        video_id = parsed.path.lstrip("/")
    else:
        query_id = parse_qs(parsed.query).get("v", [None])[0]
        if query_id:
            video_id = query_id
        else:
            # /shorts/<id> and /embed/<id> style paths
            parts = [p for p in parsed.path.split("/") if p]
            video_id = parts[-1] if parts else ""

    if not _VIDEO_ID_RE.match(video_id or ""):
        raise ValueError(f"Could not extract a valid video ID from '{url}'.")

    return video_id


def canonical_url(video_id: str) -> str:
    """Rebuild a clean watch URL from a validated ID — never pass the user's raw
    string downstream, so no query-string smuggling reaches yt-dlp/transcript-api."""
    return f"https://www.youtube.com/watch?v={video_id}"


def get_video_info(video_id: str, url: str) -> dict:
    """Metadata-only lookup (no download). Returns {"title", "duration_seconds"}."""
    ydl_opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True, "noprogress": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise HTTPException(status_code=404, detail=f"Could not access YouTube video: {exc}") from exc

    if info.get("is_live"):
        raise HTTPException(status_code=422, detail="Live streams in progress are not supported.")

    return {
        "title": info.get("title") or video_id,
        "duration_seconds": float(info.get("duration") or 0),
    }


def fetch_captions(video_id: str, language: str | None) -> dict | None:
    """Try official YouTube captions. Returns None (never raises) when no caption
    track is usable, signaling the caller to fall back to Whisper."""
    languages = [language] if language else [config.DEFAULT_LANGUAGE, "en"]

    start = time.perf_counter()
    try:
        transcript_list = YouTubeTranscriptApi().list(video_id)

        try:
            transcript = transcript_list.find_manually_created_transcript(languages)
        except Exception:
            if not config.YOUTUBE_ACCEPT_AUTO_CAPTIONS:
                return None
            transcript = transcript_list.find_generated_transcript(languages)

        fetched = transcript.fetch()
    except CouldNotRetrieveTranscript:
        return None
    except Exception as exc:
        logger.warning("Unexpected error fetching captions for %s: %s", video_id, exc)
        return None

    segments = [
        {"start": snippet.start, "end": snippet.start + snippet.duration, "text": snippet.text.strip()}
        for snippet in fetched
    ]
    processing_time = time.perf_counter() - start

    return {
        "text": " ".join(s["text"] for s in segments).strip(),
        "segments": segments,
        "processing_time_seconds": processing_time,
    }


def download_audio(video_id: str, url: str) -> tuple[str, str]:
    """Download the best-audio stream to a scratch dir. Returns (audio_path, scratch_dir);
    caller must shutil.rmtree(scratch_dir, ignore_errors=True) when done."""
    tmp_dir = tempfile.mkdtemp(prefix="yt_audio_")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"{tmp_dir}/audio.%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "max_filesize": config.YOUTUBE_MAX_DOWNLOAD_BYTES,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        return info["requested_downloads"][0]["filepath"], tmp_dir
    except (yt_dlp.utils.DownloadError, KeyError, IndexError) as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"Failed to download audio from YouTube: {exc}") from exc
