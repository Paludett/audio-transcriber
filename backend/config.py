import os

from dotenv import load_dotenv

load_dotenv()

# Default model: "small" comfortably fits in 4GB VRAM with int8_float16.
# "medium" with int8 is still safe; "large-v3" will probably exceed 4GB.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8_float16")
DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
DEFAULT_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "en")

# Upload size limit in bytes (default 100MB)
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(100 * 1024 * 1024)))

ALLOWED_EXTENSIONS = {".opus", ".ogg", ".m4a", ".mp3", ".wav"}

# YouTube transcription pipeline (captions first, Whisper fallback)
YOUTUBE_MAX_DURATION_SECONDS = int(os.getenv("YOUTUBE_MAX_DURATION_SECONDS", str(2 * 60 * 60)))
YOUTUBE_MAX_DOWNLOAD_BYTES = int(os.getenv("YOUTUBE_MAX_DOWNLOAD_BYTES", str(500 * 1024 * 1024)))
YOUTUBE_ACCEPT_AUTO_CAPTIONS = os.getenv("YOUTUBE_ACCEPT_AUTO_CAPTIONS", "true").lower() in ("1", "true", "yes")

# Security boundary, not runtime config: keep hardcoded like ALLOWED_EXTENSIONS above.
ALLOWED_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
